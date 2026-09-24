"""Tiny unit tests for the ORION-HIVE prototype: device envelope contract and
the token-weighted FedAvg aggregation (no training, no processes - pure)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
import torch

from hive.envelope import (
    ROLE_EVAL,
    ROLE_LIGHTWEIGHT,
    ROLE_PRIMARY,
    declare_device,
)
from hive.aggregation import fedavg, loss_reduction_pct, mse


def test_envelope_carries_declared_capability():
    env = declare_device("dev-1", ROLE_PRIMARY, cpu_threads_budget=3, ram_mb_budget=768)
    assert env.device_id == "dev-1"
    assert env.role == ROLE_PRIMARY
    assert env.cpu_threads_budget == 3
    assert env.transport == "multiprocessing-pipe"

    # a device re-probes its own tok/s and re-declares (capability update)
    updated = env.with_tps(1234.5)
    assert updated.tokens_per_sec_estimate == 1234.5
    assert updated.cpu_threads_budget == 3  # the rest of the envelope is preserved

    with pytest.raises(ValueError):
        declare_device("bad", "no-such-role", cpu_threads_budget=1)


def test_fedavg_weights_by_tokens_trained():
    # Two "workers": worker A trained 10 tokens, worker B trained 30 tokens.
    a = {"w": torch.tensor([1.0, 0.0]), "b": torch.tensor([0.5])}
    b = {"w": torch.tensor([0.0, 2.0]), "b": torch.tensor([0.0])}
    agg = fedavg([(a, 10), (b, 30)])
    # weighted average of w: (10*[1,0] + 30*[0,2]) / 40 = [0.25, 1.5]
    assert torch.allclose(agg["w"], torch.tensor([0.25, 1.5]))
    assert torch.allclose(agg["b"], torch.tensor([0.125]))  # (10*0.5+30*0)/40

    # a single update passes through unchanged (resume/full-fleet edge)
    one = fedavg([(a, 10)])
    assert mse(one, a) < 1e-6

    with pytest.raises(ValueError):
        fedavg([])


def test_loss_reduction_pct():
    assert loss_reduction_pct(1.0, 0.5) == 50.0
    assert loss_reduction_pct(1.0, 1.3) == 0.0  # a rising loss is not a reduction
    assert loss_reduction_pct(0.0, 0.1) == 0.0  # no meaningful start
