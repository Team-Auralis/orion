"""FedAvg-style aggregation: update weights weighted by tokens trained."""

from collections import OrderedDict

import torch


def fedavg(updates) -> OrderedDict:
    """updates: [(state_dict, tokens_trained), ...] -> token-weighted average.

    Divergence is explicit and handled by the caller (dropout) - here every
    update counts toward the average.
    """
    if not updates:
        raise ValueError("fedavg needs at least one update")
    total = sum(t for _, t in updates)
    if total <= 0:
        raise ValueError("fedavg needs positive total tokens")
    keys = list(updates[0][0].keys())
    agg: OrderedDict = OrderedDict()
    for k in keys:
        acc = None
        for sd, t in updates:
            w = sd[k].float() * t
            acc = w if acc is None else acc + w
        agg[k] = acc / total
    return agg


def loss_reduction_pct(start: float, end: float) -> float:
    if not start:
        return 0.0
    return max(0.0, 100.0 * (start - end) / start)


def mse(dict_a, dict_b) -> float:
    """Max abs diff between two state dicts (for checkpoint round-trip checks)."""
    worst = 0.0
    for k in dict_a:
        d = (dict_a[k].float() - dict_b[k].float()).abs().max().item()
        worst = max(worst, d)
    return worst
