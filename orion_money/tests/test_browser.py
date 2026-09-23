"""Tests for orion.browser — allowlist gate, https-only, captcha refusal,
anti-injection (untrusted + marked, policy state untouched), screenshot,
mock driver, and the honest playwright gate.
"""

from __future__ import annotations

import importlib.util

import pytest

from orion.browser import (
    BrowserController,
    CaptchaBlockedError,
    BrowserPageResult,
)
from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.policy import BudgetPolicy
from orion.security import merge_with_boundary


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


# ---------------------------------------------------------------------------
# allowlist / https gate
# ---------------------------------------------------------------------------


def test_allowlisted_domain_loads_mock_page(db):
    ctrl = BrowserController()
    result: BrowserPageResult = ctrl.page("https://example.com/marketplace")
    assert result.error is None
    assert result.status_code == 200
    assert "Mock Marketplace" in result.text
    # the fixture lists the same offers as MockConnector
    assert "Resume formatting service" in result.text
    assert result.sanitized.trusted is False  # web content is ALWAYS untrusted
    assert result.sanitized.suspicious_markers == []


def test_non_allowlisted_domain_blocked(db):
    ctrl = BrowserController()
    result = ctrl.page("https://evil.test/phish")
    assert result.status_code == 0
    assert result.error is not None
    assert "not in browser.domain_allowlist" in result.error
    assert result.text == ""
    assert result.sanitized.trusted is False


def test_http_blocked_even_when_allowlisted(db):
    ctrl = BrowserController()
    result = ctrl.page("http://example.com/page")
    assert result.status_code == 0
    assert result.error is not None
    assert "https-only" in result.error


def test_allowlist_override(db):
    ctrl = BrowserController(allowlist=["good.test"])
    assert ctrl.page("https://good.test/x").error is None
    assert ctrl.page("https://example.com/x").error is not None


def test_invalid_driver_reported(db):
    ctrl = BrowserController(driver="banana")
    result = ctrl.page("https://example.com/x")
    assert result.error is not None and "unknown browser.driver" in result.error


# ---------------------------------------------------------------------------
# captcha refusal
# ---------------------------------------------------------------------------


def test_captcha_always_refused(db):
    ctrl = BrowserController()
    with pytest.raises(CaptchaBlockedError):
        ctrl.solve_captcha("https://example.com/captcha")
    # a captcha-styled page still loads text (loading is not bypassing);
    # only solving is refused
    result = ctrl.page("https://example.com/captcha")
    assert result.error is None
    assert "CAPTCHA" in result.text


# ---------------------------------------------------------------------------
# anti-injection
# ---------------------------------------------------------------------------


def test_malicious_page_is_untrusted_and_marked(db):
    ctrl = BrowserController()
    result = ctrl.page("https://example.com/injection")
    assert result.error is None
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in result.text
    assert result.sanitized.trusted is False
    assert "ignore all previous instructions" in result.sanitized.suspicious_markers
    # merging only happens through the labeled boundary helper
    merged = merge_with_boundary(result.sanitized)
    assert "[UNTRUSTED WEB CONTENT BELOW" in merged
    assert "[END UNTRUSTED WEB CONTENT]" in merged


def test_malicious_page_leaves_policy_state_untouched(db):
    from orion import ledger

    ctrl = BrowserController()
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        policy = BudgetPolicy()
        before_budget = policy.remaining_daily_budget(session=session)
        before_decision = policy.can_spend(500, "tooling", session=session)

        result = ctrl.page("https://example.com/injection")
        assert "ignore all previous instructions" in result.sanitized.suspicious_markers

        after_budget = policy.remaining_daily_budget(session=session)
        after_decision = policy.can_spend(500, "tooling", session=session)
        assert before_budget == after_budget
        assert before_decision == after_decision
        # near-injective page text lives only inside the untrusted boundary
        assert get_config().risk_guardrails.max_total_loss == 20000
        assert ctrl.session.ended_at is None  # session still active, unmutated


# ---------------------------------------------------------------------------
# screenshots
# ---------------------------------------------------------------------------


def test_mock_screenshot_writes_stub(db):
    ctrl = BrowserController()
    path = ctrl.take_screenshot("https://example.com/marketplace")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "MOCK SCREENSHOT" in content
    assert "example.com" in content


def test_screenshot_blocked_raises_not_faked(db):
    ctrl = BrowserController()
    with pytest.raises(ValueError, match="allowlist"):
        ctrl.take_screenshot("https://evil.test/x")


def test_screenshot_failure_never_faked(db):
    ctrl = BrowserController(driver="playwright")
    if importlib.util.find_spec("playwright") is None:
        # playwright absent -> fetch failure must surface as an error
        with pytest.raises(RuntimeError, match="requires playwright"):
            ctrl.take_screenshot("https://example.com/x")
    else:
        pytest.skip("playwright installed; offline screenshot not exercised")


# ---------------------------------------------------------------------------
# playwright gate (never pretend)
# ---------------------------------------------------------------------------


def test_playwright_requires_installed_package(db):
    ctrl = BrowserController(driver="playwright")
    result = ctrl.page("https://example.com/x")
    if importlib.util.find_spec("playwright") is None:
        assert result.error is not None
        assert "requires playwright installed" in result.error
    else:
        pytest.skip("playwright installed; lazy-load gate not exercised")


# ---------------------------------------------------------------------------
# session tracking
# ---------------------------------------------------------------------------


def test_session_records_actions(db):
    ctrl = BrowserController()
    ctrl.page("https://example.com/marketplace")
    ctrl.page("https://example.com/injection")
    with pytest.raises(CaptchaBlockedError):
        ctrl.solve_captcha("https://example.com/captcha")

    actions = ctrl.end_session()
    kinds = [a["action"] for a in actions]
    assert kinds == ["page", "page", "solve_captcha_refused"]
    assert ctrl.session.session_id
    assert ctrl.session.ended_at is not None
    for a in actions:
        assert a["at"] and a["session_id"] in (ctrl.session.session_id,)
