"""Offline tests for the Gumroad connector."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

import orion.connectors.gumroad as gumroad
from orion.config import get_config
from orion.connectors.gumroad import (
    GumroadAPIError,
    GumroadConnector,
    PayoutRecord,
    SaleRecord,
)
from orion.db import _reset_engine, get_session, init_db
from orion.models import Product

TEST_TOKEN = "gumroad-test-token-never-log-123456"


class FakeVault:
    def __init__(self, token: str | None):
        self._token = token

    def get(self, name: str) -> str | None:
        return self._token if name == "gumroad_token" else None


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        text: str | None = None,
    ):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(
        self,
        responses: list[FakeResponse] | None = None,
        *,
        error: Exception | None = None,
        close_error: Exception | None = None,
    ):
        self.responses = list(responses or [])
        self.error = error
        self.close_error = close_error
        self.is_closed = False
        self.close_called = False
        self.requests: list[dict[str, Any]] = []

    @staticmethod
    def _close_uploads(files: Any) -> None:
        for value in (files or {}).values():
            if (
                isinstance(value, tuple)
                and len(value) > 1
                and hasattr(value[1], "close")
            ):
                value[1].close()

    async def request(self, **kwargs) -> FakeResponse:
        self.requests.append(kwargs)
        self._close_uploads(kwargs.get("files"))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected Gumroad request")
        return self.responses.pop(0)

    async def aclose(self) -> None:
        self.close_called = True
        if self.close_error is not None:
            raise self.close_error
        self.is_closed = True


def make_connector(
    responses: list[FakeResponse] | None = None,
    *,
    token: str | None = TEST_TOKEN,
    error: Exception | None = None,
    close_error: Exception | None = None,
) -> GumroadConnector:
    connector = GumroadConnector(vault=FakeVault(token))
    connector._client = FakeClient(
        responses,
        error=error,
        close_error=close_error,
    )
    return connector


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Use a temporary data directory and fail if a test creates real HTTP."""
    import orion.config as config_module

    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    config_module._config_singleton = None
    get_config(force_reload=True)

    def blocked_client(*args, **kwargs):
        raise AssertionError("network access is not allowed in Gumroad tests")

    monkeypatch.setattr(httpx, "AsyncClient", blocked_client)
    yield
    config_module._config_singleton = None


@pytest.fixture()
def product_record(isolated_environment):
    """Create a persisted Product row and its content directory."""
    _reset_engine()
    init_db()

    data_dir = get_config().data_dir
    product_dir = data_dir / "workspace" / "products" / "gumroad-test"
    product_dir.mkdir(parents=True, exist_ok=True)
    product_file = product_dir / "asset.txt"
    product_file.write_text("gumroad test asset\n", encoding="utf-8")

    record = Product(
        id="gumroad-test",
        spec_json=json.dumps(
            {
                "title": "Gumroad Test Product",
                "description": "A product used by offline connector tests",
                "tags": ["test", "digital"],
                "license": "MIT",
            }
        ),
        content_path=str(product_dir.relative_to(data_dir)),
        file_hash="test-hash",
        size_bytes=product_file.stat().st_size,
        quality_passed=True,
        price_usd_cents=1200,
        status="READY_TO_PUBLISH",
    )
    with get_session() as session:
        session.add(record)
    yield record
    _reset_engine()


def assert_draft_bundle(result) -> None:
    assert result.success is False
    assert result.method == "draft_bundle"
    assert result.draft_bundle_path
    bundle = Path(result.draft_bundle_path)
    assert bundle.is_dir()
    assert (bundle / "metadata.json").is_file()
    assert (bundle / "UPLOAD_INSTRUCTIONS.md").is_file()
    assert (bundle / "asset.txt").read_text(encoding="utf-8") == "gumroad test asset\n"


@pytest.mark.asyncio
async def test_connection_success():
    connector = make_connector(
        [FakeResponse(200, {"success": True, "user": {"name": "Herobrine"}})]
    )

    assert await connector.test_connection() is True
    assert connector._client.requests[0]["headers"]["Authorization"] == (
        f"Bearer {TEST_TOKEN}"
    )
    await connector.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_connection_auth_failure(status):
    connector = make_connector([FakeResponse(status)])

    assert await connector.test_connection() is False
    assert len(connector._client.requests) == 1
    await connector.close()


@pytest.mark.asyncio
async def test_connection_network_failure(monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(gumroad.asyncio, "sleep", no_sleep)
    connector = make_connector(error=httpx.ConnectError("network down"))

    assert await connector.test_connection() is False
    assert len(connector._client.requests) == 3
    await connector.close()


@pytest.mark.asyncio
async def test_connection_without_token():
    connector = make_connector(token=None)

    assert await connector.test_connection() is False
    assert connector._client.requests == []
    await connector.close()


@pytest.mark.asyncio
async def test_create_product_api_success(product_record):
    connector = make_connector(
        [
            FakeResponse(
                200,
                {
                    "success": True,
                    "product": {
                        "id": "abc",
                        "short_url": "https://gumroad.com/l/abc",
                    },
                },
            )
        ]
    )

    result = await connector.create_product(product_record)

    assert result.success is True
    assert result.product_id == "abc"
    assert result.url == "https://gumroad.com/l/abc"
    assert result.method == "api"
    assert result.draft_bundle_path is None
    assert connector._client.requests[0]["url"].endswith("/v2/products")
    await connector.close()


@pytest.mark.asyncio
async def test_create_product_404_falls_back_to_bundle(product_record):
    connector = make_connector([FakeResponse(404, text="endpoint unavailable")])

    result = await connector.create_product(product_record)

    assert_draft_bundle(result)
    assert "404" in (result.error or "")
    await connector.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_create_product_auth_failure_falls_back(product_record, status):
    connector = make_connector([FakeResponse(status, text="unauthorized")])

    result = await connector.create_product(product_record)

    assert_draft_bundle(result)
    assert "auth error" in (result.error or "").lower()
    await connector.close()


@pytest.mark.asyncio
async def test_create_product_network_failure_falls_back(product_record, monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(gumroad.asyncio, "sleep", no_sleep)
    connector = make_connector(error=httpx.ConnectError("network down"))

    result = await connector.create_product(product_record)

    assert_draft_bundle(result)
    assert "network" in (result.error or "").lower()
    await connector.close()


@pytest.mark.asyncio
async def test_create_product_api_disabled_skips_network(product_record):
    connector = make_connector(error=AssertionError("network request attempted"))
    connector._api_base["create_product_via_api"] = "disabled"

    result = await connector.create_product(product_record)

    assert_draft_bundle(result)
    assert connector._client.requests == []
    await connector.close()


@pytest.mark.asyncio
async def test_list_sales_flattens_pages():
    connector = make_connector(
        [
            FakeResponse(
                200,
                {
                    "sales": [
                        {
                            "id": "sale-1",
                            "product_id": "product-1",
                            "price": 1250,
                            "currency": "USD",
                            "email": "one@example.com",
                            "created_at": "2026-09-01T00:00:00Z",
                            "payout_id": "payout-1",
                        }
                    ],
                    "page_key": "next-page",
                },
            ),
            FakeResponse(
                200,
                {
                    "sales": [
                        {
                            "id": "sale-2",
                            "product_id": "product-2",
                            "price": 700,
                            "currency": "USD",
                            "email": "two@example.com",
                            "created_at": "2026-09-02T00:00:00Z",
                        }
                    ]
                },
            ),
        ]
    )

    sales = await connector.list_sales(
        after="2026-09-01", before="2026-09-03", product_id="product-1"
    )

    assert [sale.id for sale in sales] == ["sale-1", "sale-2"]
    assert isinstance(sales[0], SaleRecord)
    assert sales[0].price_usd_cents == 1250
    assert sales[1].payout_id is None
    assert len(connector._client.requests) == 2
    assert connector._client.requests[1]["params"]["page_key"] == "next-page"
    await connector.close()


@pytest.mark.asyncio
async def test_list_sales_error_has_status_without_token():
    connector = make_connector(
        [FakeResponse(503, text=f"upstream rejected {TEST_TOKEN}")]
    )

    with pytest.raises(GumroadAPIError) as raised:
        await connector.list_sales()

    assert raised.value.status_code == 503
    assert TEST_TOKEN not in str(raised.value)
    await connector.close()


@pytest.mark.asyncio
async def test_list_payouts_maps_fields():
    connector = make_connector(
        [
            FakeResponse(
                200,
                {
                    "payouts": [
                        {
                            "id": "payout-1",
                            "amount": 4200,
                            "currency": "USD",
                            "status": "paid",
                            "arrived_at": "2026-09-01T00:00:00Z",
                            "paid_out_at": "2026-09-02T00:00:00Z",
                        }
                    ]
                },
            )
        ]
    )

    payouts = await connector.list_payouts()

    assert payouts == [
        PayoutRecord(
            id="payout-1",
            amount_usd_cents=4200,
            currency="USD",
            status="paid",
            arrived_at="2026-09-01T00:00:00Z",
            paid_out_at="2026-09-02T00:00:00Z",
        )
    ]
    await connector.close()


@pytest.mark.asyncio
async def test_list_payouts_error_raises():
    connector = make_connector([FakeResponse(500, text="payout service down")])

    with pytest.raises(GumroadAPIError) as raised:
        await connector.list_payouts()

    assert raised.value.status_code == 500
    assert "payout service down" in str(raised.value)
    await connector.close()


@pytest.mark.asyncio
async def test_token_is_not_logged_on_network_error(caplog, monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(gumroad.asyncio, "sleep", no_sleep)
    caplog.set_level(logging.DEBUG, logger="orion.connectors.gumroad")
    connector = make_connector(
        error=httpx.ConnectError(f"request rejected with {TEST_TOKEN}")
    )

    assert await connector.test_connection() is False

    assert TEST_TOKEN not in caplog.text
    assert all(TEST_TOKEN not in str(record.__dict__) for record in caplog.records)
    assert any(
        "[REDACTED]" in str(getattr(record, "error", "")) for record in caplog.records
    )
    await connector.close()


@pytest.mark.asyncio
async def test_close_swallows_event_loop_race():
    client = FakeClient(close_error=RuntimeError("Event loop is closed"))
    connector = GumroadConnector(vault=FakeVault(TEST_TOKEN))
    connector._client = client

    await connector.close()

    assert client.close_called is True
    assert connector._client is None
