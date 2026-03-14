"""
API Routes for the Takaada Integration Service.

Versioned under /api/v1. Routes are thin — they delegate to services,
handle pagination params, and map exceptions to HTTP responses.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundException
from app.db.session import get_db
from app.models.models import InvoiceStatus
from app.repositories.repositories import (
    CustomerRepository,
    InvoiceRepository,
    SyncLogRepository,
)
from app.schemas.schemas import (
    CustomerCreditInsight,
    CustomerResponse,
    InvoiceResponse,
    PaginatedCustomers,
    PaginatedInvoices,
    PortfolioSummary,
    SyncLogResponse,
    SyncTriggerResponse,
)
from app.services.insights_service import insights_service
from app.services.sync_service import sync_service

router = APIRouter()


# ─── Sync Endpoints ───────────────────────────────────────────────────────────

@router.post(
    "/sync",
    response_model=SyncTriggerResponse,
    summary="Trigger a full data sync",
    tags=["Sync"],
)
async def trigger_sync(background_tasks: BackgroundTasks):
    """
    Enqueues a full sync as a background task.
    Returns immediately — poll /sync/logs for status.
    """
    background_tasks.add_task(sync_service.run_full_sync)
    return SyncTriggerResponse(
        message="Sync started in background. Check /api/v1/sync/logs for status.",
        sync_log_id=0,  # ID not yet known since it's async; check logs endpoint
    )


@router.post(
    "/sync/run",
    summary="Trigger sync and wait for completion (blocking)",
    tags=["Sync"],
)
async def trigger_sync_blocking():
    """
    Runs sync synchronously and returns the result.
    Use this for testing / manual triggers.
    """
    result = await sync_service.run_full_sync()
    return result


@router.get(
    "/sync/logs",
    response_model=list[SyncLogResponse],
    summary="List recent sync logs",
    tags=["Sync"],
)
async def list_sync_logs(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    repo = SyncLogRepository(db)
    logs = await repo.list_recent(limit=limit)
    return logs


# ─── Customer Endpoints ───────────────────────────────────────────────────────

@router.get(
    "/customers",
    response_model=PaginatedCustomers,
    summary="List all customers",
    tags=["Customers"],
)
async def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    repo = CustomerRepository(db)
    customers, total = await repo.list_all(page=page, page_size=page_size)
    return PaginatedCustomers(
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
        items=[CustomerResponse.model_validate(c) for c in customers],
    )


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    summary="Get customer by internal ID",
    tags=["Customers"],
)
async def get_customer(customer_id: int, db: AsyncSession = Depends(get_db)):
    repo = CustomerRepository(db)
    customer = await repo.get_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found.")
    return CustomerResponse.model_validate(customer)


@router.get(
    "/customers/{customer_id}/invoices",
    response_model=PaginatedInvoices,
    summary="List invoices for a customer",
    tags=["Customers"],
)
async def list_customer_invoices(
    customer_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    repo = InvoiceRepository(db)
    invoices, total = await repo.list_for_customer(customer_id, page=page, page_size=page_size)
    return PaginatedInvoices(
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
        items=[InvoiceResponse.model_validate(i) for i in invoices],
    )


# ─── Invoice Endpoints ────────────────────────────────────────────────────────

@router.get(
    "/invoices",
    response_model=PaginatedInvoices,
    summary="List all invoices with optional status filter",
    tags=["Invoices"],
)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="Filter by status: overdue, paid, issued, partially_paid, voided"),
    db: AsyncSession = Depends(get_db),
):
    # Validate status if provided
    if status:
        try:
            InvoiceStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{status}'. Valid values: {[s.value for s in InvoiceStatus]}",
            )

    repo = InvoiceRepository(db)
    invoices, total = await repo.list_all(page=page, page_size=page_size, status=status)
    return PaginatedInvoices(
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
        items=[InvoiceResponse.model_validate(i) for i in invoices],
    )


# ─── Insights / Analytics Endpoints ──────────────────────────────────────────

@router.get(
    "/insights/portfolio",
    response_model=PortfolioSummary,
    summary="Portfolio-level receivables summary",
    tags=["Insights"],
)
async def get_portfolio_summary(db: AsyncSession = Depends(get_db)):
    """
    Returns aggregate financial health metrics across all customers:
    total billed, collected, outstanding, overdue amounts, and collection rate.
    """
    return await insights_service.get_portfolio_summary(db)


@router.get(
    "/insights/overdue",
    summary="All overdue invoices across the portfolio",
    tags=["Insights"],
)
async def get_overdue_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all overdue invoices sorted by due date (oldest first),
    including customer context and days overdue.
    """
    items, total = await insights_service.get_all_overdue_invoices(db, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (page * page_size) < total,
        "items": items,
    }


@router.get(
    "/insights/customers/{customer_id}",
    response_model=CustomerCreditInsight,
    summary="Full credit insight for a specific customer",
    tags=["Insights"],
)
async def get_customer_credit_insight(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a comprehensive credit profile for a customer:
    - Receivables summary (total billed, outstanding, overdue)
    - Credit utilization % (if credit limit is set)
    - Overdue invoices with days overdue
    - Recent payment history
    """
    try:
        return await insights_service.get_customer_credit_insight(customer_id, db)
    except ResourceNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
