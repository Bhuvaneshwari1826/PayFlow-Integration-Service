"""
External Accounting API Client

Design decisions:
- Single responsibility: only handles HTTP communication with the external system
- Retry with exponential backoff for transient errors (5xx, timeout)
- Pagination handled transparently via fetch_all_* helpers
- All errors mapped to domain exceptions — callers never deal with httpx internals
- API key passed via header (common pattern); swap for OAuth easily
"""

import asyncio
from typing import Any, AsyncGenerator

import httpx

from app.core.config import settings
from app.core.exceptions import (
    ExternalAPIException,
    ExternalAPIRateLimitException,
    ExternalAPITimeoutException,
)
from app.core.logging import get_logger
from app.schemas.schemas import ExternalCustomer, ExternalInvoice, ExternalPayment

logger = get_logger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


class ExternalAPIClient:
    """
    Async HTTP client for the external accounting system.

    Usage:
        async with ExternalAPIClient() as client:
            customers = await client.fetch_all_customers()
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ExternalAPIClient":
        self._client = httpx.AsyncClient(
            base_url=settings.EXTERNAL_API_BASE_URL,
            headers={
                "X-API-Key": settings.EXTERNAL_API_KEY,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.EXTERNAL_API_TIMEOUT),
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an HTTP request with retry logic.

        Retries on: 429 (with Retry-After), 5xx, timeouts.
        Raises immediately on: 4xx (except 429).
        """
        assert self._client is not None, "Client not initialized. Use as async context manager."

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.debug(f"[Attempt {attempt}] {method} {path} params={params}")
                response = await self._client.request(method, path, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_BACKOFF_BASE * attempt))
                    logger.warning(f"Rate limited by external API. Retrying in {retry_after}s.")
                    await asyncio.sleep(retry_after)
                    if attempt == MAX_RETRIES:
                        raise ExternalAPIRateLimitException(429, "Rate limit exceeded after retries.")
                    continue

                if response.status_code >= 500:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(f"External API 5xx ({response.status_code}). Retrying in {wait}s.")
                    await asyncio.sleep(wait)
                    if attempt == MAX_RETRIES:
                        raise ExternalAPIException(response.status_code, response.text)
                    continue

                if response.status_code >= 400:
                    raise ExternalAPIException(response.status_code, response.text)

                return response.json()

            except httpx.TimeoutException:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"External API timeout on attempt {attempt}. Retrying in {wait}s.")
                await asyncio.sleep(wait)
                if attempt == MAX_RETRIES:
                    raise ExternalAPITimeoutException(
                        f"External API timed out after {MAX_RETRIES} attempts: {path}"
                    )

        # Should never reach here
        raise ExternalAPIException(500, "Exhausted retries without resolution.")

    async def _paginate(
        self,
        path: str,
        extra_params: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Async generator that transparently paginates through all pages.

        Yields individual records, so callers don't need to think about pagination.
        """
        page = 1
        while True:
            params = {"page": page, "page_size": page_size, **(extra_params or {})}
            response = await self._request("GET", path, params=params)

            items = response.get("data", [])
            for item in items:
                yield item

            if not response.get("has_more", False):
                break

            page += 1
            logger.debug(f"Fetching page {page} from {path}")

    # ─── Public fetch methods ──────────────────────────────────────────────────

    async def fetch_all_customers(self) -> list[ExternalCustomer]:
        """Fetch all customers from the external system."""
        logger.info("Fetching all customers from external API.")
        customers = []
        async for raw in self._paginate("/v1/customers"):
            try:
                customers.append(ExternalCustomer(**raw))
            except Exception as e:
                logger.warning(f"Skipping malformed customer record: {e} | raw={raw}")
        logger.info(f"Fetched {len(customers)} customers.")
        return customers

    async def fetch_all_invoices(
        self, updated_since: str | None = None
    ) -> list[ExternalInvoice]:
        """
        Fetch all invoices. Optionally filter by updated_since (ISO timestamp)
        for incremental syncs.
        """
        logger.info(f"Fetching invoices from external API. updated_since={updated_since}")
        params = {"updated_since": updated_since} if updated_since else {}
        invoices = []
        async for raw in self._paginate("/v1/invoices", extra_params=params):
            try:
                invoices.append(ExternalInvoice(**raw))
            except Exception as e:
                logger.warning(f"Skipping malformed invoice record: {e} | raw={raw}")
        logger.info(f"Fetched {len(invoices)} invoices.")
        return invoices

    async def fetch_all_payments(
        self, updated_since: str | None = None
    ) -> list[ExternalPayment]:
        """Fetch all payments. Supports incremental sync via updated_since."""
        logger.info(f"Fetching payments from external API. updated_since={updated_since}")
        params = {"updated_since": updated_since} if updated_since else {}
        payments = []
        async for raw in self._paginate("/v1/payments", extra_params=params):
            try:
                payments.append(ExternalPayment(**raw))
            except Exception as e:
                logger.warning(f"Skipping malformed payment record: {e} | raw={raw}")
        logger.info(f"Fetched {len(payments)} payments.")
        return payments

    async def fetch_customer(self, external_id: str) -> ExternalCustomer:
        """Fetch a single customer by ID."""
        raw = await self._request("GET", f"/v1/customers/{external_id}")
        return ExternalCustomer(**raw)

    async def fetch_invoice(self, external_id: str) -> ExternalInvoice:
        """Fetch a single invoice by ID."""
        raw = await self._request("GET", f"/v1/invoices/{external_id}")
        return ExternalInvoice(**raw)
