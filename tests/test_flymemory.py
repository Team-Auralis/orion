import numpy as np
import pytest

from services.nectar.memory.flymemory import FlyMemory


class _FakeSyn:
    def __init__(self, pre, post, w):
        self.i = pre
        self.j = post
        self.w = w


@pytest.fixture
def mem(monkeypatch):
    m = FlyMemory.__new__(FlyMemory)
    m._memory_path = ":memory:"
    m.kc_indices = [100, 101, 200]
    m.mbon_indices = [400, 401, 402]
    m.memory = {
        "experiences": [],
        "weight_modifications": {},
        "total_experiences": 0,
    }
    m.g = 0  # count saves

    def fake_save(self):
        self.g += 1

    m.save_memory = fake_save.__get__(m)
    return m


def test_apply_to_synapses_multiplies_only_stored_pairs(mem):
    # Reward on kc 100 and 101 -> stored mods for every KC x MBON pair.
    mem.apply_reward([100, 101], strength=1.5)
    mods = mem.get_weight_multipliers()
    assert (100, 400) in mods and (101, 400) in mods

    pre = np.array([100, 100, 101, 999, 200])
    post = np.array([400, 500, 400, 888, 400])
    w = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    syn = _FakeSyn(pre, post, w)

    n = mem.apply_to_synapses(syn)
    assert n == 2
    assert syn.w[0] == 1.5 and syn.w[2] == 1.5
    # untouched synapses keep baseline weight
    assert syn.w[1] == 1.0 and syn.w[3] == 1.0 and syn.w[4] == 1.0


def test_apply_to_synapses_no_mods_returns_zero(mem):
    pre = np.array([1, 2])
    post = np.array([3, 4])
    syn = _FakeSyn(pre, post, np.array([1.0, 1.0]))
    assert mem.apply_to_synapses(syn) == 0


def test_apply_to_synapses_no_actual_synapses_returns_zero(mem):
    mem.apply_reward([100], strength=1.5)
    # Stored mods exist but the synapse list has no matching pair.
    syn = _FakeSyn(np.array([7]), np.array([8]), np.array([1.0]))
    assert mem.apply_to_synapses(syn) == 0
