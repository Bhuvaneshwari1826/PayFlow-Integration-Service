"""
Pydantic schemas for API I/O and external API response parsing.

Design: Separate schemas for external API payloads vs internal API responses
to decouple our API contract from upstream changes.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.models import InvoiceStatus, SyncStatus


# ─── External API Schemas (what the accounting system returns) ────────────────

class ExternalCustomer(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    is_active: bool = True


class ExternalInvoice(BaseModel):
    id: str
    customer_id: str
    invoice_number: str
    status: str
    total_amount: Decimal
    paid_amount: Decimal
    issue_date: date
    due_date: date
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class ExternalPayment(BaseModel):
    id: str
    invoice_id: str
    amount: Decimal
    payment_date: date
    payment_method: Optional[str] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class ExternalPaginatedResponse(BaseModel):
    data: list
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── Internal API Response Schemas ───────────────────────────────────────────

class CustomerBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    is_active: bool


class CustomerResponse(CustomerBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_synced_at: Optional[datetime] = None


class InvoiceBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    invoice_number: str
    status: InvoiceStatus
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    issue_date: date
    due_date: date
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class InvoiceResponse(InvoiceBase):
    id: int
    customer_id: int
    created_at: datetime
    updated_at: datetime
    last_synced_at: Optional[datetime] = None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    invoice_id: int
    amount: Decimal
    payment_date: date
    payment_method: Optional[str] = None
    reference_number: Optional[str] = None
    created_at: datetime


# ─── Insight / Analytics Schemas ──────────────────────────────────────────────

class OverdueInvoiceSummary(BaseModel):
    invoice_id: int
    external_id: str
    invoice_number: str
    due_date: date
    days_overdue: int
    outstanding_amount: Decimal


class CustomerReceivablesSummary(BaseModel):
    customer_id: int
    external_id: str
    name: str
    email: Optional[str] = None
    credit_limit: Optional[Decimal] = None

    total_invoices: int
    total_billed: Decimal
    total_paid: Decimal
    total_outstanding: Decimal

    overdue_invoices: int
    overdue_amount: Decimal

    # Useful for risk scoring
    credit_utilization_pct: Optional[Decimal] = None  # outstanding / credit_limit


class PortfolioSummary(BaseModel):
    """Aggregate view across all customers — top-level dashboard metric."""
    total_customers: int
    active_customers: int

    total_invoices: int
    total_billed: Decimal
    total_collected: Decimal
    total_outstanding: Decimal

    overdue_invoices: int
    overdue_amount: Decimal

    collection_rate_pct: Decimal  # total_collected / total_billed * 100


class CustomerCreditInsight(BaseModel):
    """Deep dive into a single customer's credit profile."""
    customer: CustomerResponse
    receivables: CustomerReceivablesSummary
    overdue_invoices: list[OverdueInvoiceSummary]
    recent_payments: list[PaymentResponse]


# ─── Sync Schemas ─────────────────────────────────────────────────────────────

class SyncLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sync_type: str
    status: SyncStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    customers_synced: int
    invoices_synced: int
    payments_synced: int
    error_message: Optional[str] = None


class SyncTriggerResponse(BaseModel):
    message: str
    sync_log_id: int


# ─── Pagination ───────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    has_more: bool
    items: list


class PaginatedCustomers(PaginatedResponse):
    items: list[CustomerResponse]


class PaginatedInvoices(PaginatedResponse):
    items: list[InvoiceResponse]
