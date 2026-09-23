"""Tool registry + secure command runner.

Registry
--------
:data:`_REGISTRY` maps every tool the system declares it has to a
:class:`ToolSpec` (name, description, input/output JSON schemas, risk level,
approval requirement, handler). Tools that map onto existing subsystems are
wired to real handlers (ledger, discovery, approval, decimal-safe math,
SELECT-only SQL, workspace-confined file I/O); the rest raise
:class:`NotImplementedError` with the exact string "not implemented in this
build" — success is never faked.

CommandRunner
-------------
Secure subprocess execution: an ALLOWLIST of safe baseline commands, a
BLOCKLIST of destructive patterns, no shell, a hard runtime cap, cwd
confined to workspace/allowlisted roots, full stdout/stderr captured, logged
to the audit log through a redaction pass, and every invocation returns a
:class:`CommandResult`.
"""

from __future__ import annotations

import ast
import json
import re
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from orion.config import PROJECT_ROOT, get_config
from orion.db import get_session
from orion.discovery import DiscoveryService
from orion.ledger import EventType, record_revenue, spend
from orion.log import get_logger
from orion.models import Opportunity
from orion.safety import ApprovalService
from orion.security import redact_secrets

log = get_logger("tools")

NOT_IMPLEMENTED = "not implemented in this build"

WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
WORKSPACE_SUBDIRS = (
    "products",
    "deliverables",
    "downloads",
    "generated",
    "screenshots",
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool: schemas are JSON-schema dicts; ``handler`` is
    ``fn(args: dict) -> dict`` (JSON-serializable result)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str  # L0..L4 matching config/policies.yaml levels
    requires_approval: bool
    handler: Callable[[dict[str, Any]], dict[str, Any]]


_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> ToolSpec:
    """Register (or replace) a tool spec by name."""
    _REGISTRY[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec:
    """Resolve a tool by name; raises ValueError for unknown tools."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown tool {name!r}") from None


def list_tools() -> list[ToolSpec]:
    """All registered tools, in declaration order."""
    return list(_REGISTRY.values())


def _unbuilt(name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A handler for a declared-but-unbuilt tool: honest NotImplementedError."""

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(NOT_IMPLEMENTED)

    handler.__name__ = f"{name}_not_implemented"
    return handler


# ---------------------------------------------------------------------------
# Wired handlers
# ---------------------------------------------------------------------------


def _calculate(args: dict[str, Any]) -> dict[str, Any]:
    """Decimal-safe arithmetic on a restricted expression language."""
    expr = str(args.get("expression") or "")
    result = _safe_eval_decimal(expr)
    return {"expression": expr, "result": str(result)}


def _safe_eval_decimal(expr: str) -> Decimal:
    """Evaluate + - * / // % ** on decimal literals via the ast (no eval,
    no builtins, no attribute access)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {exc}") from exc

    bin_ops = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
    }

    def ev(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"unsupported constant {value!r}")
            return Decimal(str(value))
        if isinstance(node, ast.BinOp):
            op = bin_ops.get(type(node.op))
            if op is None:
                raise ValueError(f"unsupported operator {type(node.op).__name__}")
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow):
                if right != int(right) or abs(right) > 64:  # DoS guard
                    raise ValueError("power must be an integer in [-64, 64]")
                right = int(right)
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.UAdd):
                return +ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -ev(node.operand)
            raise ValueError("unsupported unary operator")
        raise ValueError(f"unsupported expression element {type(node).__name__}")

    try:
        return ev(tree)
    except InvalidOperation as exc:
        raise ValueError(f"arithmetic error: {exc}") from exc


def _query_database(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only SQL against the ORION database. SELECT-only, enforced by
    both a statement prefix check and the sqlite3 authorizer; never writes."""
    sql = str(args.get("sql") or "").strip()
    if not sql:
        raise ValueError("query_database requires a 'sql' argument")
    if re.search(r";", sql.rstrip(";").rstrip()):
        raise ValueError("only a single statement is allowed")
    head = sql.lstrip()[:16].split(None, 1)[0].upper() if sql.lstrip() else ""
    if head not in {"SELECT", "WITH"}:
        raise ValueError(f"only SELECT/WITH queries are allowed, got {head!r}")

    conn = sqlite3.connect(str(get_config().db_path))
    try:
        conn.set_authorizer(_sqlite_authorizer)
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = [list(row) for row in cursor.fetchmany(500)]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"query failed: {exc}") from exc
    finally:
        conn.close()


def _sqlite_authorizer(action: int, arg1, arg2, db, trigger) -> int:
    """sqlite3 authorizer: allow pure reads only; deny every write/DDL."""
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,  # aggregate/scalar functions (count, sum, ...)
        sqlite3.SQLITE_RECURSIVE,
    }
    if action in allowed:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _safe_workspace_path(rel: Union[str, Path]) -> Path:
    """Resolve a tool-supplied path inside the workspace; refuse escapes."""
    p = Path(str(rel))
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"path escapes workspace: {rel!r}")
    target = (WORKSPACE_ROOT / p).resolve()
    if not target.is_relative_to(WORKSPACE_ROOT.resolve()):
        raise ValueError(f"path escapes workspace: {rel!r}")
    return target


def _create_file(args: dict[str, Any]) -> dict[str, Any]:
    """Write a file under workspace/ (parents created as needed)."""
    target = _safe_workspace_path(args["path"])
    content = str(args.get("content") or "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    relative = str(target.relative_to(WORKSPACE_ROOT))
    log.info("tool create_file", extra={"path": relative, "bytes": len(content)})
    return {"path": relative, "bytes": len(content)}


def _read_file(args: dict[str, Any]) -> dict[str, Any]:
    """Read a text file from workspace/ (capped at 1 MB)."""
    target = _safe_workspace_path(args["path"])
    if not target.is_file():
        raise ValueError(f"file not found in workspace: {args['path']!r}")
    relative = str(target.relative_to(WORKSPACE_ROOT))
    text = target.read_text(encoding="utf-8")
    truncated = len(text) > 1_000_000
    text = text[:1_000_000]
    log.info("tool read_file", extra={"path": relative, "bytes": len(text)})
    return {
        "path": relative,
        "content": text,
        "bytes": len(text),
        "truncated": truncated,
    }


def _require_paise(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{key} must be a positive integer paise, got {value!r}")
    return value


def _record_expense(args: dict[str, Any]) -> dict[str, Any]:
    """Record a real ledger SPEND (subject to budget guardrails)."""
    amount = _require_paise(args, "amount_paise")
    with get_session() as s:
        entry = spend(
            s,
            amount,
            destination=str(args.get("destination") or "tool-spend"),
            reference=args.get("reference"),
            correlation_id=args.get("correlation_id"),
        )
        return {
            "entry_id": entry.id,
            "type": entry.type,
            "amount_paise": entry.amount_paise,
        }


def _record_revenue(args: dict[str, Any]) -> dict[str, Any]:
    """Record earned revenue; VERIFIED only with method + confidence >= 0.9."""
    amount = _require_paise(args, "amount_paise")
    with get_session() as s:
        entry = record_revenue(
            s,
            amount,
            source=str(args.get("source") or "tool-revenue"),
            reference=str(args.get("reference") or f"tool-revenue-{amount}"),
            verification_method=args.get("verification_method"),
            confidence=float(args.get("confidence") or 0.0),
            correlation_id=args.get("correlation_id"),
        )
        return {"entry_id": entry.id, "type": entry.type, "status": entry.status}


def _create_opportunity(args: dict[str, Any]) -> dict[str, Any]:
    """Create (or refresh) a DISCOVERED opportunity via the discovery dedupe."""
    from orion.connectors.base import SourceOffer, offer_hash

    required = ("title", "estimated_value_paise")
    for key in required:
        if not args.get(key):
            raise ValueError(f"create_opportunity requires {key!r}")
    offer = SourceOffer(
        title=str(args["title"])[:255],
        source=str(args.get("source") or "agent"),
        url=str(args.get("url") or ""),
        description=str(args.get("description") or ""),
        estimated_value_paise=int(args["estimated_value_paise"]),
        cost_paise=int(args.get("cost_paise") or 0),
        deadline=args.get("deadline"),
        required_skills=list(args.get("required_skills") or []),
        automation_allowed=bool(args.get("automation_allowed")),
        platform_notes=str(args.get("platform_notes") or ""),
        confidence=float(args.get("confidence") or 0.5),
        demand_hint=float(args.get("demand_hint") or 0.5),
        competition_hint=float(args.get("competition_hint") or 0.5),
    )
    with get_session() as s:
        # Reuse the discovery upsert so re-scans collapse onto one row.
        row: Optional[Opportunity] = DiscoveryService()._upsert_offer(offer, "agent", s)
        if row is None:
            row = (
                s.query(Opportunity)
                .filter(Opportunity.content_hash == offer_hash(offer))
                .first()
            )
        return {"id": row.id if row else None, "created": row is not None}


def _request_approval(args: dict[str, Any]) -> dict[str, Any]:
    """Create an approval request (auto-approved in dry-run mode)."""
    action = str(args.get("action") or "")
    if not action:
        raise ValueError("request_approval requires an 'action'")
    service = ApprovalService()
    with get_session() as s:
        req = service.request(
            action,
            why=str(args.get("why") or ""),
            cost_paise=args.get("cost_paise"),
            potential_revenue_paise=args.get("potential_revenue_paise"),
            risk_level=args.get("risk_level"),
            proposed_payload=args.get("proposed_payload"),
            destination=str(args.get("destination") or ""),
            correlation_id=args.get("correlation_id"),
            session=s,
        )
        return {"id": req.id, "status": req.status, "decision": req.decision}


# ---------------------------------------------------------------------------
# Tool declarations (the system's full advertised surface)
# ---------------------------------------------------------------------------

_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}


def _obj(props: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _build_registry() -> None:
    def tool(name, description, input_schema, output_schema, level, approval, handler):
        register_tool(
            ToolSpec(
                name=name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                risk_level=level,
                requires_approval=approval,
                handler=handler,
            )
        )

    # --- research / browsing (not wired this cycle) ------------------------
    tool(
        "search_web",
        "Search the public web. Returns linked results.",
        _obj({"query": _STR}, ["query"]),
        _obj(
            {"results": {"type": "array", "items": _obj({"title": _STR, "url": _STR})}}
        ),
        "L0",
        False,
        _unbuilt("search_web"),
    )
    tool(
        "open_page",
        "Open a page in the controlled browser (domain allowlist enforced).",
        _obj({"url": _STR}, ["url"]),
        _obj({"page_id": _INT, "title": _STR}),
        "L2",
        True,
        _unbuilt("open_page"),
    )
    tool(
        "extract_page",
        "Extract sanitized text/links from an open page.",
        _obj({"page_id": _INT}, ["page_id"]),
        _obj({"text": _STR}),
        "L0",
        False,
        _unbuilt("extract_page"),
    )
    tool(
        "browser_click",
        "Click an element in the browser.",
        _obj({"page_id": _INT, "selector": _STR}, ["page_id", "selector"]),
        _obj({"clicked": _BOOL}),
        "L2",
        True,
        _unbuilt("browser_click"),
    )
    tool(
        "browser_type",
        "Type text into an element in the browser.",
        _obj(
            {"page_id": _INT, "selector": _STR, "text": _STR},
            ["page_id", "selector", "text"],
        ),
        _obj({"typed": _BOOL}),
        "L2",
        True,
        _unbuilt("browser_type"),
    )
    tool(
        "take_screenshot",
        "Save a screenshot of an open page into workspace/screenshots/.",
        _obj({"page_id": _INT, "name": _STR}, ["page_id"]),
        _obj({"path": _STR}),
        "L1",
        False,
        _unbuilt("take_screenshot"),
    )

    # --- local work --------------------------------------------------------
    tool(
        "create_file",
        "Write a text file under workspace/ (path traversal refused).",
        _obj({"path": _STR, "content": _STR}, ["path"]),
        _obj({"path": _STR, "bytes": _INT}),
        "L1",
        False,
        _create_file,
    )
    tool(
        "read_file",
        "Read a text file from workspace/ (1 MB cap).",
        _obj({"path": _STR}, ["path"]),
        _obj({"path": _STR, "content": _STR, "bytes": _INT, "truncated": _BOOL}),
        "L0",
        False,
        _read_file,
    )
    tool(
        "run_python",
        "Run a python snippet in a sandboxed subprocess.",
        _obj({"code": _STR}, ["code"]),
        _obj({"exit_code": _INT, "stdout": _STR, "stderr": _STR}),
        "L1",
        False,
        _unbuilt("run_python"),
    )
    tool(
        "run_test",
        "Run the test suite (pytest); results are advisory only.",
        _obj({"args": {"type": "array", "items": _STR}}),
        _obj({"exit_code": _INT, "stdout": _STR, "stderr": _STR}),
        "L1",
        False,
        _unbuilt("run_test"),
    )
    tool(
        "calculate",
        "Decimal-safe arithmetic: + - * / // % ** on plain numbers.",
        _obj({"expression": _STR}, ["expression"]),
        _obj({"expression": _STR, "result": _STR}),
        "L0",
        False,
        _calculate,
    )
    tool(
        "query_database",
        "SELECT-only read-only SQL against the ORION database.",
        _obj({"sql": _STR}, ["sql"]),
        _obj(
            {
                "columns": {"type": "array", "items": _STR},
                "rows": {"type": "array"},
                "row_count": _INT,
            }
        ),
        "L0",
        False,
        _query_database,
    )

    # --- money + opportunities + approval --------------------------------
    tool(
        "record_expense",
        "Record a real ledger SPEND (budget guardrails enforced).",
        _obj({"amount_paise": _INT, "destination": _STR, "reference": _STR}),
        _obj({"entry_id": _INT, "type": _STR, "amount_paise": _INT}),
        "L3",
        True,
        _record_expense,
    )
    tool(
        "record_revenue",
        "Record earned revenue (VERIFIED only with method + confidence >= 0.9).",
        _obj(
            {
                "amount_paise": _INT,
                "source": _STR,
                "reference": _STR,
                "verification_method": _STR,
                "confidence": _NUM,
            }
        ),
        _obj({"entry_id": _INT, "type": _STR, "status": _STR}),
        "L1",
        False,
        _record_revenue,
    )
    tool(
        "create_opportunity",
        "Persist a discovered opportunity (deduped by content hash).",
        _obj(
            {
                "title": _STR,
                "description": _STR,
                "estimated_value_paise": _INT,
                "cost_paise": _INT,
                "source": _STR,
                "url": _STR,
            }
        ),
        _obj({"id": _INT, "created": _BOOL}),
        "L1",
        False,
        _create_opportunity,
    )
    tool(
        "create_draft",
        "Compose a draft deliverable for human review.",
        _obj({"title": _STR, "body": _STR}),
        _obj({"draft_id": _STR}),
        "L1",
        False,
        _unbuilt("create_draft"),
    )
    tool(
        "request_approval",
        "Queue an approval request for a consequential action.",
        _obj(
            {
                "action": _STR,
                "why": _STR,
                "cost_paise": _INT,
                "potential_revenue_paise": _INT,
                "risk_level": _STR,
            }
        ),
        _obj({"id": _INT, "status": _STR, "decision": _STR}),
        "L2",
        False,
        _request_approval,
    )


_build_registry()


# ---------------------------------------------------------------------------
# CommandRunner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one CommandRunner invocation."""

    exit_code: int
    stdout: str
    stderr: str
    truncated: bool


ALLOWED_COMMANDS = frozenset({"echo", "python", "pytest", "node", "ls", "dir", "git"})
GIT_ALLOWED_SUBCOMMANDS = frozenset(
    {"status", "log", "diff", "branch", "show", "remote"}
)
MAX_OUTPUT_CHARS = 10_000
MAX_RUNTIME_SECONDS = 30

EXIT_BLOCKED = 126
EXIT_TIMEOUT = 124
EXIT_UNKNOWN = 127

# Metacharacters that would reach a shell — forbidden in string commands
# unless quoted (a naive split that keeps them unquoted cannot be trusted).
_SHELL_METACHARS = set(";|&`$<>")

# Defense in depth on top of the allowlist (single-word checks use word
# boundaries but must not trip on e.g. `--format=...`).
_BLOCKLIST_RE = [
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"\bdel\s+/s\b", re.I),
    re.compile(r"(?<![-\w/])format(?![\w-])", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\bmkfs\b", re.I),
]


def _unquoted_metachar(raw: str) -> bool:
    """True when a shell metacharacter appears OUTSIDE quotes in ``raw``."""
    quote: Optional[str] = None
    for char in raw:
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char in _SHELL_METACHARS:
            return True
    return False


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS], True


class CommandRunner:
    """Secure subprocess runner. Constructor takes ``max_runtime_seconds``
    and the allowed cwd roots (defaults: project root + workspace/)."""

    def __init__(
        self,
        max_runtime_seconds: float = MAX_RUNTIME_SECONDS,
        allowed_roots: Optional[Sequence[Path]] = None,
    ):
        self.max_runtime_seconds = max_runtime_seconds
        self.allowed_roots = tuple(
            allowed_roots
            if allowed_roots is not None
            else (PROJECT_ROOT, WORKSPACE_ROOT)
        )

    def run(
        self,
        command: Union[str, Sequence[Union[str, Path]]],
        cwd: Optional[Union[str, Path]] = None,
    ) -> CommandResult:
        """Execute a (string or argv-list) command; never through a shell."""
        if isinstance(command, str):
            raw = command
            if _unquoted_metachar(raw):
                return self._deny("shell metacharacter in command")
            try:
                argv = shlex.split(raw)
            except ValueError as exc:  # unbalanced quotes
                return self._deny(f"could not parse command: {exc}")
            if not argv:
                return self._deny("empty command")
            argv = [str(a) for a in argv]
        else:
            argv = [str(a) for a in command]
            if not argv:
                return self._deny("empty command")
            raw = shlex.join(argv)

        blocked, why = self._policy_violation(argv, raw)
        if blocked:
            return self._deny(why)

        workdir = self._resolve_cwd(cwd)
        if workdir is None:
            return self._deny("cwd outside allowed roots")

        try:
            proc = subprocess.run(
                argv,
                cwd=workdir,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.max_runtime_seconds,
                shell=False,
            )
        except FileNotFoundError:
            return CommandResult(
                exit_code=EXIT_UNKNOWN,
                stdout="",
                stderr=f"command not found: {argv[0]}",
                truncated=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            stdout = (stdout or "") + f"\n[timeout after {self.max_runtime_seconds}s]"
            stdout, truncated = _truncate(stdout)
            stderr, _ = _truncate(stderr or "")
            self._audit(argv, workdir, EXIT_TIMEOUT, stdout, stderr, truncated)
            return CommandResult(EXIT_TIMEOUT, stdout, stderr, truncated)

        stdout, stderr = _truncate(proc.stdout or ""), _truncate(proc.stderr or "")
        self._audit(
            argv, workdir, proc.returncode, stdout[0], stderr[0], stdout[1] or stderr[1]
        )
        return CommandResult(
            proc.returncode, stdout[0], stderr[0], stdout[1] or stderr[1]
        )

    # -- helpers -----------------------------------------------------------

    def _policy_violation(self, argv: list[str], raw: str) -> tuple[bool, str]:
        """(blocked, reason) against the blocklist then the allowlist."""
        for pattern in _BLOCKLIST_RE:
            if pattern.search(raw):
                return (
                    True,
                    f"blocked: command matches blocklist pattern {pattern.pattern!r}",
                )
        name = Path(argv[0]).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name not in ALLOWED_COMMANDS:
            return True, f"blocked: {argv[0]!r} is not on the command allowlist"
        if name == "git":
            if len(argv) < 2 or argv[1] not in GIT_ALLOWED_SUBCOMMANDS:
                return True, "blocked: git restricted to " + ", ".join(
                    sorted(GIT_ALLOWED_SUBCOMMANDS)
                )
        return False, ""

    def _resolve_cwd(self, cwd: Optional[Union[str, Path]]) -> Optional[str]:
        target = Path(cwd) if cwd is not None else PROJECT_ROOT
        try:
            resolved = target.resolve()
        except OSError:
            return None
        if not any(
            resolved.is_relative_to(root.resolve()) for root in self.allowed_roots
        ):
            return None
        return str(resolved)

    def _deny(self, reason: str) -> CommandResult:
        self._audit([], ".", EXIT_BLOCKED, "", reason, False)
        return CommandResult(
            exit_code=EXIT_BLOCKED, stdout="", stderr=reason, truncated=False
        )

    @staticmethod
    def _audit(
        argv: list[str],
        cwd: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        truncated: bool,
    ) -> None:
        log.info(
            "command executed (audit)",
            extra={
                "command": redact_secrets(" ".join(argv)),
                "cwd": cwd,
                "exit_code": exit_code,
                "truncated": truncated,
                "stdout": redact_secrets(stdout),
                "stderr": redact_secrets(stderr),
            },
        )


def ensure_workspace_dirs() -> None:
    """Create workspace/ subdirectories on startup (idempotent)."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_SUBDIRS:
        (WORKSPACE_ROOT / name).mkdir(parents=True, exist_ok=True)
