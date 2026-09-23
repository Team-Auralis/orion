"""orion command-line interface — ``python -m orion.cli``.

commands: start, stop, status, doctor, dry-run, opportunities, strategies,
experiments, ledger, approve, reject, kill, logs.

exit codes: 0 success, 1 user error, 2 runtime error.

all money is printed as ₹ (paise -> rupee) through :func:`fmt_paise`, the
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
from pathlib import path
from typing import optional

from orion.config import get_config
from orion.db import get_session, init_db
from orion.ledger import eventtype, get_ledger, ledger_summary as _summary
from orion.log import get_logger
from orion.safety import approvalservice
from orion.security import killswitchservice
from orion.tools import ensure_workspace_dirs

log = get_logger("cli")

exit_ok = 0
exit_user = 1
exit_runtime = 2


def fmt_paise(paise: int) -> str:
    """the one place paise become ₹ — `fmt_paise(123456)` -> '₹1,234.56'."""
    amount = int(paise)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    return f"{sign}₹{absolute // 100:,}.{absolute % 100:02d}"


# ---------------------------------------------------------------------------
# argument parsing (usage errors are user errors, exit 1 — not argparse's 2)
# ---------------------------------------------------------------------------


class _parser(argparse.argumentparser):
    def error(self, message: str) -> none:  # argparse default exits with 2
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise systemexit(exit_user)


def _build_parser() -> _parser:
    parser = _parser(prog="orion", description="orion economic agent cli")
    sub = parser.add_subparsers(dest="command", required=true)

    sub.add_parser("start", help="boot scheduler + worker and run until stopped")
    sub.add_parser("stop", help="signal a running `orion start` to exit")

    sub.add_parser("status", help="mode, model health, kill switch, db, jobs, capital")
    sub.add_parser("doctor", help="environment diagnostics (pass/warn/fail)")
    sub.add_parser("dry-run", help="run the whole mock loop and print a summary")

    p = sub.add_parser("opportunities", help="list discovered opportunities")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("strategies", help="list strategies with evidence summary")
    sub.add_parser("experiments", help="list experiments")
    sub.add_parser("ledger", help="balance summary + recent ledger entries")

    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} an approval request")
        p.add_argument("id", type=int, help="approval request id")
    sub.add_parser("kill", help="engage the global kill switch")
    p = sub.add_parser("logs", help="tail data/logs/orion.log")
    p.add_argument("--lines", type=int, default=40)
    return parser


# ---------------------------------------------------------------------------
# command implementations
# ---------------------------------------------------------------------------


def cmd_start(args) -> int:
    from orion.jobs import start_worker, stop_worker
    from orion.safety import approvalservice

    cfg = get_config()
    stop_flag = _stop_flag()
    if stop_flag.exists():
        stop_flag.unlink()

    start_worker()
    cmd_status(args)
    print(
        f"\norion running — job worker poll {cfg.jobs.poll_seconds}s, "
        f"scheduler tick {cfg.scheduler.tick_seconds}s "
        f"(ctrl+c or `orion stop` to halt)"
    )
    # ponytail: bare loop scheduler — swap for apscheduler jobs when the
    # periodic sweeps (scan/reconcile/memory) actually land.
    try:
        while not stop_flag.exists():
            time.sleep(cfg.scheduler.tick_seconds)
            try:
                approvalservice().expire_stale()
            except exception:  # scheduler must survive a bad sweep
                log.exception("scheduler sweep failed")
    except keyboardinterrupt:
        print("\norion stopped (ctrl+c)")
    finally:
        stop_worker()
        stop_flag.unlink(missing_ok=true)
    return exit_ok


def _stop_flag() -> path:
    return get_config().data_dir / "stop"


def cmd_stop(args) -> int:
    flag = _stop_flag()
    flag.parent.mkdir(parents=true, exist_ok=true)
    flag.write_text("stop requested", encoding="utf-8")
    print("stop signal written — a running `orion start` will exit cleanly")
    return exit_ok


def cmd_status(args) -> int:
    import orion.ledger as ledger
    from orion.jobs import job_statuses
    from orion.models import job, schemaversion
    from orion.router import modelrouter

    cfg = get_config()
    print(f"mode: {cfg.autonomy.default_mode}")

    health = modelrouter().health()
    model_state = "ok" if health.available else "degraded"
    print(f"model: {model_state} ({health.detail})")

    ks = killswitchservice().status()
    print(
        f"kill switch: {'active' if ks['active'] else 'inactive'}"
        + (f" ({ks['reason']})" if ks.get("reason") else "")
    )

    with get_session() as s:
        latest = s.query(schemaversion).order_by(schemaversion.id.desc()).first()
        summary = ledger.summary(s)
        jobs_by_status = {
            status: s.query(job).filter(job.status == status).count()
            for status in job_statuses
        }
    print(f"db: {get_config().db_path} (schema v{latest.version if latest else '?'})")
    running = jobs_by_status.get("running", 0)
    queued = jobs_by_status.get("queued", 0)
    print(
        f"jobs: {running} running, {queued} queued "
        f"(success {jobs_by_status.get('success', 0)}, "
        f"failed {jobs_by_status.get('failed', 0)})"
    )
    print(
        f"capital: {fmt_paise(summary['capital'])}"
        f"   available: {fmt_paise(summary['available_cash'])}"
        f"   spent: {fmt_paise(summary['spent'])}"
        f"   verified revenue: {fmt_paise(summary['verified_revenue'])}"
        f"   net profit: {fmt_paise(summary['net_profit'])}"
    )
    return exit_ok


def _check(level: str, name: str, detail: str, remediation: str = "") -> int:
    """print one doctor line; returns 1 for fail."""
    print(f"{level:<4} {name}: {detail}")
    if level in ("warn", "fail") and remediation:
        print(f"     → {remediation}")
    return 1 if level == "fail" else 0


def cmd_doctor(args) -> int:
    import httpx

    from orion.router import modelrouter

    cfg = get_config()
    fails = 0

    info = sys.version_info
    if (info.major, info.minor) >= (3, 11):
        fails += _check(
            "pass", "python", f"{info.major}.{info.minor}.{info.micro} (>= 3.11)"
        )
    else:
        fails += _check(
            "fail",
            "python",
            f"{info.major}.{info.minor}",
            "python 3.11+ is required — install a newer interpreter",
        )

    node = shutil.which("node")
    if node:
        fails += _check("pass", "node", f"found at {node}")
    else:
        fails += _check(
            "warn",
            "node",
            "not found",
            "install node.js for frontend/build tooling (optional for the core agent)",
        )

    model = cfg.model_roles.role("orchestrator").model
    if model:
        fails += _check("pass", "model", f"configured ({model})")
    else:
        fails += _check(
            "warn", "model", "no model configured", "set config/model_roles.yaml"
        )

    health = modelrouter().health()
    if health.available:
        detail = f"{health.detail} (latency {health.latency_ms}ms)"
        fails += _check("pass", "ollama", detail)
    else:
        fails += _check(
            "warn",
            "ollama",
            health.detail,
            "install/start ollama (https://ollama.com) — orion runs degraded without it",
        )

    base_url = cfg.model_roles.role("orchestrator").base_url.rstrip("/")
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            fails += _check("pass", "ollama network", f"reachable at {base_url}")
        else:
            fails += _check(
                "warn", "ollama network", f"http {resp.status_code} at {base_url}"
            )
    except exception as exc:  # network errors collapse to a single warn
        fails += _check(
            "warn",
            "ollama network",
            f"{base_url}: {exc}",
            "no local model server — start `ollama serve` or set orion_force_no_ollama=1",
        )

    gpu = shutil.which("nvidia-smi")
    if gpu:
        try:
            out = subprocess.run(
                [gpu, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=true,
                text=true,
                timeout=3.0,
            ).stdout.strip()
            fails += _check("pass", "gpu", out or "nvidia-smi present (no output)")
        except exception as exc:  # noqa: ble001
            fails += _check(
                "warn", "gpu", f"nvidia-smi failed: {exc}", "best-effort check only"
            )
    else:
        fails += _check(
            "warn",
            "gpu",
            "no nvidia-smi found (likely cpu-only)",
            "best-effort note — not a failure; small local models run fine on cpu",
        )

    if importlib.util.find_spec("playwright"):
        fails += _check("pass", "playwright", "installed")
    else:
        fails += _check(
            "warn",
            "playwright",
            "not installed",
            f"pip install playwright && playwright install chromium "
            f"(browser driver is currently '{get_config().policies.browser.driver}')",
        )

    try:
        init_db()
        with get_session() as s:
            from orion.models import schemaversion

            latest = s.query(schemaversion).order_by(schemaversion.id.desc()).first()
        version = latest.version if latest else "?"
        fails += _check(
            "pass", "database", f"init ok, schema v{version} at {get_config().db_path}"
        )
    except exception as exc:  # noqa: ble001
        fails += _check(
            "fail",
            "database",
            f"init failed: {exc}",
            "check data-dir permissions; delete a corrupt data/orion.db to rebuild",
        )

    fs_ok = true
    for root, probe in (
        (get_config().data_dir, ".doctor-probe"),
        (get_config().data_dir / "logs", ".doctor-probe"),
    ):
        try:
            root.mkdir(parents=true, exist_ok=true)
            target = root / probe
            target.write_text("probe", encoding="utf-8")
            target.unlink()
        except exception:  # noqa: ble001
            fs_ok = false
            break
    if fs_ok:
        fails += _check("pass", "filesystem", "data dir writable")
    else:
        fails += _check(
            "fail",
            "filesystem",
            "cannot write to data dir",
            "fix permissions on the data/ directory",
        )

    env = sorted(k for k in os.environ if k.startswith("orion_"))
    if env:
        pairs = " ".join(f"{k}={os.environ[k]}" for k in env)
        fails += _check("pass", "env", pairs)
    else:
        fails += _check("pass", "env", "none set (using config/*.yaml defaults)")

    return exit_ok if fails == 0 else exit_user


def cmd_dry_run(args) -> int:
    from orion import ledger
    from orion.connectors import mockconnector
    from orion.discovery import discoveryservice
    from orion.scoring import opportunityscorer
    from orion.strategy import strategyservice

    cfg = get_config()
    with get_session() as s:
        ledger.seed_capital(s, cfg.orion.starting_capital)

    discovery = discoveryservice()
    scorer = opportunityscorer()
    with get_session() as s:
        discovery.scan(s)
        for offer in mockconnector().catalog():
            scorer.score_opportunity_from_offer(offer, s)
        top = none
        for row in discovery.list_opportunities(session=s, status="scored"):
            if top is none or (row.score_0_100 or 0) > (top.score_0_100 or 0):
                top = row
    if top is none:
        print("error: no scoreable opportunity after scan", file=sys.stderr)
        return exit_user

    with get_session() as s:
        discovery.submit_for_decision(top.id, session=s)
        req = approvalservice().request(
            "spend",
            why="dry-run: top-scored opportunity",
            cost_paise=100,
            potential_revenue_paise=top.estimated_value_paise,
            risk_level="l2",
            proposed_payload={"opportunity_id": top.id},
            destination="dry-run",
            session=s,
        )

    strategies = strategyservice()
    strategy = strategies.propose(
        name="dry-run micro-service gigs",
        description="simulated automated micro-service delivery sweeps",
        required_capital_paise=2000,
        required_skills=["python", "excel", "writing"],
        automation_level="semi",
        risk_level="l2",
        min_opportunity_score=40.0,
        max_spend_paise=500,
        allowed_risk_levels=["l0", "l1", "l2"],
    )
    activated = strategies.activate(strategy.id)
    if activated.status != "active":
        from orion.strategy import _payload

        reasons = _payload(activated).get("activation_reasons", [])
        print("error: strategy would not activate:", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return exit_runtime

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
    balance = none
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
    return exit_ok


def cmd_opportunities(args) -> int:
    from orion.discovery import discoveryservice

    rows = discoveryservice().list_opportunities(limit=args.limit)
    if not rows:
        print("no opportunities (try `orion dry-run`)")
        return exit_ok
    for row in rows:
        score = f"{row.score_0_100 or 0:.1f}"
        print(
            f"#{row.id:<4} [{row.status:<9}] score={score:<5} "
            f"value={fmt_paise(row.estimated_value_paise):>12}  {row.name[:50]}"
        )
    return exit_ok


def cmd_strategies(args) -> int:
    from orion.strategy import strategyservice

    service = strategyservice()
    for row in service.list_strategies():
        summary = service.performance_summary(row.id)
        print(
            f"#{row.id:<3} [{row.status:<8}] runs={summary['run_count']} "
            f"profit={fmt_paise(summary['total_profit_paise'])} "
            f"pph_avg={fmt_paise(summary['avg_profit_per_hour_paise'])}  {row.name[:50]}"
        )
    return exit_ok


def cmd_experiments(args) -> int:
    from orion.experiments import experimentservice

    service = experimentservice()
    for row in service.list_experiments():
        suffix = row.name[:60]
        print(f"#{row.id:<3} [{row.status:<9}] {suffix}")
    return exit_ok


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
    return exit_ok


def _approval_id(args) -> int:
    if args.id <= 0:
        raise valueerror(f"invalid approval id {args.id}")
    return args.id


def cmd_approve(args) -> int:
    record = approvalservice().approve(_approval_id(args), reason="approved via cli")
    print(f"approval #{record.id} -> {record.status} (decision={record.decision})")
    return exit_ok


def cmd_reject(args) -> int:
    record = approvalservice().reject(_approval_id(args), reason="rejected via cli")
    print(f"approval #{record.id} -> {record.status} (decision={record.decision})")
    return exit_ok


def cmd_kill(args) -> int:
    result = killswitchservice().kill(reason="manual kill via cli")
    print(f"kill switch engaged: {result}")
    print(
        "hint: run `orion status` to confirm; disengage by deleting the row "
        "or via the api (no cli override exists on purpose)"
    )
    return exit_ok


def cmd_logs(args) -> int:
    path = get_config().log_dir / "orion.log"
    if not path.exists():
        print(f"no log file yet at {path}")
        return exit_ok
    lines = path.read_text(encoding="utf-8").splitlines()[-args.lines :]
    print("\n".join(lines))
    return exit_ok


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

_handlers = {
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
    "kill": cmd_kill,
    "logs": cmd_logs,
}


def main(argv: optional[list[str]] = none) -> int:
    ensure_workspace_dirs()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except systemexit as exc:
        code = exc.code
        return (
            int(code)
            if isinstance(code, int)
            else (exit_user if code is not none else exit_ok)
        )

    try:
        return int(_handlers[args.command](args) or exit_ok)
    except systemexit as exc:
        return int(exc.code or exit_ok)
    except valueerror as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exit_user
    except keyboardinterrupt:
        print("\ninterrupted", file=sys.stderr)
        return exit_runtime
    except exception:  # noqa: ble001 — anything else is a runtime failure
        log.exception("cli runtime error", extra={"command": args.command})
        traceback.print_exc()
        return exit_runtime


if __name__ == "__main__":
    sys.exit(main())
