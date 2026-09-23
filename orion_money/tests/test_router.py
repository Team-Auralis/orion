"""Tests for the Ollama model router — every test runs in forced-degraded mode.

``ORION_FORCE_NO_OLLAMA=1`` makes all calls fail fast to the deterministic
fallback with zero network traffic, so this suite is green with no Ollama
server installed or running.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from orion import router
from orion.config import get_config
from orion.db import _reset_engine, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Point ORION at a temp data dir and bootstrap a fresh database."""
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch):
    monkeypatch.setenv("ORION_FORCE_NO_OLLAMA", "1")


# ---------------------------------------------------------------------------
# Role presets
# ---------------------------------------------------------------------------


def test_role_presets_resolve_from_config():
    r = router.ModelRouter()
    rc = r.for_role("orchestrator")
    assert rc.model == "qwen2.5:7b"
    assert rc.temperature == 0.3
    assert rc.max_tokens == 2048
    assert rc.base_url == "http://127.0.0.1:11434"
    assert rc.timeout == 120

    # Unknown roles fall back to ModelRole defaults instead of raising.
    rc = r.for_role("no-such-role")
    assert rc.max_tokens == 2048


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_reports_unavailable_when_forced():
    r = router.ModelRouter()
    status = r.health()
    assert status.name == "ollama"
    assert status.available is False
    assert status.degraded_reason is not None
    assert "FORCE_NO_OLLAMA" in status.detail


def test_async_health_reports_unavailable_when_forced():
    r = router.ModelRouter()
    status = asyncio.run(r.ahealth())
    assert status.available is False


# ---------------------------------------------------------------------------
# Generation (fallback path)
# ---------------------------------------------------------------------------


def test_generate_falls_back_cleanly():
    r = router.ModelRouter()
    result = r.generate(
        "orchestrator", "You are ORION's reasoning core.", "Summarise the ledger."
    )
    assert result.status == router.DEGRADED
    assert result.fallback_used is True
    assert result.provider == router.PROVIDER_FALLBACK
    assert result.error
    assert "ORION" in result.text
    assert "DEGRADED" in result.text
    assert "Summarise the ledger." in result.text  # request echoed back


@pytest.mark.asyncio
async def test_async_generate_falls_back_cleanly():
    r = router.ModelRouter()
    result = await r.agenerate("coding", "sys", "help me refactor")
    assert result.status == router.DEGRADED
    assert result.fallback_used is True
    assert "help me refactor" in result.text


# ---------------------------------------------------------------------------
# Structured output (schema-shaped fallback)
# ---------------------------------------------------------------------------


_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "score": {"type": "number"},
        "tags": {"type": "array"},
        "meta": {"type": "object"},
    },
    "required": ["status", "summary"],
}


def test_structured_output_returns_schema_shaped_dict():
    r = router.ModelRouter()
    out = r.structured_output("analyst", "sys", "analyze", _SCHEMA)
    assert out["status"] == "degraded"
    assert out["summary"] == ""
    assert out["score"] == 0
    assert out["tags"] == []
    assert out["meta"] == {}
    json.dumps(out)  # must be JSON-serializable


def test_fallback_dict_is_valid_json_with_required_keys():
    r = router.ModelRouter()
    out = r._schema_fallback(_SCHEMA, reason="test")
    dumped = json.dumps(out)
    decoded = json.loads(dumped)
    assert decoded["status"] == "degraded"
    assert set(_SCHEMA["required"]).issubset(decoded)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_prompts_redacted_before_logging(db, monkeypatch):
    """A secret embedded in a prompt must never reach the log file."""
    # Rebind logging so records land in the temp data dir we control (the
    # process-wide handler was bound to the real data dir at import time).
    import orion.log as olog

    root = logging.getLogger("orion")
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    monkeypatch.setattr(olog, "_logging_configured", False)
    olog.setup_logging()

    secret = "sk-super_secret_token_12345"
    r = router.ModelRouter()
    r.generate("orchestrator", f"The api_key={secret} was rotated.", "Analyze it.")

    log_path = get_config().log_dir / "orion.log"
    assert log_path.exists(), f"expected log file at {log_path}"
    content = log_path.read_text(encoding="utf-8")
    assert secret not in content, "secret leaked into the log file"
    assert "REDACTED" in content, "expected a redaction marker in the log"
