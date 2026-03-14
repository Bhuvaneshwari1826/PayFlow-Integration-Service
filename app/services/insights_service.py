"""
Insights Service — computes financial analytics from locally stored data.

All heavy lifting is pushed to the DB via SQLAlchemy aggregations.
Python-level computation is only used for derived metrics (percentages, etc.).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundException
from app.core.logging import get_logger
from app.models.models import Customer, Invoice, Payment, InvoiceStatus
from app.repositories.repositories import CustomerRepository, PaymentRepository
from app.schemas.schemas import (
    CustomerCreditInsight,
    CustomerReceivablesSummary,
    CustomerResponse,
    OverdueInvoiceSummary,
    PaymentResponse,
    PortfolioSummary,
)

logger = get_logger(__name__)


class InsightsService:

    async def get_portfolio_summary(self, session: AsyncSession) -> PortfolioSummary:
        """
        Single-query aggregate across all customers and invoices.
        Returns top-level portfolio health metrics.
        """
        today = date.today()

        # Customer counts
        customer_counts = await session.execute(
            select(
                func.count(Customer.id).label("total"),
                func.count(case((Customer.is_active == True, 1))).label("active"),
            )
        )
        cust_row = customer_counts.one()

        # Invoice aggregations in one query
        invoice_agg = await session.execute(
            select(
                func.count(Invoice.id).label("total_invoices"),
                func.coalesce(func.sum(Invoice.total_amount), Decimal("0")).label("total_billed"),
                func.coalesce(func.sum(Invoice.paid_amount), Decimal("0")).label("total_collected"),
                func.coalesce(func.sum(Invoice.outstanding_amount), Decimal("0")).label("total_outstanding"),
                func.count(
                    case((Invoice.status == InvoiceStatus.OVERDUE, 1))
                ).label("overdue_invoices"),
                func.coalesce(
                    func.sum(
                        case((Invoice.status == InvoiceStatus.OVERDUE, Invoice.outstanding_amount), else_=Decimal("0"))
                    ),
                    Decimal("0"),
                ).label("overdue_amount"),
            ).where(Invoice.status != InvoiceStatus.VOIDED)
        )
        inv_row = invoice_agg.one()

        total_billed = inv_row.total_billed or Decimal("0")
        total_collected = inv_row.total_collected or Decimal("0")
        collection_rate = (
            (total_collected / total_billed * 100).quantize(Decimal("0.01"))
            if total_billed > 0
            else Decimal("0")
        )

        return PortfolioSummary(
            total_customers=cust_row.total,
            active_customers=cust_row.active,
            total_invoices=inv_row.total_invoices,
            total_billed=total_billed,
            total_collected=total_collected,
            total_outstanding=inv_row.total_outstanding or Decimal("0"),
            overdue_invoices=inv_row.overdue_invoices,
            overdue_amount=inv_row.overdue_amount or Decimal("0"),
            collection_rate_pct=collection_rate,
        )

    async def get_customer_receivables(
        self, customer_id: int, session: AsyncSession
    ) -> CustomerReceivablesSummary:
        """Compute receivables summary for a single customer."""
        today = date.today()
        customer_repo = CustomerRepository(session)
        customer = await customer_repo.get_by_id(customer_id)
        if not customer:
            raise ResourceNotFoundException("Customer", str(customer_id))

        agg = await session.execute(
            select(
                func.count(Invoice.id).label("total_invoices"),
                func.coalesce(func.sum(Invoice.total_amount), Decimal("0")).label("total_billed"),
                func.coalesce(func.sum(Invoice.paid_amount), Decimal("0")).label("total_paid"),
                func.coalesce(func.sum(Invoice.outstanding_amount), Decimal("0")).label("total_outstanding"),
                func.count(
                    case((Invoice.status == InvoiceStatus.OVERDUE, 1))
                ).label("overdue_invoices"),
                func.coalesce(
                    func.sum(
                        case(
                            (Invoice.status == InvoiceStatus.OVERDUE, Invoice.outstanding_amount),
                            else_=Decimal("0"),
                        )
                    ),
                    Decimal("0"),
                ).label("overdue_amount"),
            ).where(
                and_(
                    Invoice.customer_id == customer_id,
                    Invoice.status != InvoiceStatus.VOIDED,
                )
            )
        )
        row = agg.one()

        credit_utilization = None
        if customer.credit_limit and customer.credit_limit > 0:
            credit_utilization = (
                (row.total_outstanding / customer.credit_limit * 100).quantize(Decimal("0.01"))
            )

        return CustomerReceivablesSummary(
            customer_id=customer.id,
            external_id=customer.external_id,
            name=customer.name,
            email=customer.email,
            credit_limit=customer.credit_limit,
            total_invoices=row.total_invoices,
            total_billed=row.total_billed or Decimal("0"),
            total_paid=row.total_paid or Decimal("0"),
            total_outstanding=row.total_outstanding or Decimal("0"),
            overdue_invoices=row.overdue_invoices,
            overdue_amount=row.overdue_amount or Decimal("0"),
            credit_utilization_pct=credit_utilization,
        )

    async def get_customer_credit_insight(
        self, customer_id: int, session: AsyncSession
    ) -> CustomerCreditInsight:
        """Full credit insight for a customer: summary + overdue invoices + recent payments."""
        customer_repo = CustomerRepository(session)
        payment_repo = PaymentRepository(session)

        customer = await customer_repo.get_by_id(customer_id)
        if not customer:
            raise ResourceNotFoundException("Customer", str(customer_id))

        receivables = await self.get_customer_receivables(customer_id, session)

        # Overdue invoices with days_overdue computed in Python (simple, readable)
        overdue_result = await session.execute(
            select(Invoice).where(
                and_(
                    Invoice.customer_id == customer_id,
                    Invoice.status == InvoiceStatus.OVERDUE,
                )
            ).order_by(Invoice.due_date.asc())
        )
        overdue_invoices_raw = overdue_result.scalars().all()
        today = date.today()
        overdue_summaries = [
            OverdueInvoiceSummary(
                invoice_id=inv.id,
                external_id=inv.external_id,
                invoice_number=inv.invoice_number,
                due_date=inv.due_date,
                days_overdue=(today - inv.due_date).days,
                outstanding_amount=inv.outstanding_amount,
            )
            for inv in overdue_invoices_raw
        ]

        # Recent payments
        recent_payments_raw = await payment_repo.get_recent_for_customer(customer_id, limit=5)

        return CustomerCreditInsight(
            customer=CustomerResponse.model_validate(customer),
            receivables=receivables,
            overdue_invoices=overdue_summaries,
            recent_payments=[PaymentResponse.model_validate(p) for p in recent_payments_raw],
        )

    async def get_all_overdue_invoices(
        self, session: AsyncSession, page: int = 1, page_size: int = 20
    ) -> tuple[list, int]:
        """Paginated list of all overdue invoices across all customers."""
        today = date.today()
        offset = (page - 1) * page_size

        count_result = await session.execute(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.OVERDUE)
        )
        total = count_result.scalar_one()

        result = await session.execute(
            select(Invoice, Customer)
            .join(Customer, Invoice.customer_id == Customer.id)
            .where(Invoice.status == InvoiceStatus.OVERDUE)
            .order_by(Invoice.due_date.asc())
            .offset(offset)
            .limit(page_size)
        )
        rows = result.all()

        items = [
            {
                "invoice_id": inv.id,
                "external_id": inv.external_id,
                "invoice_number": inv.invoice_number,
                "due_date": inv.due_date,
                "days_overdue": (today - inv.due_date).days,
                "outstanding_amount": inv.outstanding_amount,
                "customer_id": cust.id,
                "customer_name": cust.name,
                "customer_external_id": cust.external_id,
            }
            for inv, cust in rows
        ]
        return items, total


insights_service = InsightsService()
