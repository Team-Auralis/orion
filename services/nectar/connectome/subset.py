import os

import pandas as pd

from .loader import load_completeness, load_connectivity


def build_subset(connectome_path: str, completeness_path: str,
                 n_neurons: int = 5000, seed: int = 42,
                 out_dir: str = None) -> dict:
    """
    Build a Phase-1 connectome subset.

    Deterministic: picks `n_neurons` by evenly-stride sampling of the
    completeness roster (keeps a durable subset lineage, unlike random)
    and keeps only connections where both endpoints are in the subset.

    Returns and optionally writes {connectivity, completeness} subset files.
    """
    comp = load_completeness(completeness_path)
    n = len(comp)
    if n_neurons >= n:
        raise ValueError(f"n_neurons={n_neurons} >= full roster {n}.")

    step = n / n_neurons
    ids = sorted(int(i * step) for i in range(n_neurons))
    subset_roster = comp.iloc[ids]
    kept = set(subset_roster.index)
    old2new = {rid: new_i for new_i, rid in enumerate(subset_roster.index)}

    conn = load_connectivity(connectome_path, min_synapses=1)
    mask = conn["pre"].isin(kept) & conn["post"].isin(kept)
    sub = conn[mask].copy()
    sub["pre_idx"] = sub["pre"].map(old2new)
    sub["post_idx"] = sub["post"].map(old2new)

    result = {
        "n_neurons": len(subset_roster),
        "n_connections": len(sub),
        "pre": sub["pre"].to_numpy(),
        "post": sub["post"].to_numpy(),
        "weight": sub["weight"].to_numpy(),
        "sign": sub["sign"].to_numpy(),
        "pre_idx": sub["pre_idx"].to_numpy(),
        "post_idx": sub["post_idx"].to_numpy(),
        "roster": subset_roster.index.to_numpy(),
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        subset_roster.to_csv(os.path.join(out_dir, f"completeness_{n_neurons}.csv"))
        sub[["pre", "post", "weight", "sign", "pre_idx", "post_idx"]].to_parquet(
            os.path.join(out_dir, f"connectivity_{n_neurons}.parquet")
        )

    return result