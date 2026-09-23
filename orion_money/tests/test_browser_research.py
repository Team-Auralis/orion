"""Tests for the A3 research browser: driver_health, research_pages, the
real Playwright driver (gated to machines that actually have it), the CLI
research hook, and the /api/browser/research endpoint.

Live-browser tests launch headless chromium and are skipped when playwright
is missing or ORION_SKIP_LIVE_BROWSER=1 — the suite stays green on machines
without a browser.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading

import pytest
from starlette.testclient import TestClient

from orion.browser import (
    BrowserController,
    driver_health,
    research_pages,
)
from orion.config import get_config
from orion.db import _reset_engine, init_db

HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
LIVE_SKIP = not HAS_PLAYWRIGHT or os.environ.get("ORION_SKIP_LIVE_BROWSER") == "1"
LIVE_REASON = (
    "requires playwright + headless chromium (set ORION_SKIP_LIVE_BROWSER=1 to skip)"
)


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    """Fail the model router fast (no network in tests); DEGRADED is valid."""
    monkeypatch.setenv("ORION_FORCE_NO_OLLAMA", "1")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


@pytest.fixture()
def browser_client(db):
    """TestClient whose startup lifespan seeds capital + ensures workspace."""
    from orion.api import app

    with TestClient(app) as c:
        yield c


def _mock_mode(monkeypatch):
    monkeypatch.setenv("ORION_BROWSER_DRIVER", "mock")
    get_config(force_reload=True)


# ---------------------------------------------------------------------------
# driver_health
# ---------------------------------------------------------------------------


def test_driver_health_reports_mock_when_unset(db, monkeypatch):
    monkeypatch.delenv("ORION_BROWSER_DRIVER", raising=False)
    get_config(force_reload=True)
    health = driver_health()
    assert health["driver"] == "mock"
    assert health["available"] is True


def test_driver_health_reports_mock_when_explicit(db, monkeypatch):
    _mock_mode(monkeypatch)
    health = driver_health()
    assert health["driver"] == "mock"
    assert health["available"] is True


def test_driver_health_playwright_reports_availability(db, monkeypatch):
    monkeypatch.setenv("ORION_BROWSER_DRIVER", "playwright")
    get_config(force_reload=True)
    health = driver_health()
    assert health["driver"] == "playwright"
    if HAS_PLAYWRIGHT:
        assert health["available"] is True
    else:
        assert health["available"] is False
        assert "playwright install" in health["detail"]


# ---------------------------------------------------------------------------
# research_pages (mock driver)
# ---------------------------------------------------------------------------


def test_research_pages_fixture_text_and_sanitizes_hostile_page(db, monkeypatch):
    _mock_mode(monkeypatch)
    caps = research_pages(
        [
            "https://mock.localhost/marketplace",
            "https://mock.localhost/injection",
        ]
    )
    ok, hostile = caps
    assert ok.error is None  # success contract: no crash, no error
    assert ok.status == 200
    assert "Mock Marketplace" in ok.text_excerpt
    assert ok.sanitized_markers == []
    assert hostile.error is None
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in hostile.text_excerpt
    assert "ignore all previous instructions" in hostile.sanitized_markers
    # mock driver never takes a real screenshot
    assert ok.screenshot_path is None


def test_research_pages_override_allowlist(db, monkeypatch):
    _mock_mode(monkeypatch)
    caps = research_pages(
        ["https://only-this.test/x"], allowlist_override=["only-this.test"]
    )
    assert caps[0].error is None
    assert "Mock Marketplace" in caps[0].text_excerpt


def test_research_pages_blocked_on_real_driver_path_before_launch(db, monkeypatch):
    # "real driver path" = driver=playwright; the allowlist gate fires BEFORE
    # any import/launch, so this works whether or not playwright is installed.
    monkeypatch.setenv("ORION_BROWSER_DRIVER", "playwright")
    get_config(force_reload=True)
    caps = research_pages(["https://evil.test/page"])
    assert caps[0].error is not None
    assert "not in browser.domain_allowlist" in caps[0].error
    assert caps[0].status == 0
    assert caps[0].text_excerpt == ""


# ---------------------------------------------------------------------------
# playwright gating (never pretend)
# ---------------------------------------------------------------------------


def test_playwright_missing_package_clear_error(db, monkeypatch):
    if HAS_PLAYWRIGHT:
        pytest.skip("playwright installed; missing-package path not exercised")
    monkeypatch.setenv("ORION_BROWSER_DRIVER", "playwright")
    get_config(force_reload=True)
    ctrl = BrowserController()
    result = ctrl.page("https://example.com/x")
    assert result.error is not None
    assert "requires playwright installed" in result.error
    assert result.status_code == 0


@pytest.mark.skipif(LIVE_SKIP, reason=LIVE_REASON)
def test_playwright_connection_refused_fails_cleanly(db, monkeypatch):
    monkeypatch.setenv("ORION_BROWSER_DRIVER", "playwright")
    get_config(force_reload=True)
    # 127.0.0.1:1 is allowlisted here so the gate passes and the REAL driver
    # attempts navigation -> connection refused -> clean error, never a crash
    ctrl = BrowserController(allowlist=["127.0.0.1"])
    result = ctrl.page("http://127.0.0.1:1/x")
    assert result.error is not None
    assert "blocked" not in result.error  # not an allowlist block
    assert result.status_code == 0


@pytest.mark.skipif(LIVE_SKIP, reason=LIVE_REASON)
def test_playwright_allowlist_enforced_before_launch(db, monkeypatch):
    monkeypatch.setenv("ORION_BROWSER_DRIVER", "playwright")
    get_config(force_reload=True)
    # evil.example.com is NOT in this strict override -> blocked pre-launch
    ctrl = BrowserController(allowlist=["wikipedia.org"])
    result = ctrl.page("https://evil.example.com")
    assert result.error is not None
    assert "not in browser.domain_allowlist" in result.error
    assert result.status_code == 0


@pytest.mark.skipif(LIVE_SKIP, reason=LIVE_REASON)
def test_playwright_research_loads_http_fixture_with_screenshot(db, monkeypatch):
    """Serve the mock fixture over real local http; verify the genuine
    driver path end to end: text, sanitization markers, screenshot file."""
    import http.server

    from orion.browser import _fixture_for

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            body = _fixture_for(self.path).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence access logs
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("ORION_BROWSER_DRIVER", "playwright")
        get_config(force_reload=True)
        caps = research_pages(
            [f"http://127.0.0.1:{port}/injection"],
            allowlist_override=["127.0.0.1"],
        )
        cap = caps[0]
        assert cap.error is None
        assert cap.status == 200
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in cap.text_excerpt
        assert "ignore all previous instructions" in cap.sanitized_markers
        assert cap.screenshot_path is not None
        assert "screenshots" in cap.screenshot_path
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# CLI hook
# ---------------------------------------------------------------------------


def test_cli_research_mock_fixture_exits_0_with_banner(db, monkeypatch, capsys):
    _mock_mode(monkeypatch)
    from orion.cli import main

    monkeypatch.setattr(
        sys, "argv", ["orion", "research", "https://mock.localhost/marketplace"]
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "[UNTRUSTED WEB CONTENT — research only]" in out
    assert "final url: https://mock.localhost/marketplace" in out
    assert "Mock Marketplace" in out


def test_cli_research_blocked_exits_1(db, monkeypatch, capsys):
    from orion.cli import main

    monkeypatch.setattr(sys, "argv", ["orion", "research", "https://evil.test/x"])
    assert main() == 1
    out = capsys.readouterr().out
    assert "[UNTRUSTED WEB CONTENT — research only]" in out  # banner always


# ---------------------------------------------------------------------------
# API hook
# ---------------------------------------------------------------------------


def test_api_research_allowlisted_returns_sanitized_excerpt(
    browser_client, monkeypatch
):
    _mock_mode(monkeypatch)
    resp = browser_client.get(
        "/api/browser/research", params={"url": "https://mock.localhost/injection"}
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == 200
    assert payload["url"] == "https://mock.localhost/injection"
    assert payload["error"] is None
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in payload["text_excerpt"]
    assert "ignore all previous instructions" in payload["sanitized_markers"]
    assert payload["sanitized"] is True


def test_api_research_blocked_is_403(browser_client):
    resp = browser_client.get(
        "/api/browser/research", params={"url": "https://evil.test/x"}
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "blocked_by_policy"
    assert "not in browser.domain_allowlist" in body["detail"]
