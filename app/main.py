"""
Takaada Integration Service — Main Application Entry Point

Lifespan: handles scheduler start/stop cleanly.
Global exception handlers: converts domain exceptions to HTTP responses.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.endpoints.routes import router
from app.core.config import settings
from app.core.exceptions import (
    ExternalAPIException,
    ResourceNotFoundException,
    SyncException,
)
from app.core.logging import setup_logging
from app.services.scheduler import start_scheduler, stop_scheduler

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background scheduler on startup, stop on shutdown."""
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Takaada Integration Service

Integrates with an external accounting system to provide financial receivables insights.

### Key Features
- **Automated sync** from external accounting API (customers, invoices, payments)
- **Idempotent upserts** — safe to run multiple times
- **Receivables insights** — overdue tracking, credit utilization, collection rates
- **Background scheduler** — syncs every 15 minutes automatically

### Design Notes
- All monetary values are stored as `Numeric(15,2)` — never floats
- Invoice status is recomputed locally to catch cases where external system hasn't marked past-due invoices as overdue
- Sync logs provide full observability into the integration pipeline
""",
    lifespan=lifespan,
)

# ─── Global Exception Handlers ────────────────────────────────────────────────

@app.exception_handler(ResourceNotFoundException)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundException):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ExternalAPIException)
async def external_api_exception_handler(request: Request, exc: ExternalAPIException):
    return JSONResponse(
        status_code=502,
        content={"detail": f"External API error: {exc.detail}"},
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Takaada Integration Service. Visit /docs for API documentation."}
