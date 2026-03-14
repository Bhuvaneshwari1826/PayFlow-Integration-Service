"""
Sync Service — orchestrates the full data sync pipeline.

Responsibilities:
- Fetch data from external API
- Resolve foreign keys (external customer_id → internal customer.id)
- Persist via repositories (upsert pattern)
- Record sync outcomes in SyncLog

Design:
- Order of sync is intentional: Customers → Invoices → Payments
  (invoices reference customers, payments reference invoices)
- A missing customer for an invoice is logged + skipped, not a hard failure
- Final sync status: SUCCESS if 0 errors, PARTIAL if some skipped, FAILED if all failed
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExternalAPIException, SyncException
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.integrations.external_api_client import ExternalAPIClient
from app.models.models import SyncStatus
from app.repositories.repositories import (
    CustomerRepository,
    InvoiceRepository,
    PaymentRepository,
    SyncLogRepository,
)

logger = get_logger(__name__)


class SyncService:
    """
    Orchestrates syncing data from the external accounting system into local DB.
    """

    async def run_full_sync(self) -> dict:
        """
        Execute a full sync of all entities.
        Returns a summary dict with counts and status.
        """
        logger.info("Starting full sync.")
        async with AsyncSessionLocal() as session:
            sync_log_repo = SyncLogRepository(session)
            log = await sync_log_repo.create("full")
            await session.commit()

            customers_synced = invoices_synced = payments_synced = 0
            error_message = None
            status = SyncStatus.SUCCESS

            try:
                async with ExternalAPIClient() as client:
                    # Step 1: Sync customers
                    customers_synced = await self._sync_customers(client, session)

                    # Step 2: Sync invoices (depends on customers existing)
                    invoices_synced = await self._sync_invoices(client, session)

                    # Step 3: Sync payments (depends on invoices existing)
                    payments_synced = await self._sync_payments(client, session)

            except ExternalAPIException as e:
                logger.error(f"External API error during sync: {e}")
                error_message = str(e)
                status = SyncStatus.FAILED
            except Exception as e:
                logger.exception(f"Unexpected error during sync: {e}")
                error_message = str(e)
                status = SyncStatus.FAILED
            finally:
                await sync_log_repo.complete(
                    log_id=log.id,
                    status=status,
                    customers_synced=customers_synced,
                    invoices_synced=invoices_synced,
                    payments_synced=payments_synced,
                    error_message=error_message,
                )
                await session.commit()

            logger.info(
                f"Sync complete. status={status} customers={customers_synced} "
                f"invoices={invoices_synced} payments={payments_synced}"
            )

            return {
                "status": status,
                "sync_log_id": log.id,
                "customers_synced": customers_synced,
                "invoices_synced": invoices_synced,
                "payments_synced": payments_synced,
                "error_message": error_message,
            }

    async def _sync_customers(self, client: ExternalAPIClient, session: AsyncSession) -> int:
        repo = CustomerRepository(session)
        external_customers = await client.fetch_all_customers()
        synced = 0
        for ext_customer in external_customers:
            try:
                await repo.upsert(ext_customer)
                synced += 1
            except Exception as e:
                logger.warning(f"Failed to upsert customer {ext_customer.id}: {e}")
        await session.commit()
        logger.info(f"Customers synced: {synced}/{len(external_customers)}")
        return synced

    async def _sync_invoices(self, client: ExternalAPIClient, session: AsyncSession) -> int:
        invoice_repo = InvoiceRepository(session)
        customer_repo = CustomerRepository(session)

        external_invoices = await client.fetch_all_invoices()
        synced = 0
        skipped = 0

        for ext_invoice in external_invoices:
            try:
                customer = await customer_repo.get_by_external_id(ext_invoice.customer_id)
                if not customer:
                    logger.warning(
                        f"Invoice {ext_invoice.id} references unknown customer "
                        f"{ext_invoice.customer_id}. Skipping."
                    )
                    skipped += 1
                    continue

                await invoice_repo.upsert(ext_invoice, customer.id)
                synced += 1
            except Exception as e:
                logger.warning(f"Failed to upsert invoice {ext_invoice.id}: {e}")
                skipped += 1

        await session.commit()
        logger.info(f"Invoices synced: {synced}/{len(external_invoices)} (skipped={skipped})")
        return synced

    async def _sync_payments(self, client: ExternalAPIClient, session: AsyncSession) -> int:
        payment_repo = PaymentRepository(session)
        invoice_repo = InvoiceRepository(session)

        external_payments = await client.fetch_all_payments()
        synced = 0
        skipped = 0

        for ext_payment in external_payments:
            try:
                invoice = await invoice_repo.get_by_external_id(ext_payment.invoice_id)
                if not invoice:
                    logger.warning(
                        f"Payment {ext_payment.id} references unknown invoice "
                        f"{ext_payment.invoice_id}. Skipping."
                    )
                    skipped += 1
                    continue

                await payment_repo.upsert(ext_payment, invoice.id)
                synced += 1
            except Exception as e:
                logger.warning(f"Failed to upsert payment {ext_payment.id}: {e}")
                skipped += 1

        await session.commit()
        logger.info(f"Payments synced: {synced}/{len(external_payments)} (skipped={skipped})")
        return synced


sync_service = SyncService()
