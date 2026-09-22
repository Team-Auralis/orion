"""Reproduce the PhilShiu sugarR experiment on identical v630 data.

Stimulates the same 21 sugar-sensing neurons at 150 Hz for N trials of 1s.
Compares our spiking output against the published reference (30 trials).
This is the apples-to-apples validity test.
"""

import sys
import os
import time
import json

import numpy as np
import pandas as pd

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from services.nectar.simulator.brian2_backend import Brian2Backend

CONN = r"D:\orion\data\\nectar\connectome\Connectivity_630.parquet"
COMP = r"D:\orion\data\\nectar\connectome\Completeness_630.csv"
REF = r"D:\orion\data\\nectar\results\reference_sugarR.parquet"

SUGAR_FIDS = [
    720575940624963786,
    720575940630233916,
    720575940637568838,
    720575940638202345,
    720575940617000768,
    720575940630797113,
    720575940632889389,
    720575940621754367,
    720575940621502051,
    720575940640649691,
    720575940639332736,
    720575940616885538,
    720575940639198653,
    720575940620900446,
    720575940617937543,
    720575940632425919,
    720575940633143833,
    720575940612670570,
    720575940628853239,
    720575940629176663,
    720575940611875570,
]


def main(n_trials: int = 3, duration_s: float = 1.0):
    comp = pd.read_csv(COMP, index_col=0)
    f2i = {rid: i for i, rid in enumerate(comp.index)}
    missing = [f for f in SUGAR_FIDS if f not in f2i]
    if missing:
        print("WARNING: sugar ids missing from v630 roster:", missing)
    sugar_idx = [f2i[f] for f in SUGAR_FIDS if f in f2i]
    print(
        f"[sugarR] {len(sugar_idx)}/21 sugar neurons mapped on v630 "
        f"(roster={len(comp)})"
    )

    backend = Brian2Backend(seed=0)
    t0 = time.time()
    backend.load_connectome(CONN, {"completeness_path": COMP})
    print(f"[load] {backend._N} neurons | {time.time() - t0:.1f}s")

    rates = {}
    all_trains = {}
    for trial in range(n_trials):
        backend.reset()
        backend.load_connectome(CONN, {"completeness_path": COMP})
        backend.stimulate(sugar_idx, "sugar", duration_s)
        t0 = time.time()
        backend.run(duration_s)
        trains = backend.spike_trains()
        print(
            f"  trial {trial}: {len(trains)} spiking | "
            f"{len(trains) / backend._N * 100:.3f}% | "
            f"wall {time.time() - t0:.1f}s"
        )
        for idx, ts in trains.items():
            fid = backend._i2flyid[idx]
            rates.setdefault(fid, []).append(len(ts) / duration_s)
            all_trains.setdefault(fid, 0)
            all_trains[fid] += len(ts)

    rate_mean = {f: np.mean(r) for f, r in rates.items()}

    ref = pd.read_parquet(REF)
    n_ref_trials = ref["trial"].nunique()
    ref_rates = ref.groupby("flywire_id")["t"].count() / n_ref_trials

    ours = pd.Series(rate_mean).sort_values(ascending=False)
    print()
    print(f"=== OUR TOP-10 RESPONDERS (mean rate Hz over {n_trials} trials) ===")
    for fid, r in ours.head(10).items():
        ref_r = ref_rates.get(fid)
        tag = f"| REF={ref_r:.1f}" if ref_r == ref_r else "| not-in-ref"
        print(f"  flywire={fid} rate={r:.1f} {tag}")

    overlap = len(set(rate_mean) & set(ref_rates.index))
    n_ours = len(rate_mean)
    n_ref = len(ref_rates)
    precision = overlap / max(n_ours, 1)
    recall = overlap / max(n_ref, 1)
    print()
    print(f"=== VALIDATION vs REFERENCE ({n_ref} responding neurons) ===")
    print(f"our responding neurons   : {n_ours}")
    print(f"overlap with reference    : {overlap}")
    print(f"precision (ours intersect ref / ours) : {precision * 100:.1f}%")
    print(f"recall   (ours intersect ref / ref)   : {recall * 100:.1f}%")

    top10_ours = set(ours.head(10).index)
    top10_ref = set(ref_rates.nlargest(10).index)
    top10_overlap = len(top10_ours & top10_ref)
    print(f"top-10 responder overlap  : {top10_overlap}/10")

    report = {
        "experiment": "EXP-SUGAR-001",
        "data": "v630",
        "trials": n_trials,
        "sugar_neurons_stimulated": len(sugar_idx),
        "our_responders": n_ours,
        "ref_responders": int(n_ref),
        "overlap": overlap,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "top10_overlap": top10_overlap,
        "measured": True,
    }
    os.makedirs(r"D:\orion\data\\nectar\results", exist_ok=True)
    path = r"D:\orion\data\\nectar\results\EXP-SUGAR-001_v630.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[saved] {path}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    main(n_trials=n)
