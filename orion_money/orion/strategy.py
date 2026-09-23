"""Strategy engine — lifecycle + evidence-based ranking of trading strategies.

Lifecycle (``strategies.status``): PROPOSED -> ACTIVE -> PAUSED -> RETIRED.
Activation is deterministic and hard-gated (never an LLM): the strategy's
``risk_level`` must pass the configured safety matrix (a BLOCKED default
decision refuses activation), ``max_spend_paise`` must sit inside the budget
guardrails, ``min_opportunity_score`` must reference a real 0..100 score
tier, and ``risk_level`` must be inside ``allowed_risk_levels`` when one is
given. A refused activation records its reasons and stays PROPOSED.

Ranking NEVER uses LLM opinion. :meth:`StrategyService.best_strategy_by_evidence`
ranks ACTIVE strategies purely by accumulated ``profit_per_hour_paise`` from
recorded :class:`StrategyRun` rows — the engine prefers evidence, and a
strategy with no runs has no evidence to rank on.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from orion.config import get_config
from orion.db import get_session
from orion.log import get_logger
from orion.models import Strategy, StrategyRun
from orion.safety import matrix

log = get_logger("strategy")

STRATEGY_STATUSES = ("PROPOSED", "ACTIVE", "PAUSED", "RETIRED")
SCORE_TIER_MIN, SCORE_TIER_MAX = 0.0, 100.0

# Payload keys (the Strategy stub carries its params in ``payload_json``).
P_DESCRIPTION = "description"
P_REQUIRED_CAPITAL = "required_capital_paise"
P_REQUIRED_SKILLS = "required_skills"
P_AUTOMATION_LEVEL = "automation_level"
P_RISK_LEVEL = "risk_level"
P_MIN_SCORE = "min_opportunity_score"
P_MAX_SPEND = "max_spend_paise"
P_ALLOWED_LEVELS = "allowed_risk_levels"
P_REASONS = "activation_reasons"


def _payload(row: Strategy) -> dict[str, Any]:
    if not row.payload_json:
        return {}
    try:
        loaded = json.loads(row.payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


class StrategyService:
    """Lifecycle + evidence over the ``strategies`` / ``strategy_runs`` tables."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def propose(
        self,
        name: str,
        description: str,
        required_capital_paise: int,
        required_skills: list[str],
        automation_level: str,
        risk_level: str,
        min_opportunity_score: float,
        max_spend_paise: int,
        allowed_risk_levels: list[str],
        session=None,
    ) -> Strategy:
        """Create a PROPOSED strategy (no gating — proposals are free)."""
        if session is None:
            with get_session() as s:
                return self.propose(
                    name,
                    description,
                    required_capital_paise,
                    required_skills,
                    automation_level,
                    risk_level,
                    min_opportunity_score,
                    max_spend_paise,
                    allowed_risk_levels,
                    session=s,
                )
        if not name or not str(name).strip():
            raise ValueError("strategy name must not be empty")
        payload = {
            P_DESCRIPTION: str(description or ""),
            P_REQUIRED_CAPITAL: int(required_capital_paise or 0),
            P_REQUIRED_SKILLS: list(required_skills or []),
            P_AUTOMATION_LEVEL: str(automation_level or "manual"),
            P_RISK_LEVEL: str(risk_level or "L2"),
            P_MIN_SCORE: float(min_opportunity_score or 0.0),
            P_MAX_SPEND: int(max_spend_paise or 0),
            P_ALLOWED_LEVELS: list(allowed_risk_levels or []),
            P_REASONS: [],
        }
        row = Strategy(
            name=str(name).strip(),
            payload_json=_dump(payload),
            status="PROPOSED",
        )
        session.add(row)
        session.flush()
        log.info("strategy proposed", extra={"id": row.id, "strategy_name": row.name})
        return row

    def activate(self, id: int, session=None) -> Strategy:
        """PROPOSED/PAUSED -> ACTIVE, but only when every hard constraint holds.

        Refusals record their reasons in ``payload_json.activation_reasons``
        and leave the strategy PROPOSED — activation is never forced.
        """
        if session is None:
            with get_session() as s:
                return self.activate(id, session=s)
        row = self.get(id, session=session)
        if row.status == "ACTIVE":
            return row
        if row.status == "RETIRED":
            raise ValueError(f"strategy {id} is RETIRED and cannot be activated")

        payload = _payload(row)
        reasons: list[str] = []
        refused = False
        cfg = get_config()

        # 1. Risk level against the safety matrix.
        risk_level = str(payload.get(P_RISK_LEVEL, "L2"))
        policies = cfg.policies
        m = matrix()
        if risk_level in policies.levels:
            decision = policies.levels[risk_level]
        elif risk_level in m:
            decision = m[risk_level].decision.value
        else:
            decision = "UNKNOWN"
        if decision == "BLOCKED":
            refused = True
            reasons.append(f"risk level {risk_level} has BLOCKED default decision")
        else:
            reasons.append(
                f"risk level {risk_level} default decision {decision} (allowed)"
            )

        # 2. Max per-run spend inside the budget guardrails.
        max_spend = int(payload.get(P_MAX_SPEND, 0) or 0)
        if max_spend > cfg.risk_guardrails.max_single_spend:
            refused = True
            reasons.append(
                f"max_spend_paise {max_spend} exceeds max_single_spend "
                f"{cfg.risk_guardrails.max_single_spend}"
            )
        else:
            reasons.append(f"max_spend_paise {max_spend} within budget guardrails")

        # 3. Opportunity score tier must be real (0..100).
        min_score = float(payload.get(P_MIN_SCORE, 0.0) or 0.0)
        if not (SCORE_TIER_MIN <= min_score <= SCORE_TIER_MAX):
            refused = True
            reasons.append(
                f"min_opportunity_score {min_score} outside real score tier "
                f"{SCORE_TIER_MIN}..{SCORE_TIER_MAX}"
            )
        else:
            reasons.append(
                f"min_opportunity_score {min_score} references a real score tier"
            )

        # 4. Declared allowed levels must contain the strategy's own level.
        allowed = [str(x) for x in payload.get(P_ALLOWED_LEVELS, []) or []]
        if allowed and risk_level not in allowed:
            refused = True
            reasons.append(
                f"risk_level {risk_level} not in allowed_risk_levels {allowed}"
            )

        payload[P_REASONS] = reasons
        if refused:
            row.payload_json = _dump(payload)
            log.warning(
                "strategy activation refused",
                extra={"id": id, "reasons": reasons},
            )
            return row

        row.status = "ACTIVE"
        row.payload_json = _dump(payload)
        session.flush()
        log.info("strategy activated", extra={"id": id, "strategy_name": row.name})
        return row

    def pause(self, id: int, session=None) -> Strategy:
        """ACTIVE -> PAUSED. Only an ACTIVE strategy can pause."""
        if session is None:
            with get_session() as s:
                return self.pause(id, session=s)
        row = self.get(id, session=session)
        if row.status != "ACTIVE":
            raise ValueError(
                f"strategy {id} must be ACTIVE to pause (status={row.status})"
            )
        row.status = "PAUSED"
        session.flush()
        log.info("strategy paused", extra={"id": id})
        return row

    def retire(self, id: int, session=None) -> Strategy:
        """Any live status -> RETIRED (terminal)."""
        if session is None:
            with get_session() as s:
                return self.retire(id, session=s)
        row = self.get(id, session=session)
        if row.status != "RETIRED":
            row.status = "RETIRED"
            session.flush()
            log.info("strategy retired", extra={"id": id})
        return row

    # ------------------------------------------------------------------
    # Execution evidence
    # ------------------------------------------------------------------

    def record_run(
        self, id: int, run_summary: dict[str, Any], session=None
    ) -> StrategyRun:
        """Persist one execution result for a strategy.

        ``run_summary`` keys map 1:1 onto :class:`StrategyRun` columns;
        missing keys default to zero. ``profit_per_hour_paise`` is computed
        as ``profit_paise / time_hours`` when the caller omits it, and
        ``failure_rate`` as ``losses / (wins + losses)`` when omitted.
        """
        if session is None:
            with get_session() as s:
                return self.record_run(id, run_summary, session=s)
        self.get(id, session=session)  # raises when the strategy is missing

        def _num(*keys: str, default: Any = 0) -> float:
            for key in keys:
                value = run_summary.get(key)
                if value is not None:
                    return float(value)
            return default

        wins = int(_num("wins"))
        losses = int(_num("losses"))
        time_hours = _num("time_hours")
        profit = int(_num("profit_paise"))
        profit_per_hour = run_summary.get("profit_per_hour_paise")
        if profit_per_hour is None:
            profit_per_hour = (
                int(round(profit / time_hours)) if time_hours > 0 else profit
            )
        failure_rate = run_summary.get("failure_rate")
        if failure_rate is None:
            outcomes = wins + losses
            failure_rate = round(losses / outcomes, 4) if outcomes else 0.0

        run = StrategyRun(
            strategy_id=id,
            capital_used_paise=int(_num("capital_used_paise")),
            time_hours=time_hours,
            opportunities_checked=int(_num("opportunities_checked")),
            responses=int(_num("responses")),
            wins=wins,
            losses=losses,
            revenue_paise=int(_num("revenue_paise")),
            fees_paise=int(_num("fees_paise")),
            profit_paise=profit,
            profit_per_hour_paise=int(profit_per_hour),
            failure_rate=failure_rate,
            notes=str(run_summary.get("notes") or ""),
        )
        session.add(run)
        session.flush()
        log.info(
            "strategy run recorded",
            extra={"strategy_id": id, "run_id": run.id, "profit_paise": profit},
        )
        return run

    def performance_summary(self, id: int, session=None) -> dict[str, Any]:
        """Aggregate every recorded run: profit, average profit/hour, win
        rate (wins / (wins + losses)), and run count."""
        if session is None:
            with get_session() as s:
                return self.performance_summary(id, session=s)
        self.get(id, session=session)  # raises when the strategy is missing
        runs = list(
            session.query(StrategyRun)
            .filter(StrategyRun.strategy_id == id)
            .order_by(StrategyRun.id.asc())
        )
        wins = sum(r.wins for r in runs)
        losses = sum(r.losses for r in runs)
        outcomes = wins + losses
        pphs = [r.profit_per_hour_paise for r in runs]
        return {
            "strategy_id": id,
            "run_count": len(runs),
            "total_profit_paise": sum(r.profit_paise for r in runs),
            "total_revenue_paise": sum(r.revenue_paise for r in runs),
            "total_fees_paise": sum(r.fees_paise for r in runs),
            "total_time_hours": round(sum(r.time_hours for r in runs), 4),
            "avg_profit_per_hour_paise": (round(sum(pphs) / len(pphs)) if pphs else 0),
            "win_rate": (round(wins / outcomes, 4) if outcomes else 0.0),
            "wins": wins,
            "losses": losses,
        }

    def best_strategy_by_evidence(self, session=None) -> Optional[Strategy]:
        """Highest-accumulated-profit-per-hour ACTIVE strategy, else None.

        Evidence is recorded runs only — never LLM opinion, never the newest
        proposal. A strategy without runs has no evidence and cannot win.
        """
        if session is None:
            with get_session() as s:
                return self.best_strategy_by_evidence(session=s)
        active = list(session.query(Strategy).filter(Strategy.status == "ACTIVE"))
        best: Optional[Strategy] = None
        best_score = 0
        for row in active:
            runs = list(
                session.query(StrategyRun).filter(StrategyRun.strategy_id == row.id)
            )
            score = sum(r.profit_per_hour_paise for r in runs)
            if runs and score > best_score:
                best, best_score = row, score
        return best

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_strategies(
        self, status: Optional[str] = None, session=None
    ) -> list[Strategy]:
        """All strategies (optionally filtered), newest first."""
        if session is None:
            with get_session() as s:
                return self.list_strategies(status=status, session=s)
        q = session.query(Strategy)
        if status is not None:
            q = q.filter(Strategy.status == status)
        return q.order_by(Strategy.id.desc()).all()

    def get(self, id: int, session=None) -> Strategy:
        """Fetch one strategy; raises ValueError when missing."""
        if session is None:
            with get_session() as s:
                return self.get(id, session=s)
        row = session.get(Strategy, id)
        if row is None:
            raise ValueError(f"strategy {id} not found")
        return row
