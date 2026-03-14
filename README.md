# Takaada Integration Service

A production-grade integration service that syncs customer, invoice, and payment data from an external accounting system, stores it locally in PostgreSQL, and exposes financial receivables insights via a REST API.

---

## Quick Start

### Option A — Docker (Recommended, zero setup)

> **Requires:** [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) with WSL2 backend enabled.

```powershell
git clone <repo-url>
cd takaada-integration
docker compose up --build
```

Wait until you see `Application startup complete` in the logs (~20 seconds on first run while Postgres initialises).

This starts **three services**:

| Service | Port | What it is |
|---------|------|------------|
| PostgreSQL | `5432` | Database — internal use only, **not an HTTP server** |
| Mock Accounting API | `8001` | Simulates the external accounting system |
| Integration Service | `8000` | **The service you interact with** |

> **Note:** Opening `localhost:5432` in a browser will show "This page isn't working" — this is **correct and expected**. Port 5432 is a Postgres database port, not a web server. This is not an error.

Trigger the initial data sync:

```powershell
# PowerShell
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/v1/sync/run"
```

Visit **http://localhost:8000/docs** for the interactive Swagger UI.

---

### Option B — Local (without Docker)

**Prerequisites:**
- Python 3.12+ — [python.org/downloads](https://www.python.org/downloads/)
- PostgreSQL 14+ — [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
- Git — [git-scm.com](https://git-scm.com/)

#### Step 1 — Clone and create virtual environment

```powershell
git clone <repo-url>
cd takaada-integration
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

#### Step 2 — Configure .env

```powershell
copy .env.example .env
```

Now set your Postgres password. Replace `your_actual_password` with the password you set when installing PostgreSQL:

```powershell
# Update .env
(Get-Content .env) -replace 'YOUR_POSTGRES_PASSWORD', 'your_actual_password' | Set-Content .env
```

Update `alembic.ini` separately — **do not use the same replace command on it**, as `alembic.ini` uses a different placeholder format. Instead, set the `sqlalchemy.url` line directly:

```powershell
(Get-Content alembic.ini) -replace 'sqlalchemy.url = .*', 'sqlalchemy.url = postgresql+psycopg2://postgres:your_actual_password@127.0.0.1:5432/takaada' | Set-Content alembic.ini
```

> If your Postgres port is **5433** (non-default), use `5433` in the command above instead of `5432`.

Verify both files:
```powershell
Get-Content .env | Select-String "DATABASE_URL"
Get-Content alembic.ini | Select-String "sqlalchemy.url"
```

> **Non-default Postgres port?** The default is `5432`. If your Postgres was installed on a different port (e.g. `5433` — check in pgAdmin under Server Properties, or run `netstat -ano | findstr :543`), run this too:
> ```powershell
> (Get-Content .env) -replace ':5432/', ':5433/' | Set-Content .env
> ```
> And update `alembic.ini` to match:
> ```powershell
> (Get-Content alembic.ini) -replace ':5432/', ':5433/' | Set-Content alembic.ini
> ```

Verify the final values look correct:

```powershell
Get-Content .env | Select-String "DATABASE_URL"
```

Expected output (with your actual password and port):
```
DATABASE_URL=postgresql+asyncpg://postgres:your_actual_password@127.0.0.1:5432/takaada
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:your_actual_password@127.0.0.1:5432/takaada
```

> **Why `127.0.0.1` not `localhost`?** On Windows, `localhost` can resolve to IPv6 (`::1`) which PostgreSQL may not be listening on, causing a `getaddrinfo failed` error.

#### Step 3 — Create the database

```powershell
# Use -h 127.0.0.1 and -p with your actual port
psql -h 127.0.0.1 -p 5432 -U postgres -c "CREATE DATABASE takaada;"
```

> `ERROR: database "takaada" already exists` is fine — the database is already there, continue to Step 4.

#### Step 4 — Run migrations

```powershell
alembic upgrade head
```

You should see:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

Verify all tables were created:
```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d takaada -c "\dt"
```

Expected — 5 tables: `alembic_version`, `customers`, `invoices`, `payments`, `sync_logs`

> **If migration fails or shows no tables**, reset and retry:
> ```powershell
> psql -h 127.0.0.1 -p 5432 -U postgres -d takaada -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
> alembic upgrade head
> ```

#### Step 5 — Start the services

Open **Terminal 1** — Mock Accounting API:
```powershell
venv\Scripts\activate
uvicorn app.integrations.mock_server:app --port 8001
```

Open **Terminal 2** — Main service:
```powershell
venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

#### Step 6 — Trigger the initial sync

```powershell
# PowerShell (recommended)
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/v1/sync/run"

# Command Prompt with real curl (note: curl in PowerShell is an alias — use curl.exe or CMD)
curl.exe -X POST http://localhost:8000/api/v1/sync/run
```

> **`curl -X` fails in PowerShell?** PowerShell's built-in `curl` is an alias for `Invoke-WebRequest` and doesn't support `-X`. Use `Invoke-RestMethod` above, or `curl.exe` (with `.exe`) to invoke the real curl binary.

Expected response:
```json
{"status": "success", "customers_synced": 5, "invoices_synced": 8, "payments_synced": 4, "error_message": null}
```

Visit **http://localhost:8000/docs** for the interactive Swagger UI.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/sync/run` | Trigger sync (blocking) |
| `POST` | `/api/v1/sync` | Trigger sync (background) |
| `GET` | `/api/v1/sync/logs` | Recent sync history |
| `GET` | `/api/v1/customers` | List all customers (paginated) |
| `GET` | `/api/v1/customers/{id}` | Get customer by ID |
| `GET` | `/api/v1/customers/{id}/invoices` | Customer's invoices |
| `GET` | `/api/v1/invoices` | List invoices (filter by `?status=overdue`) |
| `GET` | `/api/v1/insights/portfolio` | Portfolio-level financial summary |
| `GET` | `/api/v1/insights/overdue` | All overdue invoices across portfolio |
| `GET` | `/api/v1/insights/customers/{id}` | Full credit insight for one customer |

Full interactive documentation: `http://localhost:8000/docs`

---

## Running Tests

```powershell
# Make sure venv is active
venv\Scripts\activate

pytest tests/ -v
```

Tests run entirely in-memory (SQLite) — no database or live API needed.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Application                   │
│                                                         │
│  Routes (/api/v1)                                       │
│    └── Thin handlers, param validation, HTTP mapping    │
│                                                         │
│  Services                                               │
│    ├── SyncService      orchestrates sync pipeline      │
│    ├── InsightsService  financial analytics queries     │
│    └── Scheduler        APScheduler background jobs     │
│                                                         │
│  Repositories                                           │
│    ├── CustomerRepository    upsert + queries           │
│    ├── InvoiceRepository     upsert + queries           │
│    ├── PaymentRepository     upsert + queries           │
│    └── SyncLogRepository     audit trail                │
│                                                         │
│  Integrations                                           │
│    └── ExternalAPIClient     HTTP + retry + pagination  │
│                                                         │
│  Models (SQLAlchemy)                                    │
│    Customer → Invoice → Payment                         │
│    SyncLog (audit)                                      │
└─────────────────────────────────────────────────────────┘
              │                        │
   ┌──────────▼──────────┐   ┌────────▼────────┐
   │     PostgreSQL      │   │  External API   │
   │   (local store)     │   │ (accounting sys)│
   └─────────────────────┘   └─────────────────┘
```

**Layering rule:** Data flows strictly downward. Routes call Services, Services call Repositories and Integrations. No layer skips another or calls upward.

---

## Database Schema

```
customers
├── id                  SERIAL PK
├── external_id         VARCHAR(255) UNIQUE NOT NULL   ← keyed for upsert
├── name, email, phone, address
├── credit_limit        NUMERIC(15,2)                  ← never float for money
├── is_active           BOOLEAN
└── last_synced_at      TIMESTAMPTZ

invoices
├── id                  SERIAL PK
├── external_id         VARCHAR(255) UNIQUE NOT NULL
├── customer_id         FK → customers.id
├── invoice_number      VARCHAR(100)
├── status              ENUM (draft|issued|partially_paid|paid|overdue|voided)
├── total_amount        NUMERIC(15,2)
├── paid_amount         NUMERIC(15,2)
├── outstanding_amount  NUMERIC(15,2)                  ← recomputed, not trusted
├── issue_date, due_date, paid_date
└── last_synced_at

payments
├── id                  SERIAL PK
├── external_id         VARCHAR(255) UNIQUE NOT NULL
├── invoice_id          FK → invoices.id
├── amount              NUMERIC(15,2)
├── payment_date
├── payment_method, reference_number
└── last_synced_at

sync_logs
├── id                  SERIAL PK
├── sync_type           VARCHAR(50)   (full | customers | invoices | payments)
├── status              ENUM (success | partial | failed)
├── started_at, completed_at
├── customers_synced, invoices_synced, payments_synced
└── error_message       (populated on failure)
```

**Key schema decisions:**

- `external_id` as the upsert key — makes syncs fully idempotent. Running the same sync twice produces the same result.
- `outstanding_amount` stored and recomputed from `total - paid`. Never blindly trusted from the external system.
- `Numeric(15,2)` for all monetary values. Floating point is never acceptable for financial data.
- Composite indexes on `(customer_id, status)` and `(due_date, status)` — the two most common query patterns for receivables.
- `SyncLog` table for every sync attempt — essential observability, especially when debugging why a record didn't appear.

---

## Design Decisions

### 1. Idempotent Sync via PostgreSQL `ON CONFLICT DO UPDATE`

Every upsert uses `INSERT ... ON CONFLICT (external_id) DO UPDATE`. This means:
- The sync is safe to run multiple times (scheduled every 15 mins)
- A re-run after a failure won't create duplicates
- Records not present in the external system are preserved locally (soft deletes handled via `is_active`)

### 2. Local Invoice Status Recomputation

The external system may not always mark a past-due invoice as `overdue` — this is a real-world integration problem. The `InvoiceRepository._resolve_status()` method re-derives status locally:

```
paid_amount >= total_amount            → PAID
past due_date AND paid_amount > 0      → OVERDUE (partial, but late)
past due_date AND paid_amount == 0     → OVERDUE
```

This ensures our data is always accurate regardless of the upstream system's reliability.

### 3. Retry with Exponential Backoff

`ExternalAPIClient._request()` retries on 5xx errors and timeouts with exponential backoff (`2^attempt` seconds). Rate limiting (429) respects the `Retry-After` header. After `MAX_RETRIES=3` attempts, a domain exception is raised and recorded in `SyncLog`.

### 4. Ordered Sync (Customers → Invoices → Payments)

The sync pipeline respects referential integrity: customers must exist before invoices can be linked, and invoices must exist before payments. If an invoice references an unknown `customer_id`, it's skipped and logged — the sync continues rather than aborting entirely.

### 5. Async Throughout

SQLAlchemy async + asyncpg + async APScheduler means the service never blocks on I/O. This matters when paginating through large datasets from the external API.

### 6. Separation of `outstanding_amount` Computation

`outstanding_amount` is stored in the DB (not just computed on read) to enable efficient aggregate queries in the insights endpoints without recomputing it per row at query time.

---

## Assumptions About the External API

Since the real external API wasn't provided, the following were assumed based on common accounting API conventions:

| Assumption | Rationale |
|------------|-----------|
| Paginated responses with `{ data, total, page, page_size, has_more }` | Standard pagination envelope |
| `X-API-Key` header for authentication | Common API key pattern; easily swapped for OAuth |
| `updated_since` query param for incremental sync | Standard for avoiding full re-fetches |
| Monetary amounts as strings (parsed to `Decimal`) | Avoids float precision issues in JSON |
| `customer_id` on invoices, `invoice_id` on payments | Standard FK reference by external ID |

The mock server (`app/integrations/mock_server.py`) implements all of these. Swapping to the real API only requires updating `EXTERNAL_API_BASE_URL` and `EXTERNAL_API_KEY` in `.env`.

---

## Example API Responses

### Portfolio Summary
```
GET /api/v1/insights/portfolio
```
```json
{
  "total_customers": 5,
  "active_customers": 4,
  "total_invoices": 8,
  "total_billed": "2180000.00",
  "total_collected": "755000.00",
  "total_outstanding": "1425000.00",
  "overdue_invoices": 3,
  "overdue_amount": "1180000.00",
  "collection_rate_pct": "34.63"
}
```

### Customer Credit Insight
```
GET /api/v1/insights/customers/4
```
```json
{
  "customer": {
    "id": 4,
    "name": "Sharma & Sons Trading Co.",
    "credit_limit": "1000000.00"
  },
  "receivables": {
    "total_outstanding": "625000.00",
    "overdue_amount": "625000.00",
    "credit_utilization_pct": "62.50"
  },
  "overdue_invoices": [
    {
      "invoice_number": "INV-2025-007",
      "due_date": "2025-01-26",
      "days_overdue": 45,
      "outstanding_amount": "625000.00"
    }
  ],
  "recent_payments": [
    {
      "amount": "250000.00",
      "payment_date": "2025-02-01",
      "payment_method": "Cheque",
      "reference_number": "CHQ-004892"
    }
  ]
}
```

---

## Trade-offs & What I'd Add Next

| What | Why not now | How I'd do it |
|------|-------------|---------------|
| Incremental sync (delta only) | Needs `last_sync_timestamp` tracking + external API support | Track `max(last_synced_at)` per entity type, pass as `updated_since` |
| Auth on our own API | Out of scope for assessment | FastAPI `HTTPBearer` + JWT, or API keys stored hashed in DB |
| Webhook receiver | Reduces sync lag from 15 min to near-real-time | `POST /webhooks/accounting` endpoint, validate HMAC signature |
| Soft deletes | Records deleted in external system silently disappear locally | Add `deleted_at` column; mark as deleted if absent from full sync |
| Alerting on overdue threshold | Valuable for collections workflow | APScheduler job emailing customers above X days overdue |
| Read replica | For analytics queries under load | SQLAlchemy supports multiple engine binds; route read-only queries to replica |
