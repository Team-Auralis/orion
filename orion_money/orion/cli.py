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
import json
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

    # gumroad subcommands
    gum = sub.add_parser("gumroad", help="Gumroad connector commands")
    gum_sub = gum.add_subparsers(dest="gumroad_command", required=True)

    gum_sub.add_parser("test", help="test Gumroad API connection")

    p = gum_sub.add_parser("publish", help="publish a product to Gumroad")
    p.add_argument("product_id", help="product ID to publish")

    p = gum_sub.add_parser("sales", help="list Gumroad sales")
    p.add_argument("--after", help="filter sales after this date (ISO format)")
    p.add_argument("--before", help="filter sales before this date (ISO format)")
    p.add_argument("--product-id", help="filter by product ID")

    gum_sub.add_parser("payouts", help="list Gumroad payouts")

    # product subcommands
    prod = sub.add_parser("product", help="product generation commands")
    prod_sub = prod.add_subparsers(dest="product_command", required=True)

    p = prod_sub.add_parser("generate", help="generate a new digital product")
    p.add_argument(
        "--kind",
        required=True,
        choices=["template", "notes", "tool", "asset_pack", "checklist", "starter_kit"],
    )
    p.add_argument("--title", required=True, help="product title")
    p.add_argument("--description", required=True, help="product description")
    p.add_argument("--audience", required=True, help="target audience")
    p.add_argument("--features", default="", help="comma-separated features")
    p.add_argument("--hours", type=float, default=1.0, help="estimated hours to create")
    p.add_argument("--difficulty", choices=["easy", "medium", "hard"], default="medium")
    p.add_argument(
        "--tier", choices=["low", "medium", "high", "premium"], help="price tier"
    )
    p.add_argument("--price-cents", type=int, help="explicit price in USD cents")
    p.add_argument("--tags", default="", help="comma-separated tags")
    p.add_argument("--license", choices=["MIT", "CC0", "custom"], default="MIT")

    p = prod_sub.add_parser("list", help="list generated products")
    p.add_argument("--status", help="filter by status")

    p = prod_sub.add_parser("show", help="show product details")
    p.add_argument("id", help="product ID")

    v = sub.add_parser(
        "vault",
        help="credential vault: set / list / get / delete / health",
        description="Credential vault (orion.secrets.SecretVault). Secret "
        "values are never printed: get/list show a masked (•••last4) form only.",
    )
    vsub = v.add_subparsers(dest="vault_command", required=True)
    p = vsub.add_parser(
        "set",
        help="store a secret (value argument or hidden stdin paste)",
        description="Store a secret. Pass the value as an argument OR omit it "
        "and paste the value on stdin (hidden when the terminal allows it) — "
        "the stdin form avoids shell history. The stored value is never printed.",
    )
    p.add_argument("name", help="secret name, e.g. gumroad_token")
    p.add_argument(
        "value",
        nargs="?",
        default=None,
        help="secret value (omit to paste on stdin)",
    )
    p = vsub.add_parser(
        "list",
        help="list stored secret names (masked values)",
        description="List stored secret names with their masked (last-4) values.",
    )
    p = vsub.add_parser(
        "get",
        help="print the masked value for one secret",
        description="Print the masked value (•••last4) for one secret — never "
        "the raw value. A missing secret prints a clear message and exits 0.",
    )
    p.add_argument("name", help="secret name")
    p = vsub.add_parser(
        "delete",
        help="delete a stored secret",
        description="Delete a stored secret (missing names are a no-op).",
    )
    p.add_argument("name", help="secret name")
    p = vsub.add_parser(
        "health",
        help="vault backend + writable check",
        description="Report the vault backend and whether it is reachable/writable.",
    )
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
# Gumroad CLI commands
# ---------------------------------------------------------------------------


async def _run_gumroad(connector, operation, *args, **kwargs):
    """Run one connector operation and close it on the same event loop."""
    try:
        return await operation(*args, **kwargs)
    finally:
        await connector.close()


def cmd_gumroad_test(args) -> int:
    """Test Gumroad API connection."""
    from orion.connectors.gumroad import GumroadConnector
    import asyncio

    connector = GumroadConnector()
    ok = asyncio.run(_run_gumroad(connector, connector.test_connection))

    if ok:
        print("Gumroad connection: OK")
        return EXIT_OK
    else:
        print("Gumroad connection: FAILED")
        return EXIT_RUNTIME


def cmd_gumroad_publish(args) -> int:
    """Publish a product to Gumroad (requests approval, then executes)."""
    from orion.connectors.gumroad import GumroadConnector
    from orion.products import get_product
    from orion.safety import ApprovalService
    import asyncio

    product = get_product(args.product_id)
    if not product:
        print(f"product {args.product_id} not found", file=sys.stderr)
        return EXIT_USER

    if product.status not in ("READY_TO_PUBLISH", "QUALITY_FAILED"):
        print(
            f"product {args.product_id} not ready to publish (status={product.status})",
            file=sys.stderr,
        )
        return EXIT_USER

    # Request approval
    approval = ApprovalService().request(
        action="publish",
        why=f"Publish product {product.id} to Gumroad",
        cost_paise=0,
        potential_revenue_paise=product.price_usd_cents * 100,
        risk_level="L2",
        proposed_payload={"product_id": product.id, "platform": "gumroad"},
        destination="gumroad",
        correlation_id=product.id,
    )

    print(f"Approval requested: #{approval.id} (status={approval.status})")
    if approval.status == "PENDING":
        print(
            f"Run `orion approve {approval.id}` to approve, then `orion gumroad publish {args.product_id}` again to execute"
        )
        return EXIT_OK

    # Dry-run auto-approved - execute
    connector = GumroadConnector()
    result = asyncio.run(_run_gumroad(connector, connector.create_product, product))

    if result.success:
        from orion.products import update_status

        update_status(product.id, "PUBLISHED")
        print(f"Published via {result.method}")
        if result.product_id:
            print(f"  Gumroad product ID: {result.product_id}")
        if result.url:
            print(f"  URL: {result.url}")
        if result.draft_bundle_path:
            print(f"  Draft bundle: {result.draft_bundle_path}")
        return EXIT_OK
    else:
        print(f"Publish failed: {result.error}")
        if result.draft_bundle_path:
            print(f"Draft bundle created at: {result.draft_bundle_path}")
        return EXIT_RUNTIME


def cmd_gumroad_sales(args) -> int:
    """List Gumroad sales."""
    from orion.connectors.gumroad import GumroadConnector
    from orion.ledger import fmt_paise
    import asyncio

    connector = GumroadConnector()
    sales = asyncio.run(
        _run_gumroad(
            connector,
            connector.list_sales,
            after=args.after,
            before=args.before,
            product_id=args.product_id,
        )
    )

    if not sales:
        print("no sales")
        return EXIT_OK

    print(
        f"{'ID':<20} {'Product':<15} {'Amount':>10} {'Currency':<5} {'Email':<30} {'Date':<20} {'Payout':<15}"
    )
    print("-" * 120)
    for s in sales:
        amount_str = f"${s.price_usd_cents / 100:.2f}"
        date_str = s.created_at[:19] if s.created_at else ""
        payout_str = s.payout_id or ""
        email_str = (s.email[:28] + "..") if len(s.email) > 30 else s.email
        print(
            f"{s.id:<20} {s.product_id:<15} {amount_str:>10} {s.currency:<5} {email_str:<30} {date_str:<20} {payout_str:<15}"
        )
    return EXIT_OK


def cmd_gumroad_payouts(args) -> int:
    """List Gumroad payouts."""
    from orion.connectors.gumroad import GumroadConnector
    import asyncio

    connector = GumroadConnector()
    payouts = asyncio.run(_run_gumroad(connector, connector.list_payouts))

    if not payouts:
        print("no payouts")
        return EXIT_OK

    print(
        f"{'ID':<20} {'Amount':>12} {'Currency':<5} {'Status':<12} {'Arrived':<20} {'Paid Out':<20}"
    )
    print("-" * 95)
    for p in payouts:
        amount_str = f"${p.amount_usd_cents / 100:.2f}"
        arrived_str = p.arrived_at[:19] if p.arrived_at else ""
        paid_str = p.paid_out_at[:19] if p.paid_out_at else ""
        print(
            f"{p.id:<20} {amount_str:>12} {p.currency:<5} {p.status:<12} {arrived_str:<20} {paid_str:<20}"
        )
    return EXIT_OK


_GUMROAD_HANDLERS = {
    "test": cmd_gumroad_test,
    "publish": cmd_gumroad_publish,
    "sales": cmd_gumroad_sales,
    "payouts": cmd_gumroad_payouts,
}


def cmd_gumroad(args) -> int:
    return _GUMROAD_HANDLERS[args.gumroad_command](args)


def cmd_product_generate(args) -> int:
    """Generate a new digital product from spec."""
    from orion.products import ProductSpec, generate_product

    features = (
        [f.strip() for f in args.features.split(",") if f.strip()]
        if args.features
        else []
    )
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    spec = ProductSpec(
        kind=args.kind,
        title=args.title,
        description=args.description,
        target_audience=args.audience,
        features=features,
        estimated_hours_to_create=args.hours,
        difficulty=args.difficulty,
        price_tier=args.tier,
        price_usd_cents=args.price_cents,
        tags=tags,
        license=args.license,
    )

    try:
        product = generate_product(spec)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER
    except Exception as e:
        print(f"error: generation failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME

    print(f"product_id: {product.id}")
    print(f"path: {product.content_path}")
    print(f"status: {product.status}")
    print(f"quality_passed: {product.quality_passed}")
    print(f"price_usd_cents: {product.price_usd_cents}")
    return EXIT_OK


def cmd_product_list(args) -> int:
    """List generated products."""
    from orion.products import list_products

    products = list_products(status=args.status)
    if not products:
        print("no products")
        return EXIT_OK

    for p in products:
        size_kb = p.size_bytes / 1024
        print(
            f"#{p.id:<12} [{p.status:<16}] ${p.price_usd_cents / 100:.2f}  {size_kb:.1f}KB  {json.loads(p.spec_json).get('title', 'untitled')[:50]}"
        )
    return EXIT_OK


def cmd_product_show(args) -> int:
    """Show product details."""
    from orion.products import get_product
    import json

    product = get_product(args.id)
    if not product:
        print(f"product {args.id} not found", file=sys.stderr)
        return EXIT_USER

    spec = json.loads(product.spec_json)
    meta = json.loads(product.metadata_json) if product.metadata_json else {}

    print(f"id:          {product.id}")
    print(f"title:       {spec.get('title')}")
    print(f"kind:        {spec.get('kind')}")
    print(f"audience:    {spec.get('target_audience')}")
    print(f"difficulty:  {spec.get('difficulty')}")
    print(f"hours:       {spec.get('estimated_hours_to_create')}")
    print(f"features:    {', '.join(spec.get('features', [])) or 'none'}")
    print(f"tags:        {', '.join(spec.get('tags', [])) or 'none'}")
    print(f"license:     {spec.get('license')}")
    print(
        f"price:       ${product.price_usd_cents / 100:.2f} ({product.price_usd_cents} cents)"
    )
    print(f"status:      {product.status}")
    print(f"quality:     {'passed' if product.quality_passed else 'failed'}")
    print(f"size:        {product.size_bytes} bytes")
    print(f"hash:        {product.file_hash[:16]}...")
    print(f"path:        {product.content_path}")
    print(f"created:     {product.created_at}")
    if meta.get("quality_reasons"):
        print(f"quality issues: {', '.join(meta['quality_reasons'])}")
    if meta.get("degraded_reason"):
        print(f"degraded:      {meta['degraded_reason']}")
    return EXIT_OK


def _vault_value(args) -> str:
    """Resolve the secret for ``vault set``: explicit arg, else stdin paste."""
    if args.value is not None:
        value = args.value
    else:
        from getpass import getpass

        print("Paste value (input hidden if available):", end="", flush=True)
        value = getpass("")
    value = value.strip()
    if not value:
        raise ValueError(f"no value provided for {args.name!r}")
    return value


def cmd_vault_set(args) -> int:
    """Store a secret — the value is never printed."""
    from orion.secrets import get_vault

    vault = get_vault()
    value = _vault_value(args)  # may raise ValueError (caught -> exit 1)
    vault.set(args.name, value)
    print(f"stored {args.name} in vault (backend={vault.backend})")
    return EXIT_OK


def cmd_vault_list(args) -> int:
    from orion.secrets import get_vault

    vault = get_vault()
    names = vault.list_names()
    if not names:
        print(f"vault is empty (backend={vault.backend})")
        return EXIT_OK
    print(f"stored secrets (backend={vault.backend}):")
    for name in names:
        print(f"  {name:<24} {vault.mask(name)}")
    return EXIT_OK


def cmd_vault_get(args) -> int:
    from orion.secrets import get_vault

    vault = get_vault()
    masked = vault.mask(args.name)
    if not masked:
        print(f"{args.name}: not in vault (mask unknown)")
        return EXIT_OK
    print(masked)
    return EXIT_OK


def cmd_vault_delete(args) -> int:
    from orion.secrets import get_vault

    vault = get_vault()
    if not vault.has(args.name):
        print(f"{args.name}: not in vault — nothing to delete")
        return EXIT_OK
    vault.delete(args.name)
    print(f"deleted {args.name} from vault (backend={vault.backend})")
    return EXIT_OK


def cmd_vault_health(args) -> int:
    from orion.secrets import get_vault

    health = get_vault().health()
    print(f"backend={health['backend']} ok={health['ok']} detail={health['detail']}")
    return EXIT_OK if health["ok"] else EXIT_USER


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_VAULT_HANDLERS = {
    "set": cmd_vault_set,
    "list": cmd_vault_list,
    "get": cmd_vault_get,
    "delete": cmd_vault_delete,
    "health": cmd_vault_health,
}


def cmd_vault(args) -> int:
    return _VAULT_HANDLERS[args.vault_command](args)


_PRODUCT_HANDLERS = {
    "generate": cmd_product_generate,
    "list": cmd_product_list,
    "show": cmd_product_show,
}


def cmd_product(args) -> int:
    return _PRODUCT_HANDLERS[args.product_command](args)


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
    "gumroad": cmd_gumroad,
    "vault": cmd_vault,
    "product": cmd_product,
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
    init_db()  # ensure schema is up to date
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
