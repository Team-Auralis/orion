"""ORION command-line interface — ``python -m orion.cli``.

Commands: start, stop, status, doctor, dry-run, opportunities, strategies,
experiments, ledger, approve, reject, confirm-payout, kill, logs, research.

Exit codes: 0 success, 1 user error, 2 runtime error.

All money is printed as ₹ (paise -> rupee) through :func:`fmt_paise`, the
single shared conversion helper.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
import traceback
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from orion.config import get_config
from orion.db import get_session, init_db
from orion.ledger import EventType, fmt_paise, get_ledger
from orion.log import get_logger
from orion.safety import ApprovalService
from orion.security import KillSwitchService
from orion.tools import ensure_workspace_dirs

log = get_logger("cli")

EXIT_OK = 0
EXIT_USER = 1
EXIT_RUNTIME = 2


# ---------------------------------------------------------------------------
# Argument parsing (usage errors are USER errors, exit 1 — not argparse's 2)
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse default exits with 2
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USER)


def _build_parser() -> _Parser:
    parser = _Parser(prog="orion", description="ORION economic agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="boot scheduler + worker and run until stopped")
    sub.add_parser("stop", help="signal a running `orion start` to exit")

    sub.add_parser("status", help="mode, model health, kill switch, DB, jobs, capital")
    sub.add_parser("doctor", help="environment diagnostics (PASS/WARN/FAIL)")
    sub.add_parser("dry-run", help="run the whole mock loop and print a summary")

    p = sub.add_parser("opportunities", help="list discovered opportunities")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("strategies", help="list strategies with evidence summary")
    sub.add_parser("experiments", help="list experiments")
    sub.add_parser("ledger", help="balance summary + recent ledger entries")

    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} an approval request")
        p.add_argument("id", type=int, help="approval request id")
    p = sub.add_parser(
        "confirm-payout",
        help="record a human-confirmed real payout from evidence (VERIFIED revenue)",
    )
    p.add_argument(
        "--amount-paise",
        type=int,
        help="amount in integer paise, e.g. 30000 = ₹300.00 (exactly one of --amount/--amount-paise)",
    )
    p.add_argument(
        "--amount",
        type=str,
        help="amount in rupees decimal, e.g. 300.00 = ₹300.00, converted internally "
        "(exactly one of --amount/--amount-paise)",
    )
    p.add_argument("--source", required=True, help="platform that paid out")
    p.add_argument(
        "--evidence",
        required=True,
        help="payout evidence reference: CSV path, transaction/payout id, platform "
        "record id — never account numbers",
    )
    p.add_argument(
        "--reference",
        default="",
        help="optional ledger reference (default: payout:<amount_paise>)",
    )
    p.add_argument("--confirmed-by", default="cli", help="who confirmed (default: cli)")
    sub.add_parser("kill", help="engage the global kill switch")
    p = sub.add_parser("logs", help="tail data/logs/orion.log")
    p.add_argument("--lines", type=int, default=40)

    p = sub.add_parser(
        "research", help="load one allowlisted URL and print trimmed page text"
    )
    p.add_argument("url", help="https URL on the browser allowlist (research only)")
    return parser


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_start(args) -> int:
    from orion.jobs import start_worker, stop_worker
    from orion.safety import ApprovalService

    cfg = get_config()
    stop_flag = _stop_flag()
    if stop_flag.exists():
        stop_flag.unlink()

    start_worker()
    cmd_status(args)
    print(
        f"\norion running — job worker poll {cfg.jobs.poll_seconds}s, "
        f"scheduler tick {cfg.scheduler.tick_seconds}s "
        f"(Ctrl+C or `orion stop` to halt)"
    )
    # ponytail: bare loop scheduler — swap for APScheduler jobs when the
    # periodic sweeps (scan/reconcile/memory) actually land.
    try:
        while not stop_flag.exists():
            time.sleep(cfg.scheduler.tick_seconds)
            try:
                ApprovalService().expire_stale()
            except Exception:  # scheduler must survive a bad sweep
                log.exception("scheduler sweep failed")
    except KeyboardInterrupt:
        print("\norion stopped (Ctrl+C)")
    finally:
        stop_worker()
        stop_flag.unlink(missing_ok=True)
    return EXIT_OK


def _stop_flag() -> Path:
    return get_config().data_dir / "STOP"


def cmd_stop(args) -> int:
    flag = _stop_flag()
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("stop requested", encoding="utf-8")
    print("stop signal written — a running `orion start` will exit cleanly")
    return EXIT_OK


def cmd_status(args) -> int:
    import orion.ledger as ledger
    from orion.jobs import JOB_STATUSES
    from orion.models import Job, SchemaVersion
    from orion.router import ModelRouter

    cfg = get_config()
    print(f"mode: {cfg.autonomy.default_mode}")

    health = ModelRouter().health()
    model_state = "OK" if health.available else "DEGRADED"
    print(f"model: {model_state} ({health.detail})")

    ks = KillSwitchService().status()
    print(
        f"kill switch: {'ACTIVE' if ks['active'] else 'inactive'}"
        + (f" ({ks['reason']})" if ks.get("reason") else "")
    )

    with get_session() as s:
        latest = s.query(SchemaVersion).order_by(SchemaVersion.id.desc()).first()
        summary = ledger.summary(s)
        jobs_by_status = {
            status: s.query(Job).filter(Job.status == status).count()
            for status in JOB_STATUSES
        }
    print(f"db: {get_config().db_path} (schema v{latest.version if latest else '?'})")
    running = jobs_by_status.get("RUNNING", 0)
    queued = jobs_by_status.get("QUEUED", 0)
    print(
        f"jobs: {running} running, {queued} queued "
        f"(success {jobs_by_status.get('SUCCESS', 0)}, "
        f"failed {jobs_by_status.get('FAILED', 0)})"
    )
    print(
        f"capital: {fmt_paise(summary['capital'])}"
        f"   available: {fmt_paise(summary['available_cash'])}"
        f"   spent: {fmt_paise(summary['spent'])}"
        f"   verified revenue: {fmt_paise(summary['verified_revenue'])}"
        f"   net profit: {fmt_paise(summary['net_profit'])}"
    )
    return EXIT_OK


def _check(level: str, name: str, detail: str, remediation: str = "") -> int:
    """Print one doctor line; returns 1 for FAIL."""
    print(f"{level:<4} {name}: {detail}")
    if level in ("WARN", "FAIL") and remediation:
        print(f"     → {remediation}")
    return 1 if level == "FAIL" else 0


def cmd_doctor(args) -> int:
    import httpx

    from orion.router import ModelRouter

    cfg = get_config()
    fails = 0

    info = sys.version_info
    if (info.major, info.minor) >= (3, 11):
        fails += _check(
            "PASS", "python", f"{info.major}.{info.minor}.{info.micro} (>= 3.11)"
        )
    else:
        fails += _check(
            "FAIL",
            "python",
            f"{info.major}.{info.minor}",
            "Python 3.11+ is required — install a newer interpreter",
        )

    node = shutil.which("node")
    if node:
        fails += _check("PASS", "node", f"found at {node}")
    else:
        fails += _check(
            "WARN",
            "node",
            "not found",
            "Install Node.js for frontend/build tooling (optional for the core agent)",
        )

    model = cfg.model_roles.role("orchestrator").model
    if model:
        fails += _check("PASS", "model", f"configured ({model})")
    else:
        fails += _check(
            "WARN", "model", "no model configured", "set config/model_roles.yaml"
        )

    health = ModelRouter().health()
    if health.available:
        detail = f"{health.detail} (latency {health.latency_ms}ms)"
        fails += _check("PASS", "ollama", detail)
    else:
        fails += _check(
            "WARN",
            "ollama",
            health.detail,
            "Install/start Ollama (https://ollama.com) — ORION runs DEGRADED without it",
        )

    base_url = cfg.model_roles.role("orchestrator").base_url.rstrip("/")
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            fails += _check("PASS", "ollama network", f"reachable at {base_url}")
        else:
            fails += _check(
                "WARN", "ollama network", f"HTTP {resp.status_code} at {base_url}"
            )
    except Exception as exc:  # network errors collapse to a single WARN
        fails += _check(
            "WARN",
            "ollama network",
            f"{base_url}: {exc}",
            "no local model server — start `ollama serve` or set ORION_FORCE_NO_OLLAMA=1",
        )

    gpu = shutil.which("nvidia-smi")
    if gpu:
        try:
            out = subprocess.run(
                [gpu, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=3.0,
            ).stdout.strip()
            fails += _check("PASS", "gpu", out or "nvidia-smi present (no output)")
        except Exception as exc:  # noqa: BLE001
            fails += _check(
                "WARN", "gpu", f"nvidia-smi failed: {exc}", "best-effort check only"
            )
    else:
        fails += _check(
            "WARN",
            "gpu",
            "no nvidia-smi found (likely CPU-only)",
            "best-effort note — not a failure; small local models run fine on CPU",
        )

    if importlib.util.find_spec("playwright"):
        fails += _check("PASS", "playwright", "installed")
    else:
        fails += _check(
            "WARN",
            "playwright",
            "not installed",
            f"pip install playwright && playwright install chromium "
            f"(browser driver is currently '{get_config().policies.browser.driver}')",
        )

    try:
        init_db()
        with get_session() as s:
            from orion.models import SchemaVersion

            latest = s.query(SchemaVersion).order_by(SchemaVersion.id.desc()).first()
        version = latest.version if latest else "?"
        fails += _check(
            "PASS", "database", f"init ok, schema v{version} at {get_config().db_path}"
        )
    except Exception as exc:  # noqa: BLE001
        fails += _check(
            "FAIL",
            "database",
            f"init failed: {exc}",
            "check data-dir permissions; delete a corrupt data/orion.db to rebuild",
        )

    fs_ok = True
    for root, probe in (
        (get_config().data_dir, ".doctor-probe"),
        (get_config().data_dir / "logs", ".doctor-probe"),
    ):
        try:
            root.mkdir(parents=True, exist_ok=True)
            target = root / probe
            target.write_text("probe", encoding="utf-8")
            target.unlink()
        except Exception:  # noqa: BLE001
            fs_ok = False
            break
    if fs_ok:
        fails += _check("PASS", "filesystem", "data dir writable")
    else:
        fails += _check(
            "FAIL",
            "filesystem",
            "cannot write to data dir",
            "fix permissions on the data/ directory",
        )

    env = sorted(k for k in os.environ if k.startswith("ORION_"))
    if env:
        pairs = " ".join(f"{k}={os.environ[k]}" for k in env)
        fails += _check("PASS", "env", pairs)
    else:
        fails += _check("PASS", "env", "none set (using config/*.yaml defaults)")

    return EXIT_OK if fails == 0 else EXIT_USER


def cmd_dry_run(args) -> int:
    from orion import ledger
    from orion.connectors import MockConnector
    from orion.discovery import DiscoveryService
    from orion.scoring import OpportunityScorer
    from orion.strategy import StrategyService

    init_db()  # fresh checkouts have no schema yet; doctor did this before
    cfg = get_config()
    with get_session() as s:
        ledger.seed_capital(s, cfg.orion.starting_capital)

    discovery = DiscoveryService()
    scorer = OpportunityScorer()
    with get_session() as s:
        discovery.scan(s)
        for offer in MockConnector().catalog():
            scorer.score_opportunity_from_offer(offer, s)
        top = None
        for row in discovery.list_opportunities(session=s, status="SCORED"):
            if top is None or (row.score_0_100 or 0) > (top.score_0_100 or 0):
                top = row
    if top is None:
        print("error: no scoreable opportunity after scan", file=sys.stderr)
        return EXIT_USER

    with get_session() as s:
        discovery.submit_for_decision(top.id, session=s)
        req = ApprovalService().request(
            "spend",
            why="dry-run: top-scored opportunity",
            cost_paise=100,
            potential_revenue_paise=top.estimated_value_paise,
            risk_level="L2",
            proposed_payload={"opportunity_id": top.id},
            destination="dry-run",
            session=s,
        )

    strategies = StrategyService()
    strategy = strategies.propose(
        name="dry-run micro-service gigs",
        description="Simulated automated micro-service delivery sweeps",
        required_capital_paise=2000,
        required_skills=["python", "excel", "writing"],
        automation_level="semi",
        risk_level="L2",
        min_opportunity_score=40.0,
        max_spend_paise=500,
        allowed_risk_levels=["L0", "L1", "L2"],
    )
    activated = strategies.activate(strategy.id)
    if activated.status != "ACTIVE":
        from orion.strategy import _payload

        reasons = _payload(activated).get("activation_reasons", [])
        print("error: strategy would not activate:", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return EXIT_RUNTIME

    expense_paise = 100
    revenue_paise = 1500
    with get_session() as s:
        ledger.spend(
            s,
            expense_paise,
            destination="dry-run:mock-tooling",
            reference="dry_run_sim",
        )
        ledger.record_revenue(
            s,
            revenue_paise,
            source="mock_gig",
            reference=f"dry_run_rev_{top.id}",
            verification_method="dry-run-payout-mock",
            confidence=0.95,
        )
    strategies.record_run(
        strategy.id,
        {
            "capital_used_paise": expense_paise,
            "time_hours": 1.0,
            "opportunities_checked": 3,
            "responses": 2,
            "wins": 1,
            "losses": 0,
            "revenue_paise": revenue_paise,
            "fees_paise": 0,
            "profit_paise": revenue_paise - expense_paise,
            "notes": "dry-run simulated execution",
        },
    )
    summary = strategies.performance_summary(strategy.id)
    balance = None
    with get_session() as s:
        balance = ledger.summary(s)

    print("dry-run complete — one simulated cycle")
    print(f"  mode: {cfg.autonomy.default_mode}")
    print(
        f"  top opportunity: #{top.id} {top.name[:48]} "
        f"(score {top.score_0_100:.1f}, value {fmt_paise(top.estimated_value_paise)})"
    )
    print(f"  approval: #{req.id} decision={req.decision}")
    print(
        f"  strategy: {strategy.name} ({activated.status}) — "
        f"{summary['run_count']} run(s), profit {fmt_paise(summary['total_profit_paise'])}"
    )
    print(
        f"  run: revenue {fmt_paise(revenue_paise)} expense {fmt_paise(expense_paise)} "
        f"profit {fmt_paise(revenue_paise - expense_paise)}"
    )
    print(f"  capital: {fmt_paise(balance['capital'])}")
    print(f"  spent: {fmt_paise(balance['spent'])}")
    print(f"  verified revenue: {fmt_paise(balance['verified_revenue'])}")
    print(f"  net profit: {fmt_paise(balance['net_profit'])}")
    return EXIT_OK


def cmd_opportunities(args) -> int:
    from orion.discovery import DiscoveryService

    rows = DiscoveryService().list_opportunities(limit=args.limit)
    if not rows:
        print("no opportunities (try `orion dry-run`)")
        return EXIT_OK
    for row in rows:
        score = f"{row.score_0_100 or 0:.1f}"
        print(
            f"#{row.id:<4} [{row.status:<9}] score={score:<5} "
            f"value={fmt_paise(row.estimated_value_paise):>12}  {row.name[:50]}"
        )
    return EXIT_OK


def cmd_strategies(args) -> int:
    from orion.strategy import StrategyService

    service = StrategyService()
    for row in service.list_strategies():
        summary = service.performance_summary(row.id)
        print(
            f"#{row.id:<3} [{row.status:<8}] runs={summary['run_count']} "
            f"profit={fmt_paise(summary['total_profit_paise'])} "
            f"pph_avg={fmt_paise(summary['avg_profit_per_hour_paise'])}  {row.name[:50]}"
        )
    return EXIT_OK


def cmd_experiments(args) -> int:
    from orion.experiments import ExperimentService

    service = ExperimentService()
    for row in service.list_experiments():
        suffix = row.name[:60]
        print(f"#{row.id:<3} [{row.status:<9}] {suffix}")
    return EXIT_OK


def cmd_ledger(args) -> int:
    from orion import ledger

    with get_session() as s:
        summary = ledger.summary(s)
        entries = get_ledger(s, limit=10)
    print("balance:")
    print(
        f"  capital: {fmt_paise(summary['capital'])}   "
        f"available: {fmt_paise(summary['available_cash'])}   "
        f"reserved: {fmt_paise(summary['reserved_cash'])}"
    )
    print(
        f"  spent: {fmt_paise(summary['spent'])}   "
        f"verified revenue: {fmt_paise(summary['verified_revenue'])}   "
        f"pending revenue: {fmt_paise(summary['pending_revenue'])}"
    )
    print(
        f"  fees: {fmt_paise(summary['fees'])}   refunds: {fmt_paise(summary['refunds'])}   "
        f"net profit: {fmt_paise(summary['net_profit'])}"
    )
    print("recent entries:")
    for e in entries:
        print(
            f"  #{e.id:<4} {e.type:<16} {fmt_paise(e.amount_paise):>12} "
            f"({e.status}) {e.destination or e.source} @ {e.created_at[:19]}"
        )
    return EXIT_OK


def _approval_id(args) -> int:
    if args.id <= 0:
        raise ValueError(f"invalid approval id {args.id}")
    return args.id


def cmd_approve(args) -> int:
    record = ApprovalService().approve(_approval_id(args), reason="approved via CLI")
    print(f"approval #{record.id} -> {record.status} (decision={record.decision})")
    return EXIT_OK


def cmd_reject(args) -> int:
    record = ApprovalService().reject(_approval_id(args), reason="rejected via CLI")
    print(f"approval #{record.id} -> {record.status} (decision={record.decision})")
    return EXIT_OK


def _payout_amount_paise(args) -> int:
    """Resolve exactly one of --amount-paise / --amount (rupees) to paise."""
    if (args.amount_paise is None) == (args.amount is None):
        raise ValueError(
            "pass exactly one of --amount-paise (integer paise) "
            "or --amount (rupees decimal)"
        )
    if args.amount_paise is not None:
        amount_paise = int(args.amount_paise)
    else:
        try:
            amount_paise = int(round(Decimal(args.amount) * 100))
        except (InvalidOperation, ValueError, TypeError, ArithmeticError):
            raise ValueError(
                f"--amount must be a rupees decimal (e.g. 300.00), got {args.amount!r}"
            ) from None
    if amount_paise <= 0:
        raise ValueError(f"amount must be positive, got {amount_paise} paise")
    return amount_paise


def cmd_confirm_payout(args) -> int:
    """Human-evidence revenue path: record VERIFIED income from a payout ref."""
    from orion import events, ledger

    amount_paise = _payout_amount_paise(args)
    evidence = (args.evidence or "").strip()
    if not evidence:
        raise ValueError(
            "--evidence is required — never verify a payout without evidence"
        )
    reference = args.reference or f"payout:{amount_paise}"

    print(f"confirm payout: {fmt_paise(amount_paise)} from {args.source}")
    print(f"  reference: {reference}")
    print(f"  evidence:  {evidence}")
    answer = input("Type CONFIRM to record this verified payout: ")
    if answer.strip() != "CONFIRM":
        print("aborted — nothing was recorded", file=sys.stderr)
        return EXIT_USER

    init_db()
    with get_session() as s:
        entry = ledger.record_verified_payout(
            s,
            amount_paise,
            source=args.source,
            reference=reference,
            evidence_ref=evidence,
            confirmed_by=args.confirmed_by,
        )
        summary = ledger.summary(s)
    events.publish(
        "ledger_write",
        agent="ledger",
        entity_id=entry.id,
        metadata={
            "type": entry.type,
            "status": entry.status,
            "amount_paise": entry.amount_paise,
            "evidence_ref": evidence,
        },
    )
    print(f"recorded #{entry.id} {entry.status} payout {fmt_paise(amount_paise)}")
    print("summary:")
    print(
        f"  capital: {fmt_paise(summary['capital'])}   "
        f"available: {fmt_paise(summary['available_cash'])}   "
        f"spent: {fmt_paise(summary['spent'])}"
    )
    print(
        f"  verified revenue: {fmt_paise(summary['verified_revenue'])}   "
        f"pending revenue: {fmt_paise(summary['pending_revenue'])}   "
        f"net profit: {fmt_paise(summary['net_profit'])}"
    )
    return EXIT_OK


def cmd_kill(args) -> int:
    result = KillSwitchService().kill(reason="manual kill via CLI")
    print(f"kill switch engaged: {result}")
    print(
        "hint: run `orion status` to confirm; disengage by deleting the row "
        "or via the API (no CLI override exists on purpose)"
    )
    return EXIT_OK


def cmd_logs(args) -> int:
    path = get_config().log_dir / "orion.log"
    if not path.exists():
        print(f"no log file yet at {path}")
        return EXIT_OK
    lines = path.read_text(encoding="utf-8").splitlines()[-args.lines :]
    print("\n".join(lines))
    return EXIT_OK


def cmd_research(args) -> int:
    """One-shot research read: final URL, status, screenshot, trimmed text.

    Research is L0 read-only: the page text is untrusted web content and is
    never merged anywhere except through the labeled boundary helper.
    """
    from orion.browser import BrowserController

    ctrl = BrowserController()
    result = ctrl.page(args.url)
    print("[UNTRUSTED WEB CONTENT — research only]")
    print(f"final url: {result.final_url}")
    print(f"status: {result.status_code}")
    print(f"screenshot: {result.screenshot_path or '(none)'}")
    if result.error is not None:
        print(f"error: {result.error}", file=sys.stderr)
        return EXIT_USER
    print("---")
    lines = [ln for ln in result.text.splitlines() if ln.strip()][:40]
    print("\n".join(lines) if lines else "(no page text)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_HANDLERS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "doctor": cmd_doctor,
    "dry-run": cmd_dry_run,
    "opportunities": cmd_opportunities,
    "strategies": cmd_strategies,
    "experiments": cmd_experiments,
    "ledger": cmd_ledger,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "confirm-payout": cmd_confirm_payout,
    "kill": cmd_kill,
    "logs": cmd_logs,
    "research": cmd_research,
}


def main(argv: Optional[list[str]] = None) -> int:
    # Windows consoles default to cp1252, which cannot encode ₹/→ — force UTF-8
    # so CLI output (rupee symbols, arrows) never crashes on stdio.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ensure_workspace_dirs()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return (
            int(code)
            if isinstance(code, int)
            else (EXIT_USER if code is not None else EXIT_OK)
        )

    try:
        return int(_HANDLERS[args.command](args) or EXIT_OK)
    except SystemExit as exc:
        return int(exc.code or EXIT_OK)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USER
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_RUNTIME
    except Exception:  # noqa: BLE001 — anything else is a runtime failure
        log.exception("cli runtime error", extra={"command": args.command})
        traceback.print_exc()
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
