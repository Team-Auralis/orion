"""ORION HTTP API — FastAPI app exposing every subsystem over /api.

Design rules
------------
* Money decisions go through policy+safety ALWAYS. Policy is hard logic;
  model output never influences it. The ledger endpoints below consult
  BudgetPolicy -> SafetyEngine -> ApprovalService with real sessions; a
  blocked decision is a 403, never a silent pass.
* Money is serialized in integer paise, and every money field ALSO carries a
  formatted ``₹`` string via :func:`orion.ledger.fmt_paise`.
* The event bus (:mod:`orion.events`) is the single publish point — the API
  publishes on behalf of the subsystems it orchestrates; the Activity UI
  consumes the same stream over SSE (GET /api/activity).
* The kill switch is a hard circuit breaker: engage it and every financial
  endpoint 403s immediately (checked first inside SafetyEngine).
"""

from __future__ import annotations

import json
import queue
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from orion import events, jobs, ledger
from orion.config import get_config
from orion.db import get_session, init_db
from orion.discovery import DiscoveryService
from orion.experiments import ExperimentService
from orion.ledger import fmt_paise
from orion.log import get_logger
from orion.memory import query as memory_query
from orion.models import Opportunity, utc_now_iso
from orion.router import ModelRouter
from orion.safety import ApprovalService, Decision, SafetyEngine
from orion.scoring import OpportunityScorer
from orion.security import KillSwitchService
from orion.strategy import StrategyService
from orion.tools import ensure_workspace_dirs

log = get_logger("api")

AUTONOMY_MAP = {
    "research": "ENABLED",
    "local_files": "ENABLED",
    "messaging": "APPROVAL",
    "purchases": "APPROVAL",
    "financial": "APPROVAL",
    "high_impact": "BLOCKED",
}

_STARTED_AT = time.monotonic()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    ensure_workspace_dirs()
    with get_session() as s:
        ledger.seed_capital(s, get_config().orion.starting_capital)
    # Load (or create) the singleton kill-switch row so status reflects the DB.
    KillSwitchService().status()
    yield


app = FastAPI(title="ORION API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_config().api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    """JSON-serializable API error with an explicit HTTP status."""

    status_code = 500

    def __init__(
        self,
        detail: str,
        status_code: Optional[int] = None,
        reasons: Optional[list[str]] = None,
    ):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        self.reasons = reasons or []


class BlockedByPolicy(ApiError):
    """A hard policy/safety denial — 403 with the reasons array."""

    def __init__(self, detail: str, reasons: list[str]):
        super().__init__(detail, 403, reasons)


@app.exception_handler(ApiError)
async def _api_error(request: Request, exc: ApiError):
    if isinstance(exc, BlockedByPolicy):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "blocked_by_policy",
                "detail": exc.detail,
                "reasons": exc.reasons,
            },
        )
    content: dict[str, Any] = {"error": "request_failed", "detail": exc.detail}
    if exc.reasons:
        content["reasons"] = exc.reasons
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    errors = [
        {
            "loc": [str(part) for part in err.get("loc", [])],
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=400, content={"error": "validation_error", "detail": errors}
    )


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError):
    if "not found" in str(exc).lower():
        return JSONResponse(
            status_code=404, content={"error": "not_found", "detail": str(exc)}
        )
    return JSONResponse(
        status_code=400, content={"error": "bad_request", "detail": str(exc)}
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled API error", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Event publishing (the bus must never break an API call)
# ---------------------------------------------------------------------------


def _publish(
    event_type: str,
    *,
    agent: str = "system",
    entity_id=None,
    metadata=None,
    correlation_id=None,
) -> None:
    try:
        events.publish(
            event_type,
            agent=agent,
            entity_id=entity_id,
            metadata=metadata,
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001 — observers are best-effort
        log.warning("event publish failed", extra={"event": event_type})


# ---------------------------------------------------------------------------
# Serializers — money is always BOTH *_paise int AND a formatted ₹ string
# ---------------------------------------------------------------------------


def _entry_payload(entry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "type": entry.type,
        "amount_paise": entry.amount_paise,
        "amount_formatted": fmt_paise(entry.amount_paise),
        "currency": entry.currency,
        "source": entry.source,
        "destination": entry.destination,
        "reference": entry.reference,
        "status": entry.status,
        "verification_method": entry.verification_method,
        "confidence": entry.confidence,
        "correlation_id": entry.correlation_id,
        "created_at": entry.created_at,
        "metadata": json.loads(entry.metadata_json) if entry.metadata_json else {},
    }


_MONEY_KEYS = (
    "capital",
    "available_cash",
    "reserved_cash",
    "spent",
    "revenue",
    "verified_revenue",
    "pending_revenue",
    "total_revenue",
    "fees",
    "refunds",
    "net_profit",
)


def _summary_payload(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    for key in _MONEY_KEYS:
        if key in out:
            out[f"{key}_formatted"] = fmt_paise(out[key])
    out["target_paise_formatted"] = fmt_paise(out.get("target_paise", 0))
    return out


def _approval_payload(record) -> dict[str, Any]:
    payload = json.loads(record.payload_json) if record.payload_json else {}
    cost = record.cost_paise
    return {
        "id": record.id,
        "kind": record.kind,
        "why": record.why,
        "payload": payload,
        "cost_paise": cost,
        "cost_formatted": fmt_paise(cost) if cost is not None else None,
        "potential_revenue_paise": record.potential_revenue_paise,
        "risk_level": record.risk_level,
        "destination": record.destination,
        "correlation_id": record.correlation_id,
        "status": record.status,
        "decision": record.decision,
        "decision_reason": record.decision_reason,
        "created_at": record.created_at,
        "decided_at": record.decided_at,
        "consumed_at": record.consumed_at,
        "expires_at": record.expires_at,
    }


def _opportunity_payload(row) -> dict[str, Any]:
    factors: dict[str, Any] = {}
    if row.factors_json:
        try:
            loaded = json.loads(row.factors_json)
            factors = loaded if isinstance(loaded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            pass
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "status": row.status,
        "source": row.source,
        "source_connector": row.source_connector,
        "url": row.url,
        "description": row.description,
        "estimated_value_paise": row.estimated_value_paise,
        "estimated_value_formatted": fmt_paise(row.estimated_value_paise),
        "cost_paise": row.cost_paise,
        "cost_formatted": fmt_paise(row.cost_paise),
        "score_0_100": row.score_0_100,
        "factors": factors,
        "suspicious": row.suspicious,
        "suspicious_reason": row.suspicious_reason,
        "rejected_reason": row.rejected_reason,
        "last_seen": row.last_seen,
        "created_at": row.created_at,
    }


def _strategy_payload(row, perf: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(row.payload_json) if row.payload_json else {}
    max_spend = int(payload.get("max_spend_paise") or 0)
    required_capital = int(payload.get("required_capital_paise") or 0)
    perf_payload = dict(perf)
    for key in (
        "total_profit_paise",
        "total_revenue_paise",
        "total_fees_paise",
        "avg_profit_per_hour_paise",
    ):
        if key in perf_payload:
            perf_payload[f"{key}_formatted"] = fmt_paise(perf_payload[key])
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "created_at": row.created_at,
        "description": payload.get("description", ""),
        "risk_level": payload.get("risk_level"),
        "automation_level": payload.get("automation_level"),
        "min_opportunity_score": payload.get("min_opportunity_score"),
        "max_spend_paise": max_spend,
        "max_spend_formatted": fmt_paise(max_spend),
        "required_capital_paise": required_capital,
        "required_capital_formatted": fmt_paise(required_capital),
        "required_skills": payload.get("required_skills", []),
        "allowed_risk_levels": payload.get("allowed_risk_levels", []),
        "activation_reasons": payload.get("activation_reasons", []),
        "performance_summary": perf_payload,
    }


def _experiment_payload(row) -> dict[str, Any]:
    payload = json.loads(row.payload_json) if row.payload_json else {}
    params = payload.get("params_paise")
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "created_at": row.created_at,
        "hypothesis": payload.get("hypothesis"),
        "strategy_id": payload.get("strategy_id"),
        "params_paise": params,
        "params_formatted": fmt_paise(params) if params is not None else None,
        "expected_result": payload.get("expected_result"),
        "evaluation": payload.get("evaluation"),
    }


def _job_payload(row) -> dict[str, Any]:
    payload = {}
    if row.payload_json:
        try:
            loaded = json.loads(row.payload_json)
            payload = loaded if isinstance(loaded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            pass
    return {
        "id": row.id,
        "name": row.name,
        "job_type": row.job_type,
        "status": row.status,
        "priority": row.priority,
        "attempts": row.attempts,
        "error": row.error,
        "payload": payload,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _memory_payload(row) -> dict[str, Any]:
    payload = {}
    if row.payload_json:
        try:
            loaded = json.loads(row.payload_json)
            payload = loaded if isinstance(loaded, dict) else {"raw": loaded}
        except (TypeError, json.JSONDecodeError):
            pass
    return {
        "id": row.id,
        "kind": row.kind,
        "content": row.content,
        "confidence": row.confidence,
        "source": row.source,
        "verified": row.verified,
        "status": row.status,
        "direction": row.direction,
        "reference": row.reference,
        "payload": payload,
        "created_at": row.created_at,
    }


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SpendRequest(BaseModel):
    amount_paise: int = Field(gt=0, description="integer paise, always positive")
    category: str = Field(min_length=1)
    reason: str = ""
    correlation_id: Optional[str] = None


class RevenueRequest(BaseModel):
    amount_paise: int = Field(gt=0)
    source: str = Field(min_length=1)
    reference: str = ""
    verification_method: Optional[str] = None
    confidence: float = 0.0
    correlation_id: Optional[str] = None


class ConfirmPayoutRequest(BaseModel):
    """Human-supplied evidence for real income (the sanctioned payout path).

    ``evidence_ref`` is mandatory and must be a real reference (payout CSV
    path, transaction/payout id). Empty/whitespace evidence is refused —
    without evidence a payout is never marked VERIFIED.
    """

    amount_paise: int = Field(gt=0)
    source: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    confirmed_by: str = Field(min_length=1)
    correlation_id: Optional[str] = None


class StrategyProposeRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    required_capital_paise: int = 0
    required_skills: list[str] = []
    automation_level: str = "manual"
    risk_level: str = "L2"
    min_opportunity_score: float = 0.0
    max_spend_paise: int = 0
    allowed_risk_levels: list[str] = []


class ExperimentStartRequest(BaseModel):
    hypothesis: str = Field(min_length=1)
    strategy_id: Optional[int] = None
    params_paise: Optional[int] = None
    expected_result: str = ""


class JobEnqueueRequest(BaseModel):
    job_type: str = Field(min_length=1)
    payload: dict[str, Any] = {}
    priority: int = 0


class KillRequest(BaseModel):
    reason: str = ""


class RejectRequest(BaseModel):
    reason: str = "rejected via API"


# ---------------------------------------------------------------------------
# Status / health
# ---------------------------------------------------------------------------


def _db_ok() -> bool:
    try:
        with get_session() as s:
            s.execute(ledger.LedgerEntry.__table__.select().limit(1))
            return True
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/status")
def api_status():
    cfg = get_config()
    kill = KillSwitchService().status()
    model = ModelRouter().health()
    model_status = "OK" if model.available else "DEGRADED"
    return {
        "mode": cfg.autonomy.default_mode,
        "kill_switch_active": kill["active"],
        "kill_switch_reason": kill.get("reason"),
        "model_status": model_status,
        "model_detail": model.detail,
        "db_ok": _db_ok(),
        "uptime_s": int(time.monotonic() - _STARTED_AT),
        "autonomy": dict(AUTONOMY_MAP),
    }


@app.get("/api/health")
def api_health():
    checks: dict[str, str] = {}
    checks["db"] = "pass" if _db_ok() else "fail"
    model = ModelRouter().health()
    checks["model"] = "ok" if model.available else "degraded"
    try:
        cfg = get_config()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.data_dir / ".health-probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        checks["filesystem"] = "pass"
    except Exception:  # noqa: BLE001
        checks["filesystem"] = "fail"
    checks["kill_switch"] = "active" if KillSwitchService().is_killed() else "inactive"
    ok = checks["db"] == "pass" and checks["filesystem"] == "pass"
    return {"ok": ok, "checks": checks}


# ---------------------------------------------------------------------------
# Ledger — money endpoints. Policy is hard logic; model output never
# influences it. Every spend consults BudgetPolicy -> SafetyEngine ->
# ApprovalService before any ledger write; a blocked decision is a 403.
# ---------------------------------------------------------------------------


@app.get("/api/ledger")
def api_ledger(limit: int = 50):
    with get_session() as s:
        summary = ledger.summary(s)
        entries = ledger.get_ledger(s, limit=max(1, min(limit, 500)))
    return {
        "summary": _summary_payload(summary),
        "entries": [_entry_payload(e) for e in entries],
    }


@app.post("/api/ledger/spend")
def api_spend(req: SpendRequest):
    mode = get_config().autonomy.default_mode
    with get_session() as s:
        decision = SafetyEngine().evaluate(
            {
                "action": "spend",
                "amount_paise": req.amount_paise,
                "category": req.category,
            },
            session=s,
        )
        if decision.decision == Decision.BLOCKED:
            raise BlockedByPolicy("spend blocked by policy", decision.reasons)

        record = None
        if decision.decision == Decision.APPROVAL:
            record = ApprovalService().request(
                "spend",
                why=req.reason or f"spend {req.amount_paise} paise ({req.category})",
                cost_paise=req.amount_paise,
                risk_level=decision.level.value,
                proposed_payload={
                    "category": req.category,
                    "reason": req.reason,
                    "amount_paise": req.amount_paise,
                },
                destination=req.category,
                correlation_id=req.correlation_id,
                session=s,
            )

        if record is not None and record.status == "APPROVED":
            # Dry-run auto-approval (decision=dry_run_auto_approve).
            _publish(
                "approval_approved",
                agent="safety",
                entity_id=record.id,
                metadata={"decision": record.decision},
                correlation_id=req.correlation_id,
            )
            if mode in ("assisted", "autonomous"):
                entry = ledger.spend(
                    s,
                    req.amount_paise,
                    destination=req.category,
                    reference=f"approval:{record.id}",
                    correlation_id=req.correlation_id,
                )
                _publish(
                    "ledger_write",
                    agent="ledger",
                    entity_id=entry.id,
                    metadata={
                        "type": entry.type,
                        "amount_paise": entry.amount_paise,
                        "approval_id": record.id,
                    },
                    correlation_id=req.correlation_id,
                )
                return {
                    "status": "COMPLETED",
                    "mode": mode,
                    "approval": _approval_payload(record),
                    "entry": _entry_payload(entry),
                }
            # Dry-run: NEVER spends — the approval is a simulation.
            return {
                "status": "SIMULATED",
                "simulated": True,
                "mode": mode,
                "approval": _approval_payload(record),
                "entry": None,
            }

        if record is not None:  # PENDING — human decision required
            _publish(
                "approval_requested",
                agent="safety",
                entity_id=record.id,
                metadata={"cost_paise": record.cost_paise},
                correlation_id=req.correlation_id,
            )
            return {
                "status": "PENDING",
                "mode": mode,
                "approval": _approval_payload(record),
                "entry": None,
            }

        # Decision AUTO — policy allows the spend without an approval record.
        if mode == "dry_run":
            return {
                "status": "SIMULATED",
                "simulated": True,
                "mode": mode,
                "approval": None,
                "entry": None,
            }
        entry = ledger.spend(
            s,
            req.amount_paise,
            destination=req.category,
            reference="api-spend-auto",
            correlation_id=req.correlation_id,
        )
        _publish(
            "ledger_write",
            agent="ledger",
            entity_id=entry.id,
            metadata={"type": entry.type, "amount_paise": entry.amount_paise},
            correlation_id=req.correlation_id,
        )
        return {
            "status": "COMPLETED",
            "mode": mode,
            "approval": None,
            "entry": _entry_payload(entry),
        }


def _revenue_result(
    entry, summary, correlation_id=None, *, evidence_ref=None
) -> dict[str, Any]:
    """Publish the ledger_write event and build the shared revenue response."""
    metadata: dict[str, Any] = {
        "type": entry.type,
        "status": entry.status,
        "amount_paise": entry.amount_paise,
    }
    if evidence_ref:
        metadata["evidence_ref"] = evidence_ref
    _publish(
        "ledger_write",
        agent="ledger",
        entity_id=entry.id,
        metadata=metadata,
        correlation_id=correlation_id,
    )
    return {
        "entry": _entry_payload(entry),
        "status": entry.status,
        "verified": entry.status == "VERIFIED",
        "verified_revenue_paise": summary["verified_revenue"],
        "verified_revenue_formatted": fmt_paise(summary["verified_revenue"]),
        "available_cash_paise": summary["available_cash"],
        "available_cash_formatted": fmt_paise(summary["available_cash"]),
    }


@app.post("/api/ledger/revenue")
def api_revenue(req: RevenueRequest):
    with get_session() as s:
        entry = ledger.record_revenue(
            s,
            req.amount_paise,
            source=req.source,
            reference=req.reference or "api-revenue",
            verification_method=req.verification_method,
            confidence=req.confidence,
            correlation_id=req.correlation_id,
        )
        summary = ledger.summary(s)
    return _revenue_result(entry, summary, req.correlation_id)


@app.post("/api/ledger/confirm-payout")
def api_confirm_payout(req: ConfirmPayoutRequest):
    """Sanctioned 'I got paid, here's the proof' — VERIFIED revenue gated by
    hard evidence. The only revenue path besides the existing verified
    record_revenue that can mark VERIFIED."""
    with get_session() as s:
        entry = ledger.record_verified_payout(
            s,
            req.amount_paise,
            source=req.source,
            reference=req.reference,
            evidence_ref=req.evidence_ref,
            confirmed_by=req.confirmed_by,
            correlation_id=req.correlation_id,
        )
        summary = ledger.summary(s)
    return _revenue_result(
        entry, summary, req.correlation_id, evidence_ref=req.evidence_ref
    )


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------


@app.get("/api/opportunities")
def api_opportunities(status: Optional[str] = None, limit: int = 100):
    with get_session() as s:
        rows = DiscoveryService().list_opportunities(
            session=s, status=status, limit=max(1, min(limit, 500))
        )
    return {
        "opportunities": [_opportunity_payload(r) for r in rows],
        "count": len(rows),
    }


@app.post("/api/opportunities/scan")
def api_opportunities_scan():
    from orion.connectors.base import SourceOffer

    discoverer = DiscoveryService()
    scorer = OpportunityScorer()
    with get_session() as s:
        created = discoverer.scan(s)
        for row in created:
            _publish(
                "opportunity_discovered",
                agent="discovery",
                entity_id=row.id,
                metadata={"name": row.name},
            )
        scored = 0
        pending = s.query(Opportunity).filter(Opportunity.status == "DISCOVERED").all()
        for row in pending:
            offer = SourceOffer.model_validate_json(row.payload_json)
            scorer.score_opportunity_from_offer(offer, s)
            scored += 1
            _publish(
                "opportunity_scored",
                agent="scoring",
                entity_id=row.id,
                metadata={"score": row.score_0_100},
            )
        total = s.query(Opportunity).count()
    return {"created": len(created), "scored": scored, "total": total}


# ---------------------------------------------------------------------------
# Strategies / experiments
# ---------------------------------------------------------------------------


@app.get("/api/strategies")
def api_strategies():
    service = StrategyService()
    with get_session() as s:
        rows = service.list_strategies(session=s)
        strategies = [
            _strategy_payload(row, service.performance_summary(row.id, session=s))
            for row in rows
        ]
    return {"strategies": strategies, "count": len(strategies)}


@app.post("/api/strategies")
def api_propose_strategy(req: StrategyProposeRequest):
    service = StrategyService()
    row = service.propose(
        req.name,
        req.description,
        req.required_capital_paise,
        req.required_skills,
        req.automation_level,
        req.risk_level,
        req.min_opportunity_score,
        req.max_spend_paise,
        req.allowed_risk_levels,
    )
    return _strategy_payload(row, service.performance_summary(row.id))


@app.get("/api/experiments")
def api_experiments():
    with get_session() as s:
        rows = ExperimentService().list_experiments(session=s)
    experiments = [_experiment_payload(r) for r in rows]
    return {"experiments": experiments, "count": len(experiments)}


@app.post("/api/experiments")
def api_start_experiment(req: ExperimentStartRequest):
    with get_session() as s:
        row = ExperimentService().start(
            req.hypothesis,
            strategy_id=req.strategy_id,
            params_paise=req.params_paise,
            expected_result=req.expected_result,
            session=s,
        )
    _publish(
        "experiment_started",
        agent="experiments",
        entity_id=row.id,
        metadata={"hypothesis": row.name},
    )
    return _experiment_payload(row)


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@app.get("/api/approvals")
def api_approvals(status: Optional[str] = None, limit: int = 50):
    service = ApprovalService()
    with get_session() as s:
        if (status or "").lower() == "pending":
            rows = service.pending(session=s)
        else:
            rows = service.history(limit=max(1, min(limit, 500)), session=s)
    return {"approvals": [_approval_payload(r) for r in rows], "count": len(rows)}


def _execute_approved_spend(record, session) -> Optional[Any]:
    """Execute the money move behind an approved ``spend`` approval record.

    The approval IS the authorization; the ledger write still runs through
    ledger.spend() which re-enforces the single/daily/total-loss guardrails.
    An approval funds exactly ONE spend: ``consumed_at`` is stamped on the
    first execution, and any later attempt (a second approve() call has
    already failed — the record is no longer PENDING) raises here too.
    """
    if record.kind != "spend" or record.status != "APPROVED":
        return None
    if record.consumed_at is not None:
        raise ApiError(f"approval {record.id} already consumed", 400)
    if record.cost_paise is None or record.cost_paise <= 0:
        raise ApiError(f"spend approval {record.id} has no valid cost_paise", 400)
    payload = json.loads(record.payload_json) if record.payload_json else {}
    category = str(payload.get("category") or record.destination or "spend")
    entry = ledger.spend(
        session,
        int(record.cost_paise),
        destination=category,
        reference=f"approval:{record.id}",
        correlation_id=record.correlation_id,
    )
    record.consumed_at = utc_now_iso()
    session.flush()
    _publish(
        "ledger_write",
        agent="ledger",
        entity_id=entry.id,
        metadata={
            "type": entry.type,
            "amount_paise": entry.amount_paise,
            "approval_id": record.id,
        },
        correlation_id=record.correlation_id,
    )
    return entry


@app.post("/api/approvals/{approval_id}/approve")
def api_approve(approval_id: int):
    service = ApprovalService()
    with get_session() as s:
        record = service.approve(int(approval_id), reason="approved via API", session=s)
        entry = _execute_approved_spend(record, s)
    _publish(
        "approval_approved",
        agent="safety",
        entity_id=record.id,
        metadata={"decision": record.decision},
        correlation_id=record.correlation_id,
    )
    return {
        "status": record.status,
        "approval": _approval_payload(record),
        "entry": _entry_payload(entry) if entry is not None else None,
    }


@app.post("/api/approvals/{approval_id}/reject")
def api_reject(approval_id: int, body: RejectRequest):
    record = ApprovalService().reject(int(approval_id), reason=body.reason)
    _publish(
        "approval_rejected",
        agent="safety",
        entity_id=record.id,
        metadata={"reason": body.reason},
        correlation_id=record.correlation_id,
    )
    return {"status": record.status, "approval": _approval_payload(record)}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@app.post("/api/jobs")
def api_enqueue_job(req: JobEnqueueRequest):
    with get_session() as s:
        row = jobs.enqueue(
            req.job_type, payload=req.payload, priority=req.priority, session=s
        )
    return _job_payload(row)


@app.get("/api/jobs")
def api_jobs(status: Optional[str] = None, limit: int = 50):
    with get_session() as s:
        rows = jobs.list_jobs(status=status, limit=max(1, min(limit, 500)), session=s)
    return {"jobs": [_job_payload(r) for r in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Kill switch / memory / activity
# ---------------------------------------------------------------------------


@app.post("/api/kill")
def api_kill(body: Optional[KillRequest] = None):
    return KillSwitchService().kill(reason=body.reason if body else "")


@app.post("/api/kill/lift")
def api_kill_lift(body: Optional[KillRequest] = None):
    return KillSwitchService().lift(reason=body.reason if body else "")


@app.get("/api/memory")
def api_memory(category: Optional[str] = None, limit: int = 50):
    with get_session() as s:
        rows = memory_query(s, category=category, limit=max(1, min(limit, 500)))
    memories = [_memory_payload(r) for r in rows]
    return {"memories": memories, "count": len(memories)}


@app.get("/api/activity/recent")
def api_activity_recent(limit: int = 50):
    records = events.recent(limit=max(1, min(limit, 500)))
    return {
        "events": [r.as_dict() for r in records],
        "count": len(records),
    }


@app.get("/api/activity")
async def api_activity(request: Request):
    """Server-Sent Events stream: replays recent history, then live events.

    Pings every 15s (SSE comment lines) to defeat proxy idle timeouts.
    """

    subscriber = events.subscribe()

    async def stream():
        try:
            for record in events.recent(limit=50):
                yield f"data: {json.dumps(record.as_dict(), ensure_ascii=False)}\n\n"
            last_ping = time.monotonic()
            while True:
                try:
                    record = await _queue_get(subscriber)
                except queue.Empty:
                    record = None
                if record is not None:
                    yield (
                        f"data: {json.dumps(record.as_dict(), ensure_ascii=False)}\n\n"
                    )
                    continue
                if time.monotonic() - last_ping >= 15:
                    yield ": ping\n\n"
                    last_ping = time.monotonic()
                try:
                    if await request.is_disconnected():
                        break
                except Exception:  # noqa: BLE001 — disconnect check is best-effort
                    pass
        finally:
            events.unsubscribe(subscriber)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _queue_get(subscriber: queue.Queue):
    """Blocking queue read without stalling the event loop."""
    import asyncio

    return await asyncio.to_thread(subscriber.get, True, 1.0)
