"""Scientific experiments — hypothesis, measured delta, self-evaluation.

Lifecycle (``experiments.status``): PROPOSED -> RUNNING -> COMPLETED, or
FAILED when ``record_result`` carries a ``failure_reason``.

Anti-hallucination: a recorded ``delta_paise`` only counts when it is
supported by a real ledger/evidence reference. ``record_result`` zeroes the
delta (with a warning) whenever no ``supporting_evidence_id`` is given or the
id does not resolve to an existing ledger entry / evidence row.

Self-evaluation goes through the router's ``analyst`` role
(:meth:`ModelRouter.structured_output`) with a structured prompt and is
stored as prose + score. When the router is DEGRADED (no model), evaluation
uses the deterministic template :data:`EVALUATION_TEMPLATE` and NEVER
fabricates a verdict. Evaluation never auto-tunes weights/policy — any tuning
suggestion the model produces is stored as the string field ``suggestion``
that callers may (and usually should) ignore.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from orion.db import get_session
from orion.log import get_logger
from orion.models import (
    Experiment,
    ExperimentResult,
    LedgerEntry,
    MemoryItem,
)
from orion.memory import MemoryKind
from orion.router import ModelRouter

log = get_logger("experiments")

EXPERIMENT_STATUSES = ("PROPOSED", "RUNNING", "COMPLETED", "FAILED")

# Degraded-mode evaluation — honest, deterministic, no fabrication.
EVALUATION_TEMPLATE = "no model available — recorded for later review"

_EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},  # lets the router mark DEGRADED output
        "verdict": {"type": "string"},
        "score_0_100": {"type": "number"},
        "lesson": {"type": "string"},
        "suggestion": {"type": "string"},  # optional tuning note, stored only
    },
    "required": ["verdict", "score_0_100", "lesson"],
}

_EVALUATION_SYSTEM = (
    "You are ORION's experiment analyst. Judge only the RECORDED "
    "observation against the hypothesis and its expected result. "
    "Be terse and factual. A tuning suggestion may be given but it must "
    "never be treated as an automatic weight/policy change."
)


def _payload(row: Experiment) -> dict[str, Any]:
    if not row.payload_json:
        return {}
    try:
        loaded = json.loads(row.payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


class ExperimentService:
    """Lifecycle + results + self-evaluation over the experiment tables."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        hypothesis: str,
        strategy_id: Optional[int],
        params_paise: Optional[int],
        expected_result: str,
        session=None,
    ) -> Experiment:
        """Open a RUNNING experiment. (PROPOSED is the pre-start state; a
        started experiment is RUNNING by definition.)"""
        if session is None:
            with get_session() as s:
                return self.start(
                    hypothesis,
                    strategy_id,
                    params_paise,
                    expected_result,
                    session=s,
                )
        if not hypothesis or not str(hypothesis).strip():
            raise ValueError("experiment hypothesis must not be empty")
        payload = {
            "hypothesis": str(hypothesis).strip(),
            "strategy_id": int(strategy_id) if strategy_id is not None else None,
            "params_paise": int(params_paise) if params_paise is not None else 0,
            "expected_result": str(expected_result or ""),
            "evaluation": None,
            "suggestion": "",
        }
        row = Experiment(
            name=str(hypothesis).strip()[:255],
            payload_json=_dump(payload),
            status="RUNNING",
        )
        session.add(row)
        session.flush()
        log.info("experiment started", extra={"id": row.id})
        return row

    def record_result(
        self,
        id: int,
        observed_outcome: str,
        delta_paise: int,
        supporting_evidence_id: Optional[int] = None,
        failure_reason: Optional[str] = None,
        session=None,
    ) -> ExperimentResult:
        """Record one observation. Delta counts only with a real evidence id
        (a ledger entry or a memory EVIDENCE row); otherwise it is zeroed
        with a warning (anti-hallucination). Sets COMPLETED, or FAILED when
        ``failure_reason`` is given."""
        if session is None:
            with get_session() as s:
                return self.record_result(
                    id,
                    observed_outcome,
                    delta_paise,
                    supporting_evidence_id=supporting_evidence_id,
                    failure_reason=failure_reason,
                    session=s,
                )
        experiment = self.get(id, session=session)

        evidence_ok = self._evidence_resolves(supporting_evidence_id, session)
        warning = ""
        effective_delta = int(delta_paise or 0)
        if not evidence_ok:
            effective_delta = 0
            warning = (
                "no supporting evidence id resolves to a ledger/evidence row — "
                "delta zeroed (anti-hallucination)"
            )
            log.warning(
                "experiment result delta zeroed (no evidence)",
                extra={"experiment_id": id, "requested_delta_paise": delta_paise},
            )

        status = "FAILED" if failure_reason else "COMPLETED"
        result = ExperimentResult(
            experiment_id=id,
            observed_outcome=str(observed_outcome or ""),
            delta_paise=effective_delta,
            supporting_evidence_id=(
                int(supporting_evidence_id) if evidence_ok else None
            ),
            failure_reason=failure_reason,
            warning=warning,
        )
        session.add(result)
        experiment.status = status
        session.flush()
        log.info(
            "experiment result recorded",
            extra={
                "experiment_id": id,
                "result_id": result.id,
                "delta_paise": effective_delta,
                "status": status,
            },
        )
        return result

    # ------------------------------------------------------------------
    # Self-evaluation
    # ------------------------------------------------------------------

    def evaluate(self, id: int, session=None) -> dict[str, Any]:
        """Structured self-evaluation via the router ``analyst`` role.

        Returns ``{verdict, score_0_100, lesson, suggestion, degraded}``.
        In DEGRADED mode the verdict is :data:`EVALUATION_TEMPLATE` — no
        conclusion is fabricated. The evaluation is stored as prose + score
        on the experiment; any tuning hint lands in ``suggestion`` and is
        NEVER applied automatically.
        """
        if session is None:
            with get_session() as s:
                return self.evaluate(id, session=s)
        experiment = self.get(id, session=session)
        payload = _payload(experiment)
        results = self.results_for_experiment(id, session=session)

        user_prompt = (
            f"hypothesis: {payload.get('hypothesis', '')}\n"
            f"expected_result: {payload.get('expected_result', '')}\n"
            f"strategy_id: {payload.get('strategy_id')}\n"
            f"params_paise: {payload.get('params_paise')}\n"
            "recorded results:\n"
            + "\n".join(
                f"- {r.observed_outcome} (delta {r.delta_paise} paise, "
                f"evidence {r.supporting_evidence_id or 'none'}, "
                f"{r.failure_reason or 'ok'})"
                for r in results
            )
        )

        router = ModelRouter()
        out = router.structured_output(
            "analyst", _EVALUATION_SYSTEM, user_prompt, _EVALUATION_SCHEMA
        )

        if out.get("status") == "degraded":
            evaluation = {
                "verdict": EVALUATION_TEMPLATE,
                "score_0_100": 0,
                "lesson": "",
                "suggestion": "",
                "degraded": True,
            }
            log.info(
                "experiment evaluation DEGRADED (template, no fabrication)",
                extra={"experiment_id": id},
            )
        else:
            evaluation = {
                "verdict": str(out.get("verdict") or ""),
                "score_0_100": float(out.get("score_0_100") or 0.0),
                "lesson": str(out.get("lesson") or ""),
                "suggestion": str(out.get("suggestion") or ""),
                "degraded": False,
            }

        payload["evaluation"] = evaluation
        payload["suggestion"] = evaluation["suggestion"]  # stored, never applied
        experiment.payload_json = _dump(payload)
        session.flush()
        log.info(
            "experiment evaluated",
            extra={
                "experiment_id": id,
                "degraded": evaluation["degraded"],
                "score_0_100": evaluation["score_0_100"],
            },
        )
        return evaluation

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_experiments(self, session=None) -> list[Experiment]:
        """All experiments, newest first."""
        if session is None:
            with get_session() as s:
                return self.list_experiments(session=s)
        return list(session.query(Experiment).order_by(Experiment.id.desc()))

    def get(self, id: int, session=None) -> Experiment:
        """Fetch one experiment; raises ValueError when missing."""
        if session is None:
            with get_session() as s:
                return self.get(id, session=s)
        row = session.get(Experiment, id)
        if row is None:
            raise ValueError(f"experiment {id} not found")
        return row

    def results_for(self, strategy_id: int, session=None) -> list[ExperimentResult]:
        """Every result recorded under experiments of a strategy."""
        if session is None:
            with get_session() as s:
                return self.results_for(strategy_id, session=s)
        experiment_ids = [
            e.id
            for e in session.query(Experiment)
            if _payload(e).get("strategy_id") == int(strategy_id)
        ]
        if not experiment_ids:
            return []
        return list(
            session.query(ExperimentResult)
            .filter(ExperimentResult.experiment_id.in_(experiment_ids))
            .order_by(ExperimentResult.id.desc())
        )

    # ------------------------------------------------------------------

    def results_for_experiment(self, id: int, session=None) -> list[ExperimentResult]:
        """All results of one experiment, oldest first."""
        if session is None:
            with get_session() as s:
                return self.results_for_experiment(id, session=s)
        return list(
            session.query(ExperimentResult)
            .filter(ExperimentResult.experiment_id == id)
            .order_by(ExperimentResult.id.asc())
        )

    @staticmethod
    def _evidence_resolves(evidence_id, session) -> bool:
        """True when the id names a real ledger entry or memory EVIDENCE row."""
        if evidence_id is None:
            return False
        try:
            evidence_id = int(evidence_id)
        except (TypeError, ValueError):
            return False
        if session.get(LedgerEntry, evidence_id) is not None:
            return True
        row = session.get(MemoryItem, evidence_id)
        return row is not None and row.kind == MemoryKind.EVIDENCE.value
