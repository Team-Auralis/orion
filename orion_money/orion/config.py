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
from pydantic import BaseModel

# Project root = parent of the config/ directory and the orion/ package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

# Environment variables that override YAML values.
_ENV_OVERRIDES = {
    "ORION_DATA_DIR": ("paths", "data_dir"),
    "ORION_AUTONOMY_MODE": ("autonomy", "default_mode"),
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


class Config(BaseModel):
    orion: OrionInfo = OrionInfo()
    risk_guardrails: RiskGuardrails = RiskGuardrails()
    autonomy: Autonomy = Autonomy()
    paths: Paths = Paths()
    scheduler: Scheduler = Scheduler()
    jobs: Jobs = Jobs()
    policies: Policies = Policies()
    model_roles: ModelRoles = ModelRoles()
    scoring: Scoring = Scoring()
    connectors: Connectors = Connectors()

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
    """Mutate ``data`` in place with any set environment overrides."""
    for env_var, (section, key) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var, "").strip()
        if value:
            data.setdefault(section, {})[key] = value


def _load_config() -> Config:
    defaults: dict[str, Any] = _load_yaml("default.yaml")
    policies = _load_yaml("policies.yaml")
    model_roles = _load_yaml("model_roles.yaml")
    _apply_env_overrides(defaults)

    merged = dict(defaults)
    merged["policies"] = policies
    merged["model_roles"] = model_roles
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
