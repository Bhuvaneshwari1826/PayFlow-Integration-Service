"""
Repository Layer — all database access lives here.

Design:
- Repositories are pure DB I/O. No business logic.
- Upsert pattern (insert or update) keyed on external_id for idempotent syncs.
- All queries use async SQLAlchemy 2.0 style.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, update, and_, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Customer, Invoice, Payment, SyncLog, InvoiceStatus, SyncStatus
from app.schemas.schemas import ExternalCustomer, ExternalInvoice, ExternalPayment
from app.core.logging import get_logger

logger = get_logger(__name__)


class CustomerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, external: ExternalCustomer) -> Customer:
        """Insert or update a customer, keyed on external_id."""
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(Customer)
            .values(
                external_id=external.id,
                name=external.name,
                email=external.email,
                phone=external.phone,
                address=external.address,
                credit_limit=external.credit_limit,
                is_active=external.is_active,
                last_synced_at=now,
            )
            .on_conflict_do_update(
                index_elements=["external_id"],
                set_={
                    "name": external.name,
                    "email": external.email,
                    "phone": external.phone,
                    "address": external.address,
                    "credit_limit": external.credit_limit,
                    "is_active": external.is_active,
                    "last_synced_at": now,
                    "updated_at": now,
                },
            )
            .returning(Customer)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_by_external_id(self, external_id: str) -> Optional[Customer]:
        result = await self.session.execute(
            select(Customer).where(Customer.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, customer_id: int) -> Optional[Customer]:
        result = await self.session.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, page: int = 1, page_size: int = 20) -> tuple[list[Customer], int]:
        offset = (page - 1) * page_size
        count_result = await self.session.execute(select(func.count(Customer.id)))
        total = count_result.scalar_one()
        result = await self.session.execute(
            select(Customer).order_by(Customer.name).offset(offset).limit(page_size)
        )
        return result.scalars().all(), total


class InvoiceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _resolve_status(self, external_status: str, due_date: date, paid_amount: Decimal, total_amount: Decimal) -> InvoiceStatus:
        """
        Derive canonical status locally.
        External system may not always mark invoices as overdue automatically.
        """
        today = date.today()
        if external_status == "voided":
            return InvoiceStatus.VOIDED
        if paid_amount >= total_amount:
            return InvoiceStatus.PAID
        if paid_amount > 0 and due_date < today:
            return InvoiceStatus.OVERDUE  # partial payment but still past due
        if paid_amount > 0:
            return InvoiceStatus.PARTIALLY_PAID
        if due_date < today:
            return InvoiceStatus.OVERDUE
        try:
            return InvoiceStatus(external_status)
        except ValueError:
            return InvoiceStatus.ISSUED

    async def upsert(self, external: ExternalInvoice, customer_id: int) -> Invoice:
        """Upsert invoice. Outstanding amount is computed here, not trusted from external system."""
        now = datetime.now(timezone.utc)
        outstanding = external.total_amount - external.paid_amount
        status = self._resolve_status(
            external.status, external.due_date, external.paid_amount, external.total_amount
        )

        stmt = (
            pg_insert(Invoice)
            .values(
                external_id=external.id,
                customer_id=customer_id,
                invoice_number=external.invoice_number,
                status=status,
                total_amount=external.total_amount,
                paid_amount=external.paid_amount,
                outstanding_amount=outstanding,
                issue_date=external.issue_date,
                due_date=external.due_date,
                paid_date=external.paid_date,
                notes=external.notes,
                last_synced_at=now,
            )
            .on_conflict_do_update(
                index_elements=["external_id"],
                set_={
                    "customer_id": customer_id,
                    "invoice_number": external.invoice_number,
                    "status": status,
                    "total_amount": external.total_amount,
                    "paid_amount": external.paid_amount,
                    "outstanding_amount": outstanding,
                    "issue_date": external.issue_date,
                    "due_date": external.due_date,
                    "paid_date": external.paid_date,
                    "notes": external.notes,
                    "last_synced_at": now,
                    "updated_at": now,
                },
            )
            .returning(Invoice)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_by_external_id(self, external_id: str) -> Optional[Invoice]:
        result = await self.session.execute(
            select(Invoice).where(Invoice.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def list_for_customer(self, customer_id: int, page: int = 1, page_size: int = 20) -> tuple[list[Invoice], int]:
        offset = (page - 1) * page_size
        count_result = await self.session.execute(
            select(func.count(Invoice.id)).where(Invoice.customer_id == customer_id)
        )
        total = count_result.scalar_one()
        result = await self.session.execute(
            select(Invoice)
            .where(Invoice.customer_id == customer_id)
            .order_by(Invoice.due_date.desc())
            .offset(offset)
            .limit(page_size)
        )
        return result.scalars().all(), total

    async def get_overdue_for_customer(self, customer_id: int) -> list[Invoice]:
        result = await self.session.execute(
            select(Invoice).where(
                and_(
                    Invoice.customer_id == customer_id,
                    Invoice.status == InvoiceStatus.OVERDUE,
                )
            ).order_by(Invoice.due_date.asc())
        )
        return result.scalars().all()

    async def list_all(self, page: int = 1, page_size: int = 20, status: Optional[str] = None) -> tuple[list[Invoice], int]:
        offset = (page - 1) * page_size
        base_filter = []
        if status:
            base_filter.append(Invoice.status == InvoiceStatus(status))

        count_result = await self.session.execute(
            select(func.count(Invoice.id)).where(*base_filter) if base_filter
            else select(func.count(Invoice.id))
        )
        total = count_result.scalar_one()

        q = select(Invoice)
        if base_filter:
            q = q.where(*base_filter)
        result = await self.session.execute(
            q.order_by(Invoice.due_date.desc()).offset(offset).limit(page_size)
        )
        return result.scalars().all(), total


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, external: ExternalPayment, invoice_id: int) -> Payment:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(Payment)
            .values(
                external_id=external.id,
                invoice_id=invoice_id,
                amount=external.amount,
                payment_date=external.payment_date,
                payment_method=external.payment_method,
                reference_number=external.reference_number,
                notes=external.notes,
                last_synced_at=now,
            )
            .on_conflict_do_update(
                index_elements=["external_id"],
                set_={
                    "invoice_id": invoice_id,
                    "amount": external.amount,
                    "payment_date": external.payment_date,
                    "payment_method": external.payment_method,
                    "reference_number": external.reference_number,
                    "notes": external.notes,
                    "last_synced_at": now,
                    "updated_at": now,
                },
            )
            .returning(Payment)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_recent_for_customer(self, customer_id: int, limit: int = 5) -> list[Payment]:
        """Get recent payments across all invoices for a customer."""
        result = await self.session.execute(
            select(Payment)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .where(Invoice.customer_id == customer_id)
            .order_by(Payment.payment_date.desc())
            .limit(limit)
        )
        return result.scalars().all()


class SyncLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, sync_type: str) -> SyncLog:
        log = SyncLog(
            sync_type=sync_type,
            status=SyncStatus.PARTIAL,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def complete(
        self,
        log_id: int,
        status: SyncStatus,
        customers_synced: int = 0,
        invoices_synced: int = 0,
        payments_synced: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        await self.session.execute(
            update(SyncLog)
            .where(SyncLog.id == log_id)
            .values(
                status=status,
                completed_at=datetime.now(timezone.utc),
                customers_synced=customers_synced,
                invoices_synced=invoices_synced,
                payments_synced=payments_synced,
                error_message=error_message,
            )
        )

    async def list_recent(self, limit: int = 10) -> list[SyncLog]:
        result = await self.session.execute(
            select(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit)
        )
        return result.scalars().all()
