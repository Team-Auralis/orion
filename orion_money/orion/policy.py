"""BudgetPolicy — hard money guardrails that no model output can change.

Policy is hard-coded logic. Model output can never change a policy decision.
This module is a pure function of (ledger state, configuration): the LLM
merely *proposes* a spend; :meth:`BudgetPolicy.can_spend` is the final
authorization gate and reads only the append-only ledger and the hard
guardrails from ``config/default.yaml``.

Exact total-loss formula (see :meth:`BudgetPolicy.can_spend`):

    total_loss = cumulative_spend - cumulative_verified_revenue

where ``cumulative_spend`` is the ledger balance field ``spent`` (gross SPEND
events net of REFUNDs, per the ledger invariant) and
``cumulative_verified_revenue`` is the ledger balance field
``verified_revenue`` (REVENUE events recognized as VERIFIED — PENDING /
ESTIMATED revenue never counts). A spend is denied when it would push

    total_loss + amount_paise > max_total_loss

All money values are INTEGER PAISE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from orion.config import get_config
from orion.db import get_session
from orion.ledger import EventType, LedgerEntry, get_balance
from orion.log import get_logger
from orion.models import utc_now_iso

log = get_logger("policy")

# Secret spending is hard-banned with NO operator flag — it can never be
# enabled, not even by editing config. (Borrowing/leverage/gambling carry
# explicit flags below; secret spending deliberately has none.)
SECRET_CATEGORY = "secret"

# Categories gated by an explicit risk flag in risk_guardrails. Under the
# delivered config (every flag ``false``) they are always denied; the flag is
# the operator's explicit escape hatch.
FLAGGED_BANNED_CATEGORIES = {
    "borrowing": "borrowing_allowed",
    "leverage": "leverage_allowed",
    "gambling": "gambling_allowed",
}


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of :meth:`BudgetPolicy.can_spend`.

    ``remaining_*`` fields report the headroom AFTER the proposed spend
    (i.e. proposed amount already subtracted); the standalone
    ``remaining_*_budget()`` methods report current headroom without any
    proposed spend.
    """

    allow: bool
    reasons: list[str] = field(default_factory=list)
    remaining_single: int = 0
    remaining_daily: int = 0
    remaining_loss: int = 0


def _normalize_day(when) -> str:
    """Return a ``YYYY-MM-DD`` day key (UTC) for filtering SPEND events."""
    if when is None:
        return utc_now_iso()[:10]
    if isinstance(when, date):  # datetime is a subclass of date
        return when.strftime("%Y-%m-%d")
    return str(when)[:10]


class BudgetPolicy:
    """Pure authorization engine over ledger state + configured guardrails."""

    def __init__(self, guardrails=None):
        cfg = get_config()
        self.guardrails = guardrails if guardrails is not None else cfg.risk_guardrails

    # ------------------------------------------------------------------
    # Ledger reads
    # ------------------------------------------------------------------

    def _totals(self, session, when=None) -> tuple[int, int]:
        """Return ``(today_spent, total_loss)``.

        ``today_spent``   — sum of all SPEND-type ledger events whose
                            ``created_at`` falls on ``when``'s day (default:
                            today, UTC).
        ``total_loss``    — cumulative spend minus cumulative verified
                            revenue, per the module docstring.
        """
        day = _normalize_day(when)
        today_spent = 0
        for entry in session.execute(
            select(LedgerEntry).where(LedgerEntry.type == EventType.SPEND)
        ).scalars():
            if entry.created_at[:10] == day:
                today_spent += entry.amount_paise
        balance = get_balance(session)
        total_loss = balance["spent"] - balance["verified_revenue"]
        return today_spent, total_loss

    # ------------------------------------------------------------------
    # Main gate
    # ------------------------------------------------------------------

    def can_spend(
        self,
        amount_paise: int,
        category: str,
        when=None,
        session=None,
    ) -> PolicyDecision:
        """Decide whether a proposed spend may proceed.

        Formula (exact, all paise):

            total_loss = cumulative_spend - cumulative_verified_revenue
            deny if amount_paise > max_single_spend
            deny if today_spent + amount_paise > max_daily_spend
            deny if total_loss + amount_paise > max_total_loss
            deny if category is borrowing/leverage/gambling (flag false) or
                 category is ``secret`` (hard ban, always)

        ``when`` overrides the day used for the daily cap (for tests /
        lookahead); ``session`` is an optional SQLAlchemy session (opened
        fresh when omitted).
        """
        if session is None:
            with get_session() as s:
                return self.can_spend(amount_paise, category, when=when, session=s)

        allow = True
        reasons: list[str] = []
        g = self.guardrails

        if not (
            isinstance(amount_paise, int)
            and not isinstance(amount_paise, bool)
            and amount_paise > 0
        ):
            return PolicyDecision(
                allow=False,
                reasons=[
                    f"invalid amount_paise: {amount_paise!r} (must be positive int)"
                ],
            )

        category = (category or "").lower()
        today_spent, total_loss = self._totals(session, when)

        if amount_paise > g.max_single_spend:
            allow = False
            reasons.append(
                f"single-spend cap exceeded: {amount_paise} > {g.max_single_spend}"
            )
        remaining_single = max(0, g.max_single_spend - amount_paise)

        if today_spent + amount_paise > g.max_daily_spend:
            allow = False
            reasons.append(
                f"daily-spend cap exceeded: {today_spent} + {amount_paise} > "
                f"{g.max_daily_spend}"
            )
        remaining_daily = max(0, g.max_daily_spend - today_spent - amount_paise)

        if total_loss + amount_paise > g.max_total_loss:
            allow = False
            reasons.append(
                f"total-loss cap exceeded: loss {total_loss} + {amount_paise} > "
                f"{g.max_total_loss}"
            )
        remaining_loss = max(0, g.max_total_loss - total_loss - amount_paise)

        if category == SECRET_CATEGORY:
            allow = False
            reasons.append("secret spending is hard-banned (no flag can enable it)")
        flag = FLAGGED_BANNED_CATEGORIES.get(category)
        if flag is not None:
            if not getattr(g, flag):
                allow = False
                reasons.append(f"category {category!r} is not allowed")
            else:
                reasons.append(f"category {category!r} explicitly allowed by config")

        if allow:
            reasons.append("budget ok")
        return PolicyDecision(
            allow=allow,
            reasons=reasons,
            remaining_single=remaining_single,
            remaining_daily=remaining_daily,
            remaining_loss=remaining_loss,
        )

    # ------------------------------------------------------------------
    # Budget reporters
    # ------------------------------------------------------------------

    def remaining_daily_budget(self, session=None, when=None) -> int:
        """Headroom left under the daily cap (no proposed spend subtracted)."""
        if session is None:
            with get_session() as s:
                return self.remaining_daily_budget(session=s, when=when)
        today_spent, _ = self._totals(session, when)
        return max(0, self.guardrails.max_daily_spend - today_spent)

    def remaining_loss_budget(self, session=None) -> int:
        """Headroom left under the total-loss cap (no proposed spend subtracted)."""
        if session is None:
            with get_session() as s:
                return self.remaining_loss_budget(session=s)
        _, total_loss = self._totals(session)
        return max(0, self.guardrails.max_total_loss - total_loss)

    def guardrail_summary(self, session=None) -> dict:
        """Caps, current usage, and remaining headroom — one reporting dict."""
        if session is None:
            with get_session() as s:
                return self.guardrail_summary(session=s)
        today_spent, total_loss = self._totals(session)
        g = self.guardrails
        return {
            "max_single_spend": g.max_single_spend,
            "max_daily_spend": g.max_daily_spend,
            "max_total_loss": g.max_total_loss,
            "borrowing_allowed": g.borrowing_allowed,
            "leverage_allowed": g.leverage_allowed,
            "gambling_allowed": g.gambling_allowed,
            "secret_spending_allowed": False,
            "spent_today": today_spent,
            "total_loss": total_loss,
            "remaining_single": g.max_single_spend,
            "remaining_daily": self.remaining_daily_budget(session=session),
            "remaining_loss": self.remaining_loss_budget(session=session),
        }
