"""Typed configuration loader.

Loads ``config/*.yaml`` (default.yaml, policies.yaml, model_roles.yaml),
merges environment overrides, and exposes a lazily-built singleton via
:func:`get_config`. Missing files fall back to sensible defaults so the
system boots without any config present.

All money values are INTEGER PAISE.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, field_validator

# Project root = parent of the config/ directory and the orion/ package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

# Environment variables that override YAML values.
_ENV_OVERRIDES = {
    "ORION_DATA_DIR": ("paths", "data_dir"),
    "ORION_AUTONOMY_MODE": ("autonomy", "default_mode"),
    "ORION_BROWSER_DRIVER": ("policies", "browser", "driver"),
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class OrionInfo(BaseModel):
    name: str = "orion"
    currency: str = "INR"
    starting_capital: int = 20000  # paise
    target: int = 1000000  # paise


class RiskGuardrails(BaseModel):
    max_single_spend: int = 2000  # paise
    max_daily_spend: int = 5000  # paise
    max_total_loss: int = 20000  # paise
    borrowing_allowed: bool = False
    leverage_allowed: bool = False
    gambling_allowed: bool = False


class Autonomy(BaseModel):
    default_mode: str = "dry_run"  # dry_run | manual | assisted | autonomous


class Paths(BaseModel):
    data_dir: str = "data"
    log_dir: str = "logs"
    db_file: str = "orion.db"


class Scheduler(BaseModel):
    tick_seconds: int = 60
    opportunity_scan_seconds: int = 300
    revenue_reconcile_seconds: int = 600
    memory_sweep_seconds: int = 3600


class Jobs(BaseModel):
    """Persistent job queue settings (config/default.yaml ``jobs:``)."""

    max_attempts: int = 3  # attempt cap; requeue_failed() stops at this
    poll_seconds: int = 5  # worker idle poll interval


class ModelRole(BaseModel):
    model: str = "qwen2.5:7b"
    temperature: float = 0.2
    max_tokens: int = 2048
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 120


class BrowserPolicy(BaseModel):
    """Browser controller settings (policies.yaml ``browser:``)."""

    driver: str = "mock"  # mock | playwright
    # https-only domain allowlist; empty falls back to the legacy
    # top-level ``domain_allowlist`` (empty there too = fully open).
    domain_allowlist: list[str] = []


class Policies(BaseModel):
    levels: dict[str, str] = {
        "L0": "AUTO",
        "L1": "AUTO",
        "L2": "APPROVAL",
        "L3": "APPROVAL",
        "L4": "BLOCKED",
    }
    actions: dict[str, str] = {}
    domain_allowlist: list[str] = []  # legacy top-level key
    approval_ttl_hours: int = 24
    browser: BrowserPolicy = BrowserPolicy()

    def browser_domains(self) -> list[str]:
        """Effective browser allowlist: browser.domain_allowlist, else legacy."""
        return self.browser.domain_allowlist or self.domain_allowlist


class ModelRoles(BaseModel):
    roles: dict[str, ModelRole] = {}

    def role(self, name: str) -> ModelRole:
        return self.roles.get(name, ModelRole())


class Platform(BaseModel):
    """One real-world platform's automation policy (config/platforms.yaml).

    Records HOW automation may touch the platform (official API vs browser),
    which API/auth to use, and what the human must do by hand. Never a
    scraping license — ``research_policy: api_only`` platforms are read
    via their official API only.
    """

    automation_allowed: bool = False
    api_base: str = ""
    api_version: str = ""
    auth: str = ""
    uses_oauth_scopes: list[str] = []
    research_policy: str = ""  # browser | api_only | none
    create_product_via_api: str = ""  # yes | no | conditional
    publish_requires_payout_account: bool = False
    price_currency: str = ""
    prohibited_categories_note: str = ""
    verdict_source: str = ""
    verdict_date: str = ""

    @field_validator("verdict_date", mode="before")
    @classmethod
    def _stringify_verdict_date(cls, value):
        # YAML parses an unquoted 2026-09-23 as a datetime.date; keep the
        # field a plain ISO string so dates never leak as datetime objects.
        return value.isoformat() if not isinstance(value, str) else value


class Platforms(BaseModel):
    """All platform policies, keyed by platform name."""

    platforms: dict[str, Platform] = {}


class Scoring(BaseModel):
    """Opportunity scoring weights (config/default.yaml ``scoring:``).
    Pure numeric — never an LLM. Defaults sum to 100."""

    expected_value: float = 30
    demand_confidence: float = 15
    competition_risk: float = 10
    execution_cost: float = 10
    safety_compat: float = 15
    time_to_revenue: float = 10
    automation_feasibility: float = 10

    def as_weights(self) -> dict[str, float]:
        return {
            "expected_value": self.expected_value,
            "demand_confidence": self.demand_confidence,
            "competition_risk": self.competition_risk,
            "execution_cost": self.execution_cost,
            "safety_compat": self.safety_compat,
            "time_to_revenue": self.time_to_revenue,
            "automation_feasibility": self.automation_feasibility,
        }


class ConnectorEntry(BaseModel):
    enabled: bool = False


class Connectors(BaseModel):
    """Per-connector enable flags (config/default.yaml ``connectors:``)."""

    mock: ConnectorEntry = ConnectorEntry(enabled=True)
    real_marketplace: ConnectorEntry = ConnectorEntry(enabled=False)


class Api(BaseModel):
    """HTTP API settings (orion/api.py, served by orion/main.py).

    ``port`` defaults to 8765 to avoid the commonly-occupied 8000;
    ``cors_origins`` lists the browser origins allowed to call the API.
    """

    host: str = "127.0.0.1"
    port: int = 8765
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


class Security(BaseModel):
    """Credential vault settings (config/default.yaml ``security:``)."""

    vault_backend: str = "auto"  # auto | keyring | file


class Config(BaseModel):
    orion: OrionInfo = OrionInfo()
    risk_guardrails: RiskGuardrails = RiskGuardrails()
    autonomy: Autonomy = Autonomy()
    paths: Paths = Paths()
    scheduler: Scheduler = Scheduler()
    jobs: Jobs = Jobs()
    policies: Policies = Policies()
    model_roles: ModelRoles = ModelRoles()
    platforms: Platforms = Platforms()
    scoring: Scoring = Scoring()
    connectors: Connectors = Connectors()
    api: Api = Api()
    security: Security = Security()
    product_pricing: dict[str, int] = {
        "low": 500,
        "medium": 1500,
        "high": 3000,
        "premium": 5000,
    }

    @property
    def data_dir(self) -> Path:
        """Absolute data directory (resolved against project root if relative)."""
        p = Path(self.paths.data_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def log_dir(self) -> Path:
        d = Path(self.paths.log_dir)
        return d if d.is_absolute() else self.data_dir / d

    @property
    def db_path(self) -> Path:
        d = Path(self.paths.db_file)
        return d if d.is_absolute() else self.data_dir / d

    def platform(self, name: str) -> Optional[dict[str, Any]]:
        """Platform policy dict for ``name``, or ``None`` when unknown."""
        found = self.platforms.platforms.get(name)
        return found.model_dump() if found else None


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _load_yaml(name: str) -> dict[str, Any]:
    """Load a YAML file, returning {} on any failure (missing/parse error)."""
    path = CONFIG_DIR / name
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _apply_env_overrides(data: dict[str, Any]) -> None:
    """Mutate ``data`` in place with any set environment overrides.

    Each override maps an env var to a nested key path, e.g.
    ``("policies", "browser", "driver")``; empty/unset vars are ignored so
    YAML remains the default.
    """
    for env_var, path in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var, "").strip()
        if not value:
            continue
        node: dict[str, Any] = data
        for part in path[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[path[-1]] = value


def _load_config() -> Config:
    defaults: dict[str, Any] = _load_yaml("default.yaml")
    policies = _load_yaml("policies.yaml")
    model_roles = _load_yaml("model_roles.yaml")
    platforms = _load_yaml("platforms.yaml")

    merged = dict(defaults)
    merged["policies"] = policies
    merged["model_roles"] = model_roles
    merged["platforms"] = {"platforms": platforms.get("platforms", {})}
    # Env overrides must run on the FULL merge (policies.yaml is merged above;
    # ORION_BROWSER_DRIVER targets policies.browser.driver, not defaults).
    _apply_env_overrides(merged)
    return Config.model_validate(merged)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_config_singleton: Optional[Config] = None


def get_config(*, force_reload: bool = False) -> Config:
    """Return the process-wide :class:`Config` singleton.

    ``force_reload=True`` rebuilds it from disk/env (used by tests and any
    hot-reload path); the default path is memoized after the first call.
    """
    global _config_singleton
    if _config_singleton is None or force_reload:
        _config_singleton = _load_config()
    return _config_singleton
