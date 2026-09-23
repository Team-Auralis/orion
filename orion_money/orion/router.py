"""Model router — the ONLY place ORION talks to an LLM (Ollama, optional).

Scope discipline
----------------
The router is used only for prose/analysis: orchestrator reasoning,
self-evaluation, browser summarisation, coding help. It NEVER decides policy,
safety, or money — those are hard logic in :mod:`orion.policy`,
:mod:`orion.safety` and :mod:`orion.ledger`. Model output is advisory text;
every consequential action is gated by the deterministic layers. Keep it that
way: this file contains no decision logic.

Ollama is OPTIONAL; the whole system keeps working when it is absent. When the
server is unreachable — or ``ORION_FORCE_NO_OLLAMA=1`` is set (CI/tests) —
every call degrades to a deterministic structured fallback that never
fabricates conclusions. All network calls are async over
``httpx.AsyncClient``; sync convenience wrappers (``health``/``generate``/
``structured_output``) spin up a throwaway event loop for callers that are not
async themselves. Prompts are redacted (see :mod:`orion.security`) before any
logging happens.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from orion.config import ModelRole, get_config
from orion.log import get_logger
from orion.security import redact_secrets

log = get_logger("router")

# Statuses returned by the router. DEGRADED means fallback output was used.
OK = "OK"
DEGRADED = "DEGRADED"

PROVIDER_OLLAMA = "ollama"
PROVIDER_FALLBACK = "fallback"

FALLBACK_HEADER = "[ORION: model unavailable — DEGRADED mode."

# Health-check tuning.
HEALTH_TIMEOUT_SECONDS = 3.0
HEALTH_MAX_RETRIES = 3
HEALTH_BACKOFF_BASE_SECONDS = 1.0  # delays: 1s, 2s
HEALTH_CACHE_TTL_SECONDS = 30.0

_DEGRADED_TRUTHY = {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleConfig:
    """Resolved per-role model settings (from config/model_roles.yaml)."""

    model: str
    temperature: float
    max_tokens: int
    base_url: str
    timeout: float


@dataclass(frozen=True)
class ServiceStatus:
    """Health snapshot of the Ollama backend."""

    name: str
    available: bool
    model: str = ""
    latency_ms: Optional[int] = None
    detail: str = ""
    degraded_reason: Optional[str] = None


@dataclass(frozen=True)
class ModelResult:
    """One generation: real model output or the deterministic fallback."""

    text: str
    status: str  # OK | DEGRADED
    fallback_used: bool
    provider: str  # ollama | fallback
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class ModelRouter:
    """Thin provider over a local Ollama server, with deterministic fallback.

    All network paths are async; ``health``/``generate``/``structured_output``
    are sync conveniences that run the coroutine in a fresh event loop. Do not
    call the sync variants from inside a running loop — use the ``a*`` forms.
    """

    def __init__(self, name: str = "ollama") -> None:
        self._name = name
        self._config = get_config()
        self._default_role: ModelRole = self._config.model_roles.role("orchestrator")
        self._health_cache: Optional[ServiceStatus] = None
        self._health_cached_at: float = 0.0

    # -- role resolution ---------------------------------------------------

    def for_role(self, role: str) -> RoleConfig:
        """Resolve a named role to its model settings (unknown -> defaults)."""
        cfg = self._config.model_roles.role(role)
        return RoleConfig(
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            base_url=cfg.base_url,
            timeout=cfg.timeout_seconds,
        )

    # -- degradation gate --------------------------------------------------

    @staticmethod
    def _forced_degraded() -> bool:
        """True when ORION_FORCE_NO_OLLAMA is set (CI/tests): no network."""
        return (
            os.environ.get("ORION_FORCE_NO_OLLAMA", "").strip().lower()
            in _DEGRADED_TRUTHY
        )

    def _degraded_result(
        self, system_prompt: str, user_prompt: str, reason: str
    ) -> ModelResult:
        return ModelResult(
            text=self._fallback_text(system_prompt, user_prompt),
            status=DEGRADED,
            fallback_used=True,
            provider=PROVIDER_FALLBACK,
            error=reason,
        )

    @staticmethod
    def _fallback_text(system_prompt: str, user_prompt: str) -> str:
        """Deterministic fallback: echo the (redacted) request, no conclusions."""
        system = redact_secrets(system_prompt) or "(empty)"
        user = redact_secrets(user_prompt) or "(empty)"
        return (
            f"{FALLBACK_HEADER} Fallback: model unavailable, no analysis "
            "performed.\n"
            f"request system: {system}\n"
            f"request user: {user}\n"
            "canned neutral analysis: no conclusion — model was unavailable; "
            "policy/safety/ledger hard logic governs all consequential actions.]"
        )

    def _schema_fallback(
        self, json_schema: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        """Schema-shaped degraded object: status=degraded, empty/default fields."""
        props = (
            json_schema.get("properties", {}) if isinstance(json_schema, dict) else {}
        )
        defaults = {
            "string": "",
            "integer": 0,
            "number": 0,
            "boolean": False,
            "array": [],
            "object": {},
        }
        out: dict[str, Any] = {}
        for key, prop in props.items():
            if key == "status":
                out[key] = "degraded"
            else:
                out[key] = (
                    defaults.get(prop.get("type")) if isinstance(prop, dict) else None
                )
        for required in (
            json_schema.get("required", []) if isinstance(json_schema, dict) else []
        ):
            out.setdefault(required, None)
        out["status"] = "degraded"
        log.warning(
            "router structured_output DEGRADED",
            extra={"reason": reason},
        )
        return out

    def _log_generate(
        self, role: str, system_prompt: str, user_prompt: str, result: ModelResult
    ) -> None:
        log.debug(
            "router generate",
            extra={
                "role": role,
                "status": result.status,
                "fallback_used": result.fallback_used,
                "provider": result.provider,
                "error": result.error,
                "system": redact_secrets(system_prompt),
                "user": redact_secrets(user_prompt),
            },
        )

    # -- health ------------------------------------------------------------

    async def ahealth(self) -> ServiceStatus:
        """Check Ollama with retries/backoff; negative results cached briefly."""
        if self._forced_degraded():
            return ServiceStatus(
                name=self._name,
                available=False,
                model=self._default_role.model,
                latency_ms=0,
                detail="degraded forced via ORION_FORCE_NO_OLLAMA (no network)",
                degraded_reason="forced_no_ollama",
            )

        now = time.monotonic()
        if (
            self._health_cache
            and now - self._health_cached_at < HEALTH_CACHE_TTL_SECONDS
        ):
            return self._health_cache

        base_url = self._default_role.base_url.rstrip("/")
        last_error = "unreachable"
        retries = 0
        while retries < HEALTH_MAX_RETRIES:
            retries += 1
            try:
                async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
                    start = time.monotonic()
                    resp = await client.get(f"{base_url}/api/tags")
                    latency_ms = int((time.monotonic() - start) * 1000)
                    resp.raise_for_status()
                    models = resp.json().get("models", [])
                status = ServiceStatus(
                    name=self._name,
                    available=True,
                    model=models[0].get("name", self._default_role.model)
                    if models
                    else self._default_role.model,
                    latency_ms=latency_ms,
                    detail=f"ollama reachable ({len(models)} models)",
                )
                self._cache_health(status)
                return status
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = str(exc) or last_error
                if retries < HEALTH_MAX_RETRIES:
                    await asyncio.sleep(
                        HEALTH_BACKOFF_BASE_SECONDS * (2 ** (retries - 1))
                    )

        status = ServiceStatus(
            name=self._name,
            available=False,
            model=self._default_role.model,
            detail=f"ollama unreachable at {base_url} after {HEALTH_MAX_RETRIES} attempts",
            degraded_reason=last_error,
        )
        self._cache_health(status)
        return status

    def _cache_health(self, status: ServiceStatus) -> None:
        self._health_cache = status
        self._health_cached_at = time.monotonic()

    def health(self) -> ServiceStatus:
        return self._run(self.ahealth())

    # -- generation --------------------------------------------------------

    async def agenerate(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ModelResult:
        cfg = self.for_role(role)
        if self._forced_degraded():
            result = self._degraded_result(
                system_prompt, user_prompt, "forced via ORION_FORCE_NO_OLLAMA"
            )
            self._log_generate(role, system_prompt, user_prompt, result)
            return result

        status = await self.ahealth()
        if not status.available:
            result = self._degraded_result(
                system_prompt,
                user_prompt,
                f"ollama unavailable: {status.degraded_reason}",
            )
            self._log_generate(role, system_prompt, user_prompt, result)
            return result

        payload = {
            "model": cfg.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "temperature": temperature if temperature is not None else cfg.temperature,
            "options": {
                "num_predict": max_tokens if max_tokens is not None else cfg.max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout) as client:
                resp = await client.post(
                    f"{cfg.base_url.rstrip('/')}/api/generate", json=payload
                )
                resp.raise_for_status()
                text = resp.json().get("response", "")
            result = ModelResult(
                text=text, status=OK, fallback_used=False, provider=PROVIDER_OLLAMA
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            result = self._degraded_result(
                system_prompt, user_prompt, f"ollama error: {exc}"
            )
        self._log_generate(role, system_prompt, user_prompt, result)
        return result

    def generate(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ModelResult:
        return self._run(
            self.agenerate(role, system_prompt, user_prompt, temperature, max_tokens)
        )

    # -- structured output (JSON only) -------------------------------------

    async def astructured_output(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        cfg = self.for_role(role)

        def fail(reason: str) -> dict[str, Any]:
            return self._schema_fallback(json_schema, reason)

        if self._forced_degraded():
            return fail("forced via ORION_FORCE_NO_OLLAMA")

        status = await self.ahealth()
        if not status.available:
            return fail(f"ollama unavailable: {status.degraded_reason}")

        schema_text = json.dumps(json_schema, indent=2, sort_keys=True)
        system = (
            f"{system_prompt}\n\nRespond with exactly ONE valid JSON object "
            f"matching this schema:\n{schema_text}"
        )
        payload = {
            "model": cfg.model,
            "system": system,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "temperature": cfg.temperature,
            "options": {"num_predict": cfg.max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout) as client:
                resp = await client.post(
                    f"{cfg.base_url.rstrip('/')}/api/generate", json=payload
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(parsed, dict):
                raise ValueError("model returned non-object JSON")
            validated = self._complete_schema(parsed, json_schema)
            if validated is None:
                return fail("model output missing required schema keys")
            log.debug(
                "router structured_output OK",
                extra={
                    "role": role,
                    "system": redact_secrets(system_prompt),
                    "user": redact_secrets(user_prompt),
                },
            )
            return validated
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return fail(f"ollama error: {exc}")

    def structured_output(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        return self._run(
            self.astructured_output(role, system_prompt, user_prompt, json_schema)
        )

    @staticmethod
    def _complete_schema(
        parsed: dict[str, Any], json_schema: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Check required keys are present; return the dict or None when invalid."""
        required = (
            json_schema.get("required", []) if isinstance(json_schema, dict) else []
        )
        if any(key not in parsed for key in required):
            return None
        return parsed

    # -- loop management ---------------------------------------------------

    @staticmethod
    def _run(coro):
        """Run an async coroutine from a non-async caller (fresh event loop)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "ModelRouter sync methods cannot run inside an active event loop; "
            "use the async variants (ahealth/agenerate/astructured_output)"
        )
