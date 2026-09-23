"""ORION Runner - composable @experiment / @param decorators and run lifecycle.

Design adapted from higgsfield (https://github.com/higgsfield-ai/higgsfield,
Copyright (c) higgsfield.ai authors, Apache-2.0 - see THIRD_PARTY.md), where
experiments declare their hyperparameters in the decorated function signature
and the framework records an audit trail per run. Customised for ORION: the
AST/SSH orchestration is replaced by a local runner that bridges into the ORION
training audit log (logs/training_runs.jsonl).
"""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Set

from .params import Param

_EXPERIMENTS: Dict[str, "experiment"] = {}

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_LOG_PATH = REPO_ROOT / "logs" / "training_runs.jsonl"


def runs_log_path() -> Path:
    """Audit-log location. Tests redirect it via the ORION_RUNS_LOG env var."""
    override = os.environ.get("ORION_RUNS_LOG")
    return Path(override) if override else RUNS_LOG_PATH


class Params:
    def __init__(self, values: Dict[str, Any]):
        self.__dict__.update(values)

    def __getitem__(self, key: str) -> Any:
        return self.__dict__[key]

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class _InnerWrap:
    def __init__(self, func: Callable, params: List[Param]):
        self.func = func
        self._params: List[Param] = []
        for p in params:
            self.add_param(p)

    def add_param(self, param: Param):
        if param.name not in {p.name for p in self._params}:
            self._params.append(param)

    @property
    def params(self) -> List[Param]:
        return list(self._params)


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("experiment name must be a non-empty string")
    if name in _EXPERIMENTS:
        raise ValueError(f"Experiment with name {name!r} already exists")
    return name


class experiment:
    name: str
    params: List[Param]
    func: Optional[Callable]

    def __init__(self, name: str, *, seed: Optional[int] = None):
        self.name = _check_name(name)
        self.seed = 42 if seed is None else int(seed)
        self.params = [Param("seed", default=self.seed, type=int,
                             description="Random seed for reproducibility")]
        self.func = None
        _EXPERIMENTS[self.name] = self

    def __call__(self, func: Callable) -> Callable:
        if isinstance(func, _InnerWrap):
            if "seed" not in {p.name for p in func.params}:
                self.params = self.params + func.params
            else:
                self.params = func.params
            self.func = func.func
        elif callable(func):
            self.func = func
        else:
            raise ValueError(
                f"experiment decorator needs a callable, got {type(func).__name__}"
            )
        return func


class param:
    def __init__(self, name: str, *, default: Any = None, description: str = None,
                 required: bool = False, type: Optional[type] = None,
                 options: Optional[tuple] = None):
        self._param = Param.from_values(name=name, default=default,
                                        description=description,
                                        required=required, type=type,
                                        options=options)

    def __call__(self, func: Callable) -> Callable:
        if isinstance(func, _InnerWrap):
            func.add_param(self._param)
            return func
        if callable(func):
            return _InnerWrap(func, [self._param])
        raise ValueError("param decorator needs a callable")


def get_experiment(name: str) -> Optional["experiment"]:
    return _EXPERIMENTS.get(name)


def all_experiments() -> List["experiment"]:
    return list(_EXPERIMENTS.values())


# --- audit helpers (stdlib only; no torch dependency) ---
def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"],
                             cwd=str(REPO_ROOT), capture_output=True,
                             text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def _read_rows() -> List[dict]:
    path = runs_log_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_rows(rows: List[dict]):
    path = runs_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def append_row(row: dict) -> dict:
    path = runs_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row


def remove_row(run_id: str):
    rows = _read_rows()
    kept = [r for r in rows if r.get("run_id") != run_id]
    if len(kept) != len(rows):
        _write_rows(kept)


def replace_or_append(run_id: str, row: dict):
    rows = _read_rows()
    found = False
    for i, existing in enumerate(rows):
        if existing.get("run_id") == run_id:
            rows[i] = row
            found = True
            break
    if not found:
        rows.append(row)
    _write_rows(rows)


def latest_run() -> Optional[dict]:
    rows = _read_rows()
    return rows[-1] if rows else None


def latest_run_for(experiment: str, status: Optional[str] = "COMPLETED") -> Optional[dict]:
    for row in reversed(_read_rows()):
        if row.get("experiment") == experiment and (
                status is None or row.get("status") == status):
            return row
    return None


def new_run_id(prefix: str = "orion-run") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _resolve_params(exp: "experiment", values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if values is None:
        values = {}
    resolved = {}
    for p in exp.params:
        if p.name in values and values[p.name] is not None:
            resolved[p.name] = p.coerce(values[p.name])
        else:
            resolved[p.name] = p.coerce(p.default)
    for key in values:
        if key not in resolved and key not in {p.name for p in exp.params}:
            raise ValueError(f"experiment {exp.name!r} has no param {key!r}")
    return resolved


def run_experiment(name: str, values: Optional[Dict[str, Any]] = None):
    """Execute a registered experiment with an audit trail.

    Writes a RUNNING marker row before invoking the decorated function, then
    replaces it with the enriched record once training returns (or with a
    FAILED row on error). The single surviving row carries both the legacy
    training-record fields and the ORION Runner `experiment`/`params` fields.
    """
    exp = get_experiment(name)
    if exp is None or exp.func is None:
        raise ValueError(f"no registered experiment named {name!r}")
    resolved = _resolve_params(exp, values)
    run_id = new_run_id(f"orion-{name}")
    marker = {
        "run_id": run_id,
        "timestamp": _now(),
        "status": "RUNNING",
        "experiment": exp.name,
        "params": resolved,
        "git_commit": get_git_commit(),
    }
    append_row(marker)
    started = time.time()
    try:
        result = exp.func(Params(resolved))
    except BaseException as error:
        remove_row(run_id)
        replace_or_append(run_id, {
            "run_id": run_id,
            "timestamp": _now(),
            "status": "FAILED",
            "experiment": exp.name,
            "params": resolved,
            "error_message": f"{type(error).__name__}: {error}",
            "duration_seconds": round(time.time() - started, 2),
        })
        raise

    if hasattr(result, "__dict__"):
        base = dict(result.__dict__)
    elif isinstance(result, dict):
        base = dict(result)
    else:
        base = {}

    record_id = base.get("run_id") or run_id
    row = {"run_id": record_id, "experiment": exp.name, "params": resolved}
    row.update(base)
    row["experiment"] = exp.name
    row["params"] = resolved
    row.setdefault("timestamp", _now())
    row.setdefault("status", base.get("status", "COMPLETED"))
    row["duration_seconds"] = round(base.get("duration_seconds", time.time() - started), 2)
    remove_row(run_id)
    replace_or_append(record_id, row)
    return result