"""Credential vault — OS keyring with a plaintext JSON fallback.

Holds the real platform API keys once the system goes live. Backend
selection (``security.vault_backend`` in config): ``auto`` tries the OS
keyring first and falls back to a JSON file at ``<data_dir>/vault.json``;
``keyring`` requires the optional ``keyring`` package and degrades to the
file vault with a WARNING if it is missing; ``file`` forces the plaintext
file vault (single-user machines only).

This module deliberately imports ONLY the stdlib and :mod:`orion.config` —
never :mod:`orion.log` — so the redaction filter can be wired into logging
via :func:`install_redaction_filter` without a circular import. All vault
logging goes through the stdlib ``orion.secrets`` logger, and log records
carry names/backends only, never secret values.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from orion.config import get_config

log = logging.getLogger("orion.secrets")

_SERVICE = "orion-vault"
_MARKER = "# ORION VAULT — plaintext fallback. Prefer OS keyring."


class VaultError(Exception):
    """Raised when a vault operation fails.

    Message text never contains secret values — only the affected name, so
    a logged or surfaced exception cannot leak a credential.
    """


def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401

        return True
    except ImportError:
        return False


class SecretVault:
    """Credential store backed by the OS keyring or a JSON file.

    ``backend`` is one of ``""``/``None`` (config ``security.vault_backend``,
    default ``auto``), ``"auto"``, ``"keyring"`` or ``"file"``;
    ``data_dir`` overrides the config data dir (used by tests).
    """

    def __init__(
        self, backend: Optional[str] = None, data_dir: Optional[Path] = None
    ) -> None:
        self.data_dir = (
            Path(data_dir) if data_dir is not None else get_config().data_dir
        )
        self.path = self.data_dir / "vault.json"
        self.backend = self._resolve(backend or self._config_backend())
        self._lock = threading.Lock()
        self._values: dict[str, str] = {}
        # NOTE: __init__ must never log — get_vault() constructs under its
        # lock and a log record re-enters get_vault() (deadlock/recursion).
        # Degradation warnings are emitted by get_vault() after the lock is
        # released (see _warn_degraded).

    # ------------------------------------------------------------------ setup

    def _config_backend(self) -> str:
        cfg = get_config()
        return (
            getattr(getattr(cfg, "security", None), "vault_backend", "auto") or "auto"
        )

    def _resolve(self, chosen: str) -> str:
        self._degraded_reason: Optional[str] = None
        if chosen == "file":
            return "file"
        if chosen == "keyring":
            if _keyring_available():
                return "keyring"
            self._degraded_reason = (
                "keyring unavailable; falling back to the file vault"
            )
            return "file"
        # auto: prefer the OS keyring when installed, else the file vault.
        return "keyring" if _keyring_available() else "file"

    # ------------------------------------------------------ file I/O helpers

    def _load_file(self) -> None:
        """Load persisted entries into ``self._values`` (missing file = empty)."""
        if not self.path.exists():
            self._values = {}
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as err:
            raise VaultError(f"cannot read vault file: {err}") from err
        body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        try:
            data = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError as err:
            raise VaultError("vault file is corrupt (invalid JSON)") from err
        if not isinstance(data, dict):
            raise VaultError("vault file is corrupt (not a JSON object)")
        self._values = {str(key): str(value) for key, value in data.items()}

    def _write_file(self) -> None:
        """Persist ``self._values`` behind the marker line, tightened to 0o600."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            _MARKER + "\n" + json.dumps(self._values, indent=2, ensure_ascii=False)
        )
        self.path.write_text(payload, encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # Windows: chmod is a no-op; the plaintext WARNING covers it.
            pass

    # ------------------------------------------------------ keyring helpers

    def _set_keyring(self, name: str, value: str) -> None:
        import keyring

        keyring.set_password(_SERVICE, name, value)

    def _get_keyring(self, name: str) -> Optional[str]:
        import keyring

        return keyring.get_password(_SERVICE, name)

    def _delete_keyring(self, name: str) -> None:
        import keyring

        try:
            keyring.delete_password(_SERVICE, name)
        except Exception:
            pass  # deleting a missing entry is a no-op

    # ------------------------------------------------------------ public API

    def set(self, name: str, value: str) -> None:
        """Store ``value`` under ``name`` (never logged)."""
        name, value = str(name), str(value)
        with self._lock:
            try:
                if self.backend == "keyring":
                    self._set_keyring(name, value)
                else:
                    self._load_file()
                    self._values[name] = value
                    self._write_file()
            except VaultError:
                raise
            except Exception as err:
                raise VaultError(f"vault set failed for {name!r}") from err
            self._values[name] = value  # in-process mirror for redact/list
        log.info("vault set", extra={"key": name, "backend": self.backend})

    def get(self, name: str) -> Optional[str]:
        """Return the stored value, or ``None`` when missing."""
        name = str(name)
        with self._lock:
            if self.backend == "keyring":
                try:
                    value = self._get_keyring(name)
                except Exception as err:
                    raise VaultError(f"keyring get failed for {name!r}") from err
                if value is not None:
                    self._values[name] = value
                return value
            self._load_file()
            return self._values.get(name)

    def delete(self, name: str) -> None:
        """Remove ``name``; missing entries are a no-op."""
        name = str(name)
        with self._lock:
            if self.backend == "keyring":
                self._delete_keyring(name)
            else:
                self._load_file()
                if name in self._values:
                    del self._values[name]
                    self._write_file()
            self._values.pop(name, None)
        log.info("vault delete", extra={"key": name, "backend": self.backend})

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def list_names(self) -> list[str]:
        """Sorted names of stored entries.

        For the keyring backend this reflects only names touched within this
        process (the OS keyring has no enumerate API).
        """
        with self._lock:
            if self.backend == "keyring":
                return sorted(self._values)
            self._load_file()
            return sorted(self._values)

    def mask(self, name: str) -> str:
        """UI display form: bullet dots plus the last 4 characters."""
        value = self.get(name)
        return ("•••" + value[-4:]) if value else ""

    def redact(self, text: Optional[str]) -> str:
        """Scrub every stored secret value from ``text`` (all occurrences).

        Replacement marker is ``[REDACTED:<name>]``. This is the belt-and-
        braces guarantee on top of ``orion.security.redact_secrets``: even
        unusual secret strings that look like nothing in particular get
        removed. ``None``/empty input returns ``""``.
        """
        if not text:
            return ""
        stored = sorted(
            self._stored_values().items(), key=lambda kv: len(kv[1]), reverse=True
        )
        out = text
        for name, value in stored:
            if value:
                out = out.replace(value, f"[REDACTED:{name}]")
        return out

    def health(self) -> dict:
        """Backend liveness: ``{"backend", "ok", "detail"}``."""
        if self.backend == "keyring":
            try:
                import keyring

                keyring.set_password(_SERVICE, "__health__", "1")
                ok = keyring.get_password(_SERVICE, "__health__") == "1"
                try:
                    keyring.delete_password(_SERVICE, "__health__")
                except Exception:
                    pass
                return {"backend": "keyring", "ok": ok, "detail": "keyring reachable"}
            except Exception as err:
                return {"backend": "keyring", "ok": False, "detail": str(err)}
        try:
            with self._lock:
                self._load_file()
                self._write_file()
            return {"backend": "file", "ok": True, "detail": str(self.path)}
        except Exception as err:
            return {"backend": "file", "ok": False, "detail": str(err)}

    # -------------------------------------------------------------- internal

    def _stored_values(self) -> dict[str, str]:
        with self._lock:
            if self.backend == "keyring":
                return dict(self._values)
            self._load_file()
            return dict(self._values)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: Optional[SecretVault] = None
_singleton_key: tuple = ()
_vault_lock = threading.Lock()


def get_vault(backend: Optional[str] = None) -> SecretVault:
    """Return the process-wide :class:`SecretVault`.

    The cached instance is rebuilt when the config data dir or backend
    changes, so tests that point ``ORION_DATA_DIR`` at a temp dir get their
    own isolated vault. Degradation warnings (plaintext fallback on Windows,
    missing keyring) are emitted here, after the construction lock is
    released, so they never re-enter this function.
    """
    global _singleton, _singleton_key
    key = (backend, str(get_config().data_dir))
    created = False
    if _singleton is None or _singleton_key != key:
        with _vault_lock:
            if _singleton is None or _singleton_key != key:
                _singleton = SecretVault(backend=backend)
                _singleton_key = key
                created = True
    if created and _singleton is not None:
        _warn_degraded(_singleton)
    return _singleton


def _warn_degraded(vault: SecretVault) -> None:
    """Log backend-degradation warnings (safe: vault is now cached)."""
    if vault._degraded_reason:
        log.warning(vault._degraded_reason, extra={"backend": "file"})
    if vault.backend == "file" and os.name == "nt":
        log.warning(
            "file vault is plaintext; only safe on a single-user machine "
            "with restricted filesystem ACLs — prefer `pip install -e .[secrets]`"
        )


# ---------------------------------------------------------------------------
# Log redaction filter
# ---------------------------------------------------------------------------


class SecretRedactionFilter(logging.Filter):
    """Strip every stored secret value out of a record before it is emitted.

    Reads the live vault on each call so the filter stays correct when the
    config data dir changes (tests) or new secrets are added. Message, all
    string extra fields and the formatted traceback are scrubbed; records
    with no stored secret pass through untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        vault = get_vault()
        for key, value in list(record.__dict__.items()):
            if isinstance(value, str) and value:
                scrubbed = vault.redact(value)
                if scrubbed != value:
                    setattr(record, key, scrubbed)
        message = vault.redact(record.getMessage())
        if message != record.msg or record.args:
            record.msg = message
            record.args = ()
        if record.exc_info and not record.exc_text:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = vault.redact(formatted)
        return True


def install_redaction_filter() -> None:
    """Attach :class:`SecretRedactionFilter` to the ``orion`` logger tree.

    Idempotent (filters are only added once per target) and safe with an
    empty vault — records then pass through unchanged. Attaches to the
    ``orion`` logger, the root logger and every handler they own, so records
    emitted by any ``orion.*`` child logger are scrubbed on all streams.
    """
    for logger in (logging.getLogger("orion"), logging.getLogger()):
        if not any(isinstance(f, SecretRedactionFilter) for f in logger.filters):
            logger.addFilter(SecretRedactionFilter())
        for handler in logger.handlers:
            if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
                handler.addFilter(SecretRedactionFilter())
