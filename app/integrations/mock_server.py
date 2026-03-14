"""
Mock External Accounting API Server

Run this alongside the main app during development/testing:
    uvicorn app.integrations.mock_server:app --port 8001

This simulates the external accounting system with realistic data.
It's also used in tests via httpx's MockTransport.
"""

from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI, Query, Header, HTTPException
import random

app = FastAPI(title="Mock Accounting API", version="1.0.0")

# ─── Seed Data ────────────────────────────────────────────────────────────────

CUSTOMERS = [
    {
        "id": "cust_001", "name": "Raj Enterprises", "email": "raj@rajenterprises.in",
        "phone": "+91-9876543310", "address": "12 MG Road, Bengaluru, Karnataka 560001",
        "credit_limit": "500000.00", "is_active": True,
    },
    {
        "id": "cust_002", "name": "Patel Wholesale Distributors", "email": "accounts@patelwholesale.com",
        "phone": "+91-9988776655", "address": "44 APMC Market, Vashi, Navi Mumbai 400703",
        "credit_limit": "750000.00", "is_active": True,
    },
    {
        "id": "cust_003", "name": "Krishna General Merchants", "email": "krishna.gm@gmail.com",
        "phone": "+91-8877665544", "address": "78 Old Market Street, Hyderabad, Telangana 500002",
        "credit_limit": "200000.00", "is_active": True,
    },
    {
        "id": "cust_004", "name": "Sharma & Sons Trading Co.", "email": "sharma.sons@outlook.com",
        "phone": "+91-7766554433", "address": "Plot 5, Industrial Area, Ludhiana, Punjab 141003",
        "credit_limit": "1000000.00", "is_active": True,
    },
    {
        "id": "cust_005", "name": "Meena Distributors", "email": None,
        "phone": "+91-6655443322", "address": "22 Gandhi Nagar, Jaipur, Rajasthan 302015",
        "credit_limit": None, "is_active": False,  # Inactive customer — tests edge cases
    },
]

INVOICES = [
    # cust_001: 1 overdue, 1 paid, 1 outstanding
    {
        "id": "inv_001", "customer_id": "cust_001", "invoice_number": "INV-2025-001",
        "status": "overdue", "total_amount": "125000.00", "paid_amount": "0.00",
        "issue_date": str(date.today() - timedelta(days=60)),
        "due_date": str(date.today() - timedelta(days=30)), "paid_date": None,
        "notes": "Q1 stock replenishment",
    },
    {
        "id": "inv_002", "customer_id": "cust_001", "invoice_number": "INV-2025-002",
        "status": "paid", "total_amount": "85000.00", "paid_amount": "85000.00",
        "issue_date": str(date.today() - timedelta(days=45)),
        "due_date": str(date.today() - timedelta(days=15)),
        "paid_date": str(date.today() - timedelta(days=10)),
        "notes": None,
    },
    {
        "id": "inv_003", "customer_id": "cust_001", "invoice_number": "INV-2025-003",
        "status": "issued", "total_amount": "210000.00", "paid_amount": "0.00",
        "issue_date": str(date.today() - timedelta(days=5)),
        "due_date": str(date.today() + timedelta(days=25)), "paid_date": None,
        "notes": "Festival season stock",
    },
    # cust_002: partially paid + overdue
    {
        "id": "inv_004", "customer_id": "cust_002", "invoice_number": "INV-2025-004",
        "status": "partially_paid", "total_amount": "340000.00", "paid_amount": "100000.00",
        "issue_date": str(date.today() - timedelta(days=50)),
        "due_date": str(date.today() - timedelta(days=20)), "paid_date": None,
        "notes": None,
    },
    {
        "id": "inv_005", "customer_id": "cust_002", "invoice_number": "INV-2025-005",
        "status": "overdue", "total_amount": "180000.00", "paid_amount": "0.00",
        "issue_date": str(date.today() - timedelta(days=90)),
        "due_date": str(date.today() - timedelta(days=60)), "paid_date": None,
        "notes": "Long overdue — escalate to collections",
    },
    # cust_003
    {
        "id": "inv_006", "customer_id": "cust_003", "invoice_number": "INV-2025-006",
        "status": "issued", "total_amount": "45000.00", "paid_amount": "0.00",
        "issue_date": str(date.today() - timedelta(days=10)),
        "due_date": str(date.today() + timedelta(days=20)), "paid_date": None,
        "notes": None,
    },
    # cust_004: large amounts
    {
        "id": "inv_007", "customer_id": "cust_004", "invoice_number": "INV-2025-007",
        "status": "overdue", "total_amount": "875000.00", "paid_amount": "250000.00",
        "issue_date": str(date.today() - timedelta(days=75)),
        "due_date": str(date.today() - timedelta(days=45)), "paid_date": None,
        "notes": "Bulk annual order — partial payment received",
    },
    {
        "id": "inv_008", "customer_id": "cust_004", "invoice_number": "INV-2025-008",
        "status": "paid", "total_amount": "320000.00", "paid_amount": "320000.00",
        "issue_date": str(date.today() - timedelta(days=30)),
        "due_date": str(date.today() - timedelta(days=5)),
        "paid_date": str(date.today() - timedelta(days=3)),
        "notes": None,
    },
]

PAYMENTS = [
    {
        "id": "pay_001", "invoice_id": "inv_002", "amount": "85000.00",
        "payment_date": str(date.today() - timedelta(days=10)),
        "payment_method": "NEFT", "reference_number": "NEFT20250301001", "notes": None,
    },
    {
        "id": "pay_002", "invoice_id": "inv_004", "amount": "100000.00",
        "payment_date": str(date.today() - timedelta(days=25)),
        "payment_method": "RTGS", "reference_number": "RTGS20250215001", "notes": "Partial payment",
    },
    {
        "id": "pay_003", "invoice_id": "inv_007", "amount": "250000.00",
        "payment_date": str(date.today() - timedelta(days=40)),
        "payment_method": "Cheque", "reference_number": "CHQ-004892", "notes": None,
    },
    {
        "id": "pay_004", "invoice_id": "inv_008", "amount": "320000.00",
        "payment_date": str(date.today() - timedelta(days=3)),
        "payment_method": "IMPS", "reference_number": "IMPS20250310001", "notes": None,
    },
]


# ─── Auth middleware ───────────────────────────────────────────────────────────

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != "mock-api-key-change-in-prod":
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Pagination helper ─────────────────────────────────────────────────────────

def paginate(items: list, page: int, page_size: int) -> dict:
    start = (page - 1) * page_size
    end = start + page_size
    slice_ = items[start:end]
    return {
        "data": slice_,
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "has_more": end < len(items),
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/v1/customers")
def list_customers(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    return paginate(CUSTOMERS, page, page_size)


@app.get("/v1/customers/{customer_id}")
def get_customer(customer_id: str):
    for c in CUSTOMERS:
        if c["id"] == customer_id:
            return c
    raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")


@app.get("/v1/invoices")
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    updated_since: str | None = Query(None),
):
    # updated_since filtering is mocked (no-op) for simplicity
    return paginate(INVOICES, page, page_size)


@app.get("/v1/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    for i in INVOICES:
        if i["id"] == invoice_id:
            return i
    raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")


@app.get("/v1/payments")
def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    updated_since: str | None = Query(None),
):
    return paginate(PAYMENTS, page, page_size)
