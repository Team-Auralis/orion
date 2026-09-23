"""
ORION Runner Verification Tests
===============================
Validates the higgsfield-inspired runner (third_party/higgsfield, Apache-2.0 -
see THIRD_PARTY.md) customised into ORION-native code:

- AST-based experiment discovery runs without importing the training scripts
  (no torch needed, so it works on the low-RAM box).
- Param coercion, options validation and the experiment/param decorator stack.
- The run lifecycle: a RUNNING marker row is replaced by a single enriched
  audit row carrying legacy TrainingRunRecord fields + experiment/params, or
  by a FAILED row on error.
- Organic packing (loader): greedy packing, -100 boundary/pad masking,
  deterministic shuffle under a seed.

The audit log is redirected to a temp file (ORION_RUNS_LOG) so the legacy
suite's `logs/training_runs.jsonl` last-line assertions stay untouched.
"""

import json
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _discover(name):
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from orion_runner.discovery import discover_experiments
    return discover_experiments(str(REPO_ROOT / "scripts" / "training" / name))


def test_ast_discovery_finds_both_experiments_without_imports():
    specs = _discover("orion_train.py") + _discover("orion_dpo.py")
    by_name = {s.name: s for s in specs}
    assert "orion-sft" in by_name and "orion-dpo" in by_name

    sft = by_name["orion-sft"]
    assert sft.seed == 42
    names = {p.name: p for p in sft.params}
    for expected in ("dataset", "epochs", "lr", "seed", "use_packing",
                     "surrogate", "merge_dir"):
        assert expected in names
    assert names["epochs"].type == int
    assert names["lr"].default == 2e-3
    assert names["use_packing"].type == bool
    assert names["lr"].to_schema()["type"] == "float"

    dpo = by_name["orion-dpo"]
    dpo_names = {p.name for p in dpo.params}
    assert {"preferences", "adapter", "beta"} <= dpo_names
    assert {p.type for p in dpo.params} <= {str, int, float, bool}


def test_param_coercion_and_options():
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from orion_runner.params import Param

    p_int = Param.from_values(name="epochs", default=3, type=int)
    assert p_int.coerce("5") == 5
    assert p_int.coerce(7) == 7

    p_bool = Param.from_values(name="pack", default=False, type=bool)
    assert p_bool.coerce("true") is True
    assert p_bool.coerce("false") is False
    assert p_bool.coerce(True) is True
    assert p_bool.coerce(False) is False
    with pytest.raises(ValueError):
        p_bool.coerce(1)  # a value is not a bool flag

    p_opt = Param.from_values(name="quant", default="q4_0", type=str,
                              options=("q4_0", "q8_0"))
    assert p_opt.coerce("q8_0") == "q8_0"
    with pytest.raises(ValueError):
        p_opt.coerce("f16")

    p_any = Param.from_values(name="adapter", default=None, type=str)
    assert p_any.coerce("data/x") == "data/x"


def test_experiment_param_decorator_stack_and_seed():
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import orion_runner as runner

    @runner.experiment("stack-smoke")
    @runner.param("epochs", default=2, type=int)
    @runner.param("seed", default=7, type=int)
    def probe(params):
        return params

    exp = runner.get_experiment("stack-smoke")
    assert exp is not None
    params = {p.name: p for p in exp.params}
    # explicit seed wins; no auto seed duplicate; deterministic decoration order
    assert [p.name for p in exp.params] == ["seed", "epochs"]
    assert params["seed"].default == 7
    assert params["epochs"].default == 2


def _fake_record(run_id):
    class Rec:
        pass
    r = Rec()
    r.run_id = run_id
    r.status = "COMPLETED"
    r.dataset_hash = "abc123"
    r.starting_loss = 1.0
    r.ending_loss = 0.5
    r.loss_reduction_pct = 50.0
    r.hardware = {"cpu_cores": 4, "available_ram_gb": 1.2}
    return r


def test_run_experiment_lifecycle(tmp_path, monkeypatch):
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import orion_runner as runner

    log_file = tmp_path / "runs.jsonl"
    monkeypatch.setenv("ORION_RUNS_LOG", str(log_file))

    @runner.experiment("lifecycle-probe")
    @runner.param("epochs", default=2, type=int)
    def probe(params):
        assert params.epochs == 3
        return _fake_record("adapter-run-00000001")

    result = runner.run_experiment("lifecycle-probe", values={"epochs": "3"})
    assert result.run_id == "adapter-run-00000001"

    rows = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert len(rows) == 1, "RUNNING marker must be replaced, not kept"
    row = rows[0]
    assert row["status"] == "COMPLETED"
    assert row["run_id"] == "adapter-run-00000001"  # record's own id survives
    assert row["experiment"] == "lifecycle-probe"
    assert row["params"]["epochs"] == 3
    assert row["params"]["seed"] == 42  # auto-injected seed
    for legacy in ("dataset_hash", "starting_loss", "ending_loss",
                   "loss_reduction_pct", "hardware"):
        assert legacy in row
    assert row["duration_seconds"] is not None


def test_run_experiment_failure_row(tmp_path, monkeypatch):
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import orion_runner as runner

    log_file = tmp_path / "runs.jsonl"
    monkeypatch.setenv("ORION_RUNS_LOG", str(log_file))

    @runner.experiment("fail-probe")
    @runner.param("lr", default=0.1, type=float)
    def probe(params):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        runner.run_experiment("fail-probe")
    rows = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert len(rows) == 1
    assert rows[0]["status"] == "FAILED"
    assert "boom" in rows[0]["error_message"]
    assert rows[0]["params"]["lr"] == 0.1


def test_pack_sequences_organic_batching():
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from orion_runner.loader import pack_sequences

    samples = [{"input_ids": [i + 1 for i in range(n)]} for n in (3, 5, 4, 2)]
    blocks = pack_sequences(samples, max_len=8, pad_id=0, seed=1,
                            mask_boundaries=True)
    for block in blocks:
        assert len(block["input_ids"]) <= 8
        assert len(block["labels"]) == len(block["input_ids"])
        assert len(block["attention_mask"]) == len(block["input_ids"])

    total = sum(len(s["input_ids"]) for s in samples)
    packed_tokens = sum(
        t for b in blocks for t in b["attention_mask"]
    )
    assert packed_tokens == total, "every token must be packed exactly once"

    boundary_masked = sum(
        1 for b in blocks for t in b["labels"] if t == -100
    )
    assert boundary_masked >= len(blocks)  # first token of each block masked

    a = pack_sequences(samples, max_len=8, pad_id=0, seed=7)
    b = pack_sequences(samples, max_len=8, pad_id=0, seed=7)
    assert [blk["input_ids"] for blk in a] == [blk["input_ids"] for blk in b]