"""Gumroad connector — publish products, fetch sales, wire approvals.

The ONLY component that touches the real Gumroad API.
Tries the official API first, then falls back to a human-uploadable draft bundle.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

from orion.config import get_config
from orion.products import get_product
from orion.secrets import get_vault

log = logging.getLogger("orion.connectors.gumroad")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GumroadAPIError(RuntimeError):
    """Gumroad API error with status code and message (no secrets)."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PublishResult:
    """Result of a publish/create product operation."""

    success: bool
    product_id: Optional[str] = None
    url: Optional[str] = None
    method: str = "api"  # "api" | "draft_bundle"
    error: Optional[str] = None
    draft_bundle_path: Optional[str] = None


@dataclass
class SaleRecord:
    """Normalized Gumroad sale record."""

    id: str
    product_id: str
    price_usd_cents: int
    currency: str
    email: str
    created_at: str
    payout_id: Optional[str] = None


@dataclass
class PayoutRecord:
    """Normalized Gumroad payout record."""

    id: str
    amount_usd_cents: int
    currency: str
    status: str
    arrived_at: str
    paid_out_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class GumroadConnector:
    """Gumroad API connector with draft-bundle fallback.

    All money in USD cents. All HTTP calls use httpx with 30s timeout,
    retries with exponential backoff (max 3). Token from vault is NEVER logged.
    """

    name = "gumroad"
    is_mock = False

    def __init__(self, vault: Optional[Any] = None):
        self._vault = vault or get_vault()
        self._client: Optional[httpx.AsyncClient] = None
        self._api_base = get_config().platform("gumroad") or {}
        self._api_base_url = self._api_base.get("api_base", "https://api.gumroad.com")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": "ORION/1.0"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _get_token(self) -> Optional[str]:
        """Get access token from vault (never logged)."""
        return self._vault.get("gumroad_token")

    def _auth_headers(self) -> dict[str, str]:
        token = self._get_token()
        if not token:
            raise GumroadAPIError("gumroad_token not found in vault", 401)
        return {"Authorization": f"Bearer {token}"}

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[dict[str, str]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> httpx.Response:
        """HTTP request with exponential backoff (max 3 attempts)."""
        client = await self._get_client()
        url = f"{self._api_base_url}{path}"

        merged_headers = self._auth_headers()
        if headers:
            merged_headers.update(headers)

        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=merged_headers,
                    data=data,
                    files=files,
                    params=params,
                )
                return response
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                last_error = e
                wait = (2**attempt) * 0.5  # 0.5, 1.0, 2.0
                log.warning(
                    "gumroad request failed, retrying",
                    extra={
                        "attempt": attempt + 1,
                        "method": method,
                        "path": path,
                        "wait": wait,
                        "error": str(e),
                    },
                )
                await asyncio.sleep(wait)

        raise GumroadAPIError(
            f"request failed after 3 retries: {last_error}", 0
        ) from last_error

    # -----------------------------------------------------------------------
    # Connection test
    # -----------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """GET /v2/user with stored access_token. Returns True/False."""
        try:
            token = self._get_token()
            if not token:
                log.warning("gumroad test_connection: no token in vault")
                return False

            response = await self._request_with_retry("GET", "/v2/user")
            if response.status_code == 200:
                data = response.json()
                user = data.get("user", {})
                log.info(
                    "gumroad connection ok",
                    extra={"user": user.get("name", "unknown")},
                )
                return True
            elif response.status_code in (401, 403):
                log.warning(
                    "gumroad test_connection: auth failed",
                    extra={"status": response.status_code},
                )
                return False
            else:
                log.warning(
                    "gumroad test_connection: unexpected status",
                    extra={"status": response.status_code},
                )
                return False
        except GumroadAPIError:
            return False
        except Exception as e:
            log.exception("gumroad test_connection error", extra={"error": str(e)})
            return False

    # -----------------------------------------------------------------------
    # Create product (API first, then draft bundle fallback)
    # -----------------------------------------------------------------------

    async def create_product(self, product_record: "ProductRecord") -> PublishResult:
        """Create a Gumroad product via API, fallback to draft bundle.

        Args:
            product_record: Product ORM record from orion.models.Product

        Returns:
            PublishResult with success, product_id, url, method, error, draft_bundle_path
        """
        token = self._get_token()
        if not token:
            return PublishResult(
                success=False,
                method="draft_bundle",
                error="gumroad_token not found in vault",
                draft_bundle_path=await self._create_draft_bundle(product_record),
            )

        # Check if API creation is enabled
        create_via_api = self._api_base.get("create_product_via_api", "conditional")
        if create_via_api != "conditional":
            # If explicitly disabled, go straight to draft bundle
            return PublishResult(
                success=False,
                method="draft_bundle",
                error=f"create_product_via_api is '{create_via_api}', using draft bundle",
                draft_bundle_path=await self._create_draft_bundle(product_record),
            )

        # Load product spec from JSON
        import json as json_mod

        spec = json_mod.loads(product_record.spec_json)

        # Prepare product data
        product_data = {
            "name": spec.get("title", "Untitled Product"),
            "description": spec.get("description", ""),
            "price": product_record.price_usd_cents,  # in cents
            "type": "digital",
            "tags": ",".join(spec.get("tags", [])),
            "draft": "true",  # Create as draft first
        }

        # Get product files
        content_path = get_config().data_dir / product_record.content_path
        product_files = list(content_path.glob("*")) if content_path.exists() else []
        product_files = [f for f in product_files if f.is_file()]

        try:
            # POST /v2/products with multipart/form-data
            response = await self._request_with_retry(
                "POST",
                "/v2/products",
                data=product_data,
                files={
                    f"files[]": (f.name, f.open("rb"), "application/octet-stream")
                    for f in product_files
                }
                if product_files
                else None,
            )

            if response.status_code in (200, 201):
                data = response.json()
                product = data.get("product", {})
                gumroad_product_id = product.get("id")
                product_url = product.get("short_url") or product.get("url")

                if not gumroad_product_id:
                    raise GumroadAPIError(
                        "No product ID in response", response.status_code
                    )

                # If auto-publish is desired, enable the product
                # For now, leave as draft per the spec (human enables)
                # PUT /v2/products/{id}/enable would publish it

                return PublishResult(
                    success=True,
                    product_id=str(gumroad_product_id),
                    url=product_url,
                    method="api",
                )

            elif response.status_code == 404:
                # Endpoint not implemented - fallback
                log.info(
                    "gumroad create_product: 404 endpoint, using draft bundle fallback"
                )
                return PublishResult(
                    success=False,
                    method="draft_bundle",
                    error="Gumroad API create endpoint returned 404 (not implemented)",
                    draft_bundle_path=await self._create_draft_bundle(product_record),
                )

            elif response.status_code in (401, 403):
                # Auth issue - fallback
                log.warning(
                    "gumroad create_product: auth error, using draft bundle fallback",
                    extra={"status": response.status_code},
                )
                return PublishResult(
                    success=False,
                    method="draft_bundle",
                    error=f"Gumroad API auth error ({response.status_code})",
                    draft_bundle_path=await self._create_draft_bundle(product_record),
                )

            else:
                # Other error - fallback
                error_msg = (
                    f"Gumroad API error {response.status_code}: {response.text[:200]}"
                )
                log.warning(
                    "gumroad create_product: API error, using draft bundle fallback",
                    extra={"status": response.status_code},
                )
                return PublishResult(
                    success=False,
                    method="draft_bundle",
                    error=error_msg,
                    draft_bundle_path=await self._create_draft_bundle(product_record),
                )

        except GumroadAPIError as e:
            # Network/timeout error - fallback
            log.warning(
                "gumroad create_product: network error, using draft bundle fallback",
                extra={"error": str(e)},
            )
            return PublishResult(
                success=False,
                method="draft_bundle",
                error=f"Network error: {e}",
                draft_bundle_path=await self._create_draft_bundle(product_record),
            )

    async def _create_draft_bundle(self, product_record: "ProductRecord") -> str:
        """Generate a publish-ready draft bundle for manual upload."""
        import json as json_mod

        spec = json_mod.loads(product_record.spec_json)
        product_id = product_record.id

        # Create draft bundle directory
        data_dir = get_config().data_dir
        bundle_dir = data_dir / "workspace" / "products" / product_id / "gumroad_draft"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Copy product files
        content_path = data_dir / product_record.content_path
        if content_path.exists():
            for f in content_path.glob("*"):
                if f.is_file():
                    shutil.copy2(f, bundle_dir / f.name)

        # Write metadata.json
        metadata = {
            "name": spec.get("title", "Untitled Product"),
            "description": spec.get("description", ""),
            "price_cents": product_record.price_usd_cents,
            "currency": "USD",
            "type": "digital",
            "tags": spec.get("tags", []),
            "license": spec.get("license", "MIT"),
            "created_at": datetime.now().isoformat(),
            "product_id": product_id,
            "content_path": str(product_record.content_path),
        }
        (bundle_dir / "metadata.json").write_text(
            json_mod.dumps(metadata, indent=2), encoding="utf-8"
        )

        # Write UPLOAD_INSTRUCTIONS.md
        instructions = f"""# Gumroad Manual Upload Instructions

Product: {metadata["name"]}
Product ID: {product_id}
Generated: {metadata["created_at"]}

## Steps to Publish on Gumroad

1. **Go to Gumroad Dashboard**
   - Open https://gumroad.com/dashboard in your browser
   - Sign in to your Gumroad account

2. **Create New Product**
   - Click "New Product" → "Digital Product"
   - Fill in the fields using `metadata.json`:

3. **Fill Product Details**
   - **Name**: {metadata["name"]}
   - **Description**: Copy from metadata.json (supports markdown)
   - **Price**: ${metadata["price_cents"] / 100:.2f} USD
   - **Category**: Digital Product
   - **Tags**: {", ".join(metadata["tags"]) if metadata["tags"] else "(none)"}
   - **License**: {metadata["license"]}

4. **Upload Files**
   - Upload all files from this directory:
"""
        for f in bundle_dir.iterdir():
            if f.is_file() and f.name not in (
                "metadata.json",
                "UPLOAD_INSTRUCTIONS.md",
            ):
                instructions += f"   - `{f.name}`\n"

        instructions += """
5. **Save as Draft or Publish**
   - Click "Save as Draft" to review first, or "Publish" to go live
   - If saved as draft, you can enable it later from the dashboard

## Notes
- This bundle was generated because the Gumroad API create endpoint was unavailable or authentication failed.
- The product files are copies of the original generated content.
- After publishing, update the ORION product record with the Gumroad product ID and URL.
"""
        (bundle_dir / "UPLOAD_INSTRUCTIONS.md").write_text(
            instructions, encoding="utf-8"
        )

        log.info(
            "gumroad draft bundle created",
            extra={"path": str(bundle_dir), "product_id": product_id},
        )
        return str(bundle_dir)

    # -----------------------------------------------------------------------
    # List sales (with pagination)
    # -----------------------------------------------------------------------

    async def list_sales(
        self,
        after: Optional[str] = None,
        before: Optional[str] = None,
        product_id: Optional[str] = None,
    ) -> list[SaleRecord]:
        """GET /v2/sales with filters; paginate through all pages using page_key."""
        sales: list[SaleRecord] = []
        page_key: Optional[str] = None

        params: dict[str, Any] = {}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        if product_id:
            params["product_id"] = product_id

        while True:
            if page_key:
                params["page_key"] = page_key

            response = await self._request_with_retry("GET", "/v2/sales", params=params)

            if response.status_code != 200:
                raise GumroadAPIError(
                    f"Failed to fetch sales: {response.status_code} {response.text}",
                    response.status_code,
                )

            data = response.json()
            sales_data = data.get("sales", [])

            for sale in sales_data:
                sales.append(
                    SaleRecord(
                        id=str(sale.get("id", "")),
                        product_id=str(sale.get("product_id", "")),
                        price_usd_cents=int(sale.get("price", 0)),
                        currency=sale.get("currency", "USD"),
                        email=sale.get("email", ""),
                        created_at=sale.get("created_at", ""),
                        payout_id=sale.get("payout_id"),
                    )
                )

            page_key = data.get("page_key")
            if not page_key:
                break

        return sales

    # -----------------------------------------------------------------------
    # List payouts
    # -----------------------------------------------------------------------

    async def list_payouts(self) -> list[PayoutRecord]:
        """GET /v2/payouts; returns list of PayoutRecord."""
        response = await self._request_with_retry("GET", "/v2/payouts")

        if response.status_code != 200:
            raise GumroadAPIError(
                f"Failed to fetch payouts: {response.status_code} {response.text}",
                response.status_code,
            )

        data = response.json()
        payouts_data = data.get("payouts", [])

        result: list[PayoutRecord] = []
        for payout in payouts_data:
            result.append(
                PayoutRecord(
                    id=str(payout.get("id", "")),
                    amount_usd_cents=int(payout.get("amount", 0)),
                    currency=payout.get("currency", "USD"),
                    status=payout.get("status", "unknown"),
                    arrived_at=payout.get("arrived_at", ""),
                    paid_out_at=payout.get("paid_out_at"),
                )
            )

        return result


# Import asyncio at module level for the retry logic
import asyncio
