"""Tests for orion.secrets — credential vault CRUD, redaction filter,
health, and the never-leak-secrets-in-exceptions guarantee.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path

import pytest

from orion.config import get_config
from orion.secrets import SecretVault, VaultError, get_vault, install_redaction_filter


@pytest.fixture()
def vault(tmp_path):
    return SecretVault(backend="file", data_dir=tmp_path)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_set_get_roundtrip(vault):
    vault.set("api_key", "sk-abc123")
    assert vault.get("api_key") == "sk-abc123"
    assert vault.has("api_key") is True
    assert vault.list_names() == ["api_key"]


def test_get_missing_returns_none(vault):
    assert vault.get("nope") is None
    assert vault.has("nope") is False


def test_delete(vault):
    vault.set("a", "1")
    vault.set("b", "2")
    vault.delete("a")
    assert vault.get("a") is None
    assert vault.list_names() == ["b"]
    vault.delete("missing")  # no-op, must not raise


def test_roundtrip_persists_across_instances(tmp_path):
    SecretVault(backend="file", data_dir=tmp_path).set("token", "abc")
    second = SecretVault(backend="file", data_dir=tmp_path)
    assert second.get("token") == "abc"
    assert second.list_names() == ["token"]


# ---------------------------------------------------------------------------
# File backend file layout
# ---------------------------------------------------------------------------


def test_file_backend_vault_file_has_marker_and_json(vault, tmp_path):
    vault.set("k", "v")
    path = tmp_path / "vault.json"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "# ORION VAULT" in text
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    assert json.loads(body) == {"k": "v"}


@pytest.mark.skipif(
    os.name == "nt",
    reason="os.chmod is a no-op on Windows; the vault relies on filesystem ACLs",
)
def test_file_backend_chmod_0600(vault, tmp_path):
    vault.set("k", "v")
    mode = os.stat(tmp_path / "vault.json").st_mode & 0o777
    assert mode == 0o600


# ---------------------------------------------------------------------------
# redact() and mask()
# ---------------------------------------------------------------------------


def test_redact_scrubs_all_stored_secrets(vault):
    vault.set("openai_key", "sk-abc123DEF456ghi789")
    vault.set("weird", "my weird secret! xyz")
    out = vault.redact(
        "key=sk-abc123DEF456ghi789 and my weird secret! xyz then again "
        "my weird secret! xyz"
    )
    assert "sk-abc123DEF456ghi789" not in out
    assert "my weird secret! xyz" not in out
    assert out.count("[REDACTED:openai_key]") == 1
    assert out.count("[REDACTED:weird]") == 2  # replaceAll semantics


def test_redact_empty_and_none(vault):
    assert vault.redact(None) == ""
    assert vault.redact("") == ""


def test_mask(vault):
    vault.set("k", "supersecret1234")
    assert vault.mask("k") == "•••1234"
    assert vault.mask("missing") == ""


# ---------------------------------------------------------------------------
# Redaction filter on the app logger
# ---------------------------------------------------------------------------


def test_install_redaction_filter_scrubs_log_stream(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    get_config(force_reload=True)
    vault = get_vault()
    vault.set("slack_token", "xoxb-abcdefghijklmnopqrstuvwxyz")
    install_redaction_filter()

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("orion").addHandler(handler)
    try:
        install_redaction_filter()  # idempotent; picks up the new handler
        logging.getLogger("orion.vaulttest").warning(
            "token is xoxb-abcdefghijklmnopqrstuvwxyz do not leak"
        )
    finally:
        logging.getLogger("orion").removeHandler(handler)

    out = buf.getvalue()
    assert "xoxb-abcdefghijklmnopqrstuvwxyz" not in out
    assert "[REDACTED" in out


def test_filter_safe_with_empty_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    get_config(force_reload=True)
    install_redaction_filter()

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("orion").addHandler(handler)
    try:
        install_redaction_filter()
        logging.getLogger("orion.vaulttest").warning("plain log line, no secrets")
    finally:
        logging.getLogger("orion").removeHandler(handler)

    out = buf.getvalue()
    assert "no secrets" in out
    assert "[REDACTED" not in out


# ---------------------------------------------------------------------------
# health() and singleton
# ---------------------------------------------------------------------------


def test_health_ok_for_file_backend(vault):
    health = vault.health()
    assert health["ok"] is True
    assert health["backend"] == "file"
    assert "vault.json" in health["detail"]


def test_get_vault_singleton(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    get_config(force_reload=True)
    vault = get_vault()
    assert vault is get_vault()
    assert vault.health()["ok"] is True


# ---------------------------------------------------------------------------
# Secrets never appear in raised exception messages
# ---------------------------------------------------------------------------


def test_corrupt_vault_error_has_no_secret(vault, tmp_path):
    secret = "sk-ULTRA-SECRET-1234567890"
    vault.set("api_key", secret)
    (tmp_path / "vault.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(VaultError) as exc_info:
        vault.set("other", "x")
    assert secret not in str(exc_info.value)


def test_write_failure_error_has_no_secret(tmp_path):
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("x")
    vault = SecretVault(backend="file", data_dir=blocker)  # data_dir is a file
    secret = "sk-ULTRA-1234567890"
    with pytest.raises(VaultError) as exc_info:
        vault.set("api_key", secret)
    assert secret not in str(exc_info.value)
