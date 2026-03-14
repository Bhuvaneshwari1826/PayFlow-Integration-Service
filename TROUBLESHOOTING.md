# Takaada Integration Service — Windows Troubleshooting Log

All errors encountered during local setup on Windows (PostgreSQL on port 5433, Anaconda Python, PowerShell), traced to root cause and resolved.

---

## Issue 1 — `type "invoice_status" already exists`

### Terminal Output
```
asyncpg.exceptions.DuplicateObjectError: type "invoice_status" already exists
sqlalchemy.exc.ProgrammingError: CREATE TYPE invoice_status AS ENUM (...)
```

### How It Was Traced
Migration ran partially — enums were created, then crashed before tables were built. On re-run, Postgres rejected the duplicate `CREATE TYPE`.

### Root Cause
The original migration called `postgresql.ENUM(...).create()` explicitly, then used `sa.Enum(name="invoice_status")` inside `create_table` — which triggered a second `CREATE TYPE` automatically. First run got partway, left orphaned types, every subsequent run hit the wall.

### Resolution
Replaced both calls with a PostgreSQL `DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL $$` block — the canonical Postgres-native idempotent pattern:

```python
op.execute(sa.text("""
    DO $$ BEGIN
        CREATE TYPE invoice_status AS ENUM (
            'draft', 'issued', 'partially_paid', 'paid', 'overdue', 'voided'
        );
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;
"""))
```

Used `create_type=False` on all `postgresql.ENUM(...)` column definitions so SQLAlchemy never attempts to create the type again.

**File changed:** `alembic/versions/0001_initial_schema.py`

---

## Issue 2 — `password authentication failed for user "takaada"`

### Terminal Output
```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "takaada"
```

### How It Was Traced
The default `.env.example` used `takaada:takaada` as the DB user/password. The local Postgres installation only had the `postgres` superuser — no `takaada` user existed.

### Root Cause
`.env.example` defaulted to a dedicated app user (`takaada`) which is correct for Docker (where we create it), but wrong for a local Postgres installation that only has the default `postgres` superuser.

### Resolution
Updated `.env.example` to use `postgres` superuser with a clear placeholder:

```
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_POSTGRES_PASSWORD@127.0.0.1:5432/takaada
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:YOUR_POSTGRES_PASSWORD@127.0.0.1:5432/takaada
```

Set the real password via PowerShell (avoids manual Notepad editing errors):
```powershell
(Get-Content .env) -replace 'YOUR_POSTGRES_PASSWORD', 'your_actual_password' | Set-Content .env
```

**File changed:** `.env.example`

---

## Issue 3 — `getaddrinfo failed` / connection refused

### Terminal Output
```
socket.gaierror: [Errno 11003] getaddrinfo failed
asyncpg.connect_utils.py: raise last_error or exceptions.TargetServerAttributeNotMatched
```

### How It Was Traced
`psql -h 127.0.0.1 -U postgres` worked fine. Alembic and the app could not connect. The `.env` had `YOUR_POSTGRES_PASSWORD` still as a literal string — the placeholder was never replaced, so SQLAlchemy tried to resolve `YOUR_POSTGRES_PASSWORD` as a hostname.

### Root Cause
Two sub-causes:
1. `.env` was reset by running `copy .env.example .env` again, overwriting the previously edited file
2. The placeholder text `YOUR_POSTGRES_PASSWORD` was being parsed as part of the connection URL, causing hostname resolution failure

### Resolution
```powershell
# Always set password immediately after copying .env
copy .env.example .env
(Get-Content .env) -replace 'YOUR_POSTGRES_PASSWORD', 'your_actual_password' | Set-Content .env

# Verify before running anything else
Get-Content .env | Select-String "DATABASE_URL"
```

> **Note:** Use `127.0.0.1` not `localhost` in the URL. On Windows, `localhost` can resolve to IPv6 (`::1`) which PostgreSQL may not be listening on.

---

## Issue 4 — Postgres running on port 5433, not default 5432

### Terminal Output
```
netstat -ano | findstr :5433
TCP    0.0.0.0:5433    0.0.0.0:0    LISTENING    21344
```
```
psql -h 127.0.0.1 -p 5433 -U postgres -c "CREATE DATABASE takaada;"  ← worked
psql -h 127.0.0.1 -U postgres ...                                      ← failed (wrong port)
```

### How It Was Traced
`psql` without `-p` flag defaulted to port 5432 and failed. Running `netstat -ano | findstr :543` revealed Postgres was listening on 5433. The PostgreSQL installer screenshot confirmed port 5433 was set during installation.

### Root Cause
PostgreSQL was installed with a non-default port (5433), likely because port 5432 was already occupied by another service or a previous Postgres installation.

### Resolution
Update both `.env` and `alembic.ini` to use port 5433:

```powershell
(Get-Content .env) -replace ':5432/', ':5433/' | Set-Content .env
(Get-Content alembic.ini) -replace ':5432/', ':5433/' | Set-Content alembic.ini
```

Always use `-p 5433` in all `psql` commands:
```powershell
psql -h 127.0.0.1 -p 5433 -U postgres -d takaada -c "\dt"
```

> **How to find your Postgres port:**
> ```powershell
> netstat -ano | findstr :543
> ```
> Or check in pgAdmin → right-click server → Properties → Connection tab.

---

## Issue 5 — `syntax error at or near "NOT"` on `CREATE TYPE IF NOT EXISTS`

### Terminal Output
```
asyncpg.exceptions.PostgresSyntaxError: syntax error at or near "NOT"
[SQL: CREATE TYPE IF NOT EXISTS invoice_status AS ENUM (...)]
```

### How It Was Traced
The migration was executing the raw SQL `CREATE TYPE IF NOT EXISTS ...` via `op.execute()`. The error pointed exactly to the `NOT` keyword.

### Root Cause
`asyncpg` sends DDL statements as **prepared statements**. PostgreSQL rejects `CREATE TYPE IF NOT EXISTS` when executed through the prepared statement protocol — regardless of Postgres version. This is an asyncpg-specific limitation, not a Postgres version issue.

### Resolution
Replaced `CREATE TYPE IF NOT EXISTS` with the `DO $$ EXCEPTION WHEN duplicate_object $$` pattern (see Issue 1), which works correctly through all execution paths including asyncpg prepared statements.

**File changed:** `alembic/versions/0001_initial_schema.py`

---

## Issue 6 — `alembic upgrade head` ran silently with no output and no tables created

### Terminal Output
```powershell
> alembic upgrade head
>                        ← no output, no error, no tables created

> psql ... -c "\dt"
Did not find any tables.

> psql ... -c "SELECT * FROM alembic_version;"
ERROR: relation "alembic_version" does not exist
```

### How It Was Traced
`alembic upgrade head --sql` showed the migration SQL but then crashed with `AttributeError: 'NoneType' object has no attribute 'scalar'`. `alembic current` returned nothing. The `alembic_version` table didn't exist, meaning alembic never actually connected to the database.

### Root Cause
The original `alembic/env.py` used `asyncpg` (async driver) with `asyncio.run()`. On Windows with Anaconda Python, `asyncio.run()` inside alembic's subprocess context silently exits without running the migration — no error, no output. Alembic is designed to work with **synchronous** drivers only; the async wrapper was incompatible with the Windows event loop behaviour.

Additionally, `alembic.ini` had a hardcoded URL pointing to the wrong port/credentials, so even the fallback path failed silently.

### Resolution
Rewrote `alembic/env.py` to use the **synchronous** `psycopg2` driver with `engine_from_config` — the standard Alembic pattern:

```python
def run_migrations_online() -> None:
    url = get_url()
    # Convert asyncpg URL to psycopg2 for Alembic
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

Also updated `alembic.ini` to use the psycopg2 URL directly as a fallback.

> The app still uses `asyncpg` at runtime — only the migration tool switches to the sync driver.

**Files changed:** `alembic/env.py`, `alembic.ini`

---

## Issue 7 — `_enum_exists()` crashes with `AttributeError: 'NoneType'`

### Terminal Output
```
File "alembic/versions/0001_initial_schema.py", line 159, in _enum_exists
    return result.scalar() is not None
           ^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'scalar'
```

### How It Was Traced
Error appeared when running `alembic upgrade head --sql` (offline mode). The traceback pointed directly to `op.get_bind()` returning `None`.

### Root Cause
`op.get_bind()` returns `None` in offline (SQL generation) mode because there is no live database connection. The `_enum_exists()` helper called `op.get_bind().execute(...)` which crashed on `None`.

### Resolution
Removed `_enum_exists()` entirely. Replaced with the `DO $$ EXCEPTION WHEN duplicate_object $$` block which works in both online and offline modes without needing a live connection check.

**File changed:** `alembic/versions/0001_initial_schema.py`

---

## Issue 8 — Migration shows as already run but tables don't exist

### Terminal Output
```powershell
> psql ... -c "SELECT * FROM alembic_version;"
     version_num
---------------------
 0001_initial_schema

> psql ... -c "\dt"
Did not find any tables.
```

### How It Was Traced
`alembic_version` recorded the migration as complete, but `\dt` showed no tables. This meant the migration ran but failed partway — after writing to `alembic_version` but before creating the tables.

### Root Cause
Earlier migration attempts that crashed mid-run had recorded themselves as complete in `alembic_version`. Subsequent `alembic upgrade head` calls saw the migration as already applied and skipped it entirely.

### Resolution
Full schema reset to clear the corrupted state, then re-run:

```powershell
# Wipes everything including alembic_version
psql -h 127.0.0.1 -p 5433 -U postgres -d takaada -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Fresh migration run
alembic upgrade head

# Verify
psql -h 127.0.0.1 -p 5433 -U postgres -d takaada -c "\dt"
```

Expected after fix — 5 tables: `alembic_version`, `customers`, `invoices`, `payments`, `sync_logs`

---

## Issue 9 — `invalid input value for enum sync_status: "PARTIAL"`

### Terminal Output
```
asyncpg.exceptions.InvalidTextRepresentationError: invalid input value for enum sync_status: "PARTIAL"
[SQL: INSERT INTO sync_logs ... VALUES ($1::VARCHAR, $2::sync_status, ...) ]
[parameters: ('full', 'PARTIAL', ...)]
```

### How It Was Traced
The SQL showed `'PARTIAL'` (uppercase) being inserted into the `sync_status` column. The Postgres enum was defined with lowercase values `('success', 'partial', 'failed')`. Postgres enums are case-sensitive.

### Root Cause
`SAEnum(SyncStatus, name="sync_status")` without `values_callable` makes SQLAlchemy serialize enum members by their **Python attribute name** (`PARTIAL`, `SUCCESS`, `FAILED` — uppercase) rather than their **value** (`partial`, `success`, `failed` — lowercase). The Python enum was defined as:

```python
class SyncStatus(str, enum.Enum):
    SUCCESS = "success"   # name=SUCCESS, value=success
    PARTIAL = "partial"   # name=PARTIAL, value=partial
    FAILED  = "failed"    # name=FAILED,  value=failed
```

SQLAlchemy was sending the name, Postgres expected the value.

### Resolution
Added `values_callable` to both `SyncStatus` and `InvoiceStatus` column definitions:

```python
# Before (broken)
SAEnum(SyncStatus, name="sync_status")

# After (fixed)
SAEnum(SyncStatus, name="sync_status", values_callable=lambda x: [e.value for e in x])
```

Applied to both enums in `models.py`:
```python
# SyncLog.status
SAEnum(SyncStatus, name="sync_status", values_callable=lambda x: [e.value for e in x])

# Invoice.status
SAEnum(InvoiceStatus, name="invoice_status", values_callable=lambda x: [e.value for e in x])
```

**File changed:** `app/models/models.py`

---

## Issue 10 — `curl -X POST` fails in PowerShell

### Terminal Output
```powershell
> curl -X POST http://localhost:8000/api/v1/sync/run
Invoke-WebRequest : A parameter cannot be found that matches parameter name 'X'.
```

### How It Was Traced
PowerShell has a built-in alias `curl` → `Invoke-WebRequest`. `Invoke-WebRequest` uses `-Method` not `-X`, so `-X` is an unrecognised parameter.

### Root Cause
PowerShell overrides the real `curl` binary with its own `Invoke-WebRequest` alias. Even though `curl.exe` 8.18 was installed on the system (visible in Command Prompt), PowerShell intercepted the `curl` command before it reached the binary.

### Resolution
Three options:

```powershell
# Option 1: Use PowerShell-native method (recommended)
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/v1/sync/run"

# Option 2: Force real curl binary with .exe suffix
curl.exe -X POST http://localhost:8000/api/v1/sync/run

# Option 3: Use Command Prompt (cmd.exe) instead of PowerShell
# In CMD, curl is not aliased and works normally
curl -X POST http://localhost:8000/api/v1/sync/run
```

---

## Issue 11 — `localhost:5432` in browser shows "This page isn't working"

### Terminal Output / Browser
```
localhost didn't send any data.
ERR_EMPTY_RESPONSE
```

### How It Was Traced
Browser was opened to `localhost:5432` — the Postgres port.

### Root Cause
Port 5432 (or 5433) is a **database protocol** port (PostgreSQL wire protocol), not HTTP. Browsers speak HTTP — they cannot communicate with a database server. This is not an error with the application.

### Resolution
No fix needed. This is expected behaviour.

| Port | Service | Accessible via browser? |
|------|---------|------------------------|
| `5432` / `5433` | PostgreSQL | ❌ No — database protocol |
| `8001` | Mock Accounting API | ✅ Yes — try `/v1/customers` |
| `8000` | Integration Service | ✅ Yes — try `/docs` |

---

## Quick Reference — All Commands for Windows Setup

```powershell
# 1. Create and activate venv
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure .env
copy .env.example .env
(Get-Content .env) -replace 'YOUR_POSTGRES_PASSWORD', 'your_actual_password' | Set-Content .env
(Get-Content .env) -replace ':5432/', ':5433/' | Set-Content .env        # only if your port is 5433
(Get-Content alembic.ini) -replace ':5432/', ':5433/' | Set-Content alembic.ini  # only if port is 5433
Get-Content .env | Select-String "DATABASE_URL"                           # verify

# 4. Create database
psql -h 127.0.0.1 -p 5433 -U postgres -c "CREATE DATABASE takaada;"

# 5. Run migrations
alembic upgrade head

# 6. Verify tables exist
psql -h 127.0.0.1 -p 5433 -U postgres -d takaada -c "\dt"

# 7. Terminal 1 — Mock API
uvicorn app.integrations.mock_server:app --port 8001

# 8. Terminal 2 — Main service
uvicorn app.main:app --reload --port 8000

# 9. Trigger sync
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/v1/sync/run"

# 10. Open API docs
start http://localhost:8000/docs
```

## Recovery — If migrations leave partial state

```powershell
# Full reset — wipes all tables and alembic history
psql -h 127.0.0.1 -p 5433 -U postgres -d takaada -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
alembic upgrade head
psql -h 127.0.0.1 -p 5433 -U postgres -d takaada -c "\dt"
```
