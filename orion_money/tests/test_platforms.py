"""Tests for the B1 platform policy (config/platforms.yaml) and the
``orion vault`` credential CLI.

Vault tests invoke the CLI in-process via ``cli_main(argv)`` (the existing
CLI-test pattern) against a temp ORION_DATA_DIR, so tokens never touch the
real vault. Stored names are unique and deleted in teardown so nothing leaks
into the vault used by other tests.
"""

from __future__ import annotations

import io
import logging
import uuid

import pytest

from orion.cli import main as cli_main
from orion.config import get_config
from orion.secrets import get_vault, install_redaction_filter


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point config at a temp data dir so the vault singleton is isolated."""
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    get_config(force_reload=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# platform policy (config/platforms.yaml)
# ---------------------------------------------------------------------------


def test_platforms_gumroad_policy_loaded(data_dir):
    gumroad = get_config().platform("gumroad")
    assert gumroad is not None
    assert gumroad["automation_allowed"] is True
    assert gumroad["research_policy"] == "api_only"
    assert gumroad["api_base"] == "https://api.gumroad.com"
    assert gumroad["api_version"] == "v2"
    assert gumroad["auth"] == "token"
    assert gumroad["create_product_via_api"] == "conditional"
    assert gumroad["publish_requires_payout_account"] is True
    # preserved through the typed model too
    assert get_config().platforms.platforms["gumroad"].automation_allowed is True


def test_unknown_platform_returns_none(data_dir):
    assert get_config().platform("definitely-not-a-platform") is None


def test_browser_allowlist_excludes_gumroad_and_kofi(data_dir):
    allowlist = get_config().policies.browser_domains()
    assert "gumroad.com" not in allowlist
    assert "ko-fi.com" not in allowlist
    assert "wikipedia.org" in allowlist
    assert "github.com" in allowlist
    assert "example.com" in allowlist
    assert "mock.localhost" in allowlist


# ---------------------------------------------------------------------------
# `orion vault` CLI (in-process sys.argv invocation)
# ---------------------------------------------------------------------------


def test_cli_vault_set_list_get_delete_roundtrip(data_dir, capsys):
    name = f"gumroad_token_{uuid.uuid4().hex[:10]}"
    value = f"tok-{uuid.uuid4().hex}"
    vault = get_vault()
    try:
        # set (arg form) stores and never prints the value
        assert cli_main(["vault", "set", name, value]) == 0
        out = capsys.readouterr().out
        assert f"stored {name} in vault" in out
        assert value not in out
        assert vault.get(name) == value

        # list shows the name with a masked value, never the raw secret
        assert cli_main(["vault", "list"]) == 0
        out = capsys.readouterr().out
        assert name in out
        assert "backend=" in out
        assert value not in out

        # get prints the mask only, never the raw secret
        assert cli_main(["vault", "get", name]) == 0
        out = capsys.readouterr().out
        assert "•••" in out
        assert value not in out

        # health reports backend + writable probe
        assert cli_main(["vault", "health"]) == 0
        out = capsys.readouterr().out
        assert "backend=" in out
        assert "ok=True" in out

        # delete removes it
        assert cli_main(["vault", "delete", name]) == 0
        assert f"deleted {name}" in capsys.readouterr().out
        assert vault.get(name) is None
    finally:
        vault.delete(name)


def test_cli_vault_set_reads_value_from_stdin(data_dir, monkeypatch, capsys):
    name = f"pasted_{uuid.uuid4().hex[:10]}"
    value = f"paste-{uuid.uuid4().hex}"
    vault = get_vault()
    monkeypatch.setattr("getpass.getpass", lambda prompt: value)
    try:
        assert cli_main(["vault", "set", name]) == 0
        out = capsys.readouterr().out
        assert f"stored {name} in vault" in out
        assert value not in out
        assert vault.get(name) == value
    finally:
        vault.delete(name)


def test_cli_vault_set_rejects_empty_value(data_dir, capsys):
    assert cli_main(["vault", "set", "bogus_name", "   "]) == 1
    assert "no value provided" in capsys.readouterr().err


def test_cli_vault_get_after_delete_prints_clear_message_exit_0(data_dir, capsys):
    name = f"gone_{uuid.uuid4().hex[:10]}"
    vault = get_vault()
    try:
        vault.set(name, f"tok-{uuid.uuid4().hex}")
        assert cli_main(["vault", "delete", name]) == 0
        capsys.readouterr()
        assert cli_main(["vault", "get", name]) == 0
        out = capsys.readouterr().out
        assert name in out
        assert "not in vault" in out
    finally:
        vault.delete(name)


def test_cli_vault_list_empty(data_dir, capsys):
    assert cli_main(["vault", "list"]) == 0
    assert "vault is empty" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# redaction filter scrubs a real stored secret from a log line
# ---------------------------------------------------------------------------


def test_redaction_filter_scrubs_real_stored_secret(data_dir):
    name = f"logsecret_{uuid.uuid4().hex[:10]}"
    value = f"log-{uuid.uuid4().hex}-secret"
    vault = get_vault()
    try:
        vault.set(name, value)
        install_redaction_filter()

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        logging.getLogger("orion").addHandler(handler)
        try:
            install_redaction_filter()  # idempotent; attaches to the handler
            logging.getLogger("orion.b1").warning("token is %s do not leak", value)
        finally:
            logging.getLogger("orion").removeHandler(handler)

        out = buf.getvalue()
        assert value not in out
        assert "[REDACTED" in out
    finally:
        vault.delete(name)
