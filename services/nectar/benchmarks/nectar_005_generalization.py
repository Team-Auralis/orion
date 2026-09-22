"""NECTAR-005: Stimulus generalization & discrimination.

One full-brain simulation per PROCESS (Brian2's global object registry makes
in-process reruns leak irrecoverably on 8 GB). Usage:

  python nectar_005_generalization.py --case A_ref
  python nectar_005_generalization.py --case A_noise
  ... etc ...
  python nectar_005_generalization.py --aggregate

Each case writes results/NECTAR-005_{case}.json; --aggregate merges them and
computed the discrimination Jaccards.
"""

import sys
import os
import time
import json
import argparse

import numpy as np
import pandas as pd

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from services.nectar.simulator.brian2_backend import Brian2Backend
from services.nectar.connectome.atlas import NeuronAtlas
from services.nectar.safety.audit import audit_event

CONN = r"D:\orion\data\nectar\connectome\Connectivity_630.parquet"
COMP = r"D:\orion\data\nectar\connectome\Completeness_630.csv"
OUT = r"D:\orion\data\nectar\results"
REF = r"D:\orion\data\nectar\results\reference_sugarR.parquet"
DURATION_S = 1.0

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

CASES = {
    "A_ref": "sugar21",
    "A_noise": "sugar21+noise",
    "A_partial_10": "sugar10",
    "A_partial_5": "sugar5",
    "B_bitter": "bitter",
    "C_danger": "danger",
    "C_novel_vision": "vision",
}


def get_stim(kind):
    comp = pd.read_csv(COMP, index_col=0)
    f2i = {rid: i for i, rid in enumerate(comp.index)}
    atlas = NeuronAtlas()
    if kind == "sugar21":
        return [f2i[f] for f in SUGAR_FIDS if f in f2i]
    if kind == "sugar10":
        return [f2i[f] for f in SUGAR_FIDS[:10] if f in f2i]
    if kind == "sugar5":
        return [f2i[f] for f in SUGAR_FIDS[:5] if f in f2i]
    if kind in ("bitter", "danger", "vision"):
        name = {
            "bitter": "taste_bitter",
            "danger": "smell_danger",
            "vision": "vision_looming",
        }[kind]
        fids = atlas.stimulus_neuron_ids(name)
        return [f2i[f] for f in fids if f in f2i]
    raise ValueError(kind)


def run_case(case):
    import brian2 as b2

    kind = CASES[case]
    noise = kind.endswith("+noise")
    stim_kind = kind.split("+")[0]
    stim_idx = get_stim(stim_kind)

    comp = pd.read_csv(COMP, index_col=0)
    n_neurons = len(comp)

    backend = Brian2Backend(seed=0)
    backend.reset()
    backend.load_connectome(CONN, {"completeness_path": COMP})
    if stim_idx:
        backend.stimulate(stim_idx, "stim", DURATION_S, rate=200.0)
    if noise:
        backend._pois.append(
            b2.PoissonInput(
                backend._neu,
                target_var="v",
                N=1,
                rate=0.5 * b2.Hz,
                weight=backend._params["w_syn"] * backend._params["f_poi"] * b2.mV,
            )
        )
    t0 = time.time()
    backend.run(DURATION_S)
    wall = time.time() - t0
    trains = backend.spike_trains()
    i2fid = backend._i2flyid
    responders = {i2fid[idx] for idx in trains}

    df = pd.read_parquet(REF)
    n_trials = df["trial"].nunique()
    ref_rates = df.groupby("flywire_id")["t"].count() / n_trials
    ref_resp = set(ref_rates[ref_rates > 0].index)
    counts = {i2fid[idx]: len(ts) for idx, ts in trains.items()}

    ov = len(responders & ref_resp)
    p = ov / max(len(responders), 1)
    r = ov / len(ref_resp)
    shared = responders & ref_resp
    mine = [counts.get(fid, 0) / DURATION_S for fid in shared]
    refs = [ref_rates[fid] for fid in shared]
    corr = (
        float(np.corrcoef(mine, refs)[0, 1])
        if len(shared) > 2 and np.std(mine) > 0 and np.std(refs) > 0
        else None
    )

    entry = {
        "condition": case,
        "stimulus": kind,
        "background_noise_hz": 0.5 if noise else 0.0,
        "n_driven": len(stim_idx),
        "n_neurons": n_neurons,
        "our_responders": int(len(responders)),
        "responder_ids": sorted(int(x) for x in responders),
        "overlap_vs_sugar_ref": int(ov),
        "precision_vs_sugar_ref": round(p, 4),
        "recall_vs_sugar_ref": round(r, 4),
        "rate_corr_vs_sugar_ref": round(corr, 4) if corr == corr else None,
        "wall_s": round(wall, 2),
        "measured": True,
        "mock": False,
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"NECTAR-005_{case}.json"), "w") as f:
        json.dump(entry, f, indent=2)
    print(json.dumps(entry, indent=2))
    return entry


def aggregate(first_spike_split=False):
    results = {}
    for case in list(CASES) + ["A_window_early", "A_window_late"]:
        path = os.path.join(OUT, f"NECTAR-005_{case}.json")
        if os.path.exists(path):
            with open(path) as f:
                results[case] = json.load(f)

    if not results:
        print("no case reports found")
        return
    for case, e in results.items():
        print(
            f"  {case:<18} resp={e['our_responders']:>5} "
            f"P={e['precision_vs_sugar_ref']:.3f} R={e['recall_vs_sugar_ref']:.3f} "
            f"corr={e.get('rate_corr_vs_sugar_ref')}"
        )

    # temporal cohort split handled by --case A_window_early / A_window_late
    agg = {
        "results": results,
        "measured": True,
        "mock": False,
        "experiment": "NECTAR-005",
    }
    if len(results) >= 2:
        pairs = [
            ("A_ref", "B_bitter"),
            ("A_ref", "C_danger"),
            ("A_ref", "C_novel_vision"),
            ("B_bitter", "C_danger"),
        ]
        disc = {}
        for a, b in pairs:
            if a in results and b in results:
                ids_a = set(results[a].get("responder_ids", []))
                ids_b = set(results[b].get("responder_ids", []))
                if ids_a and ids_b:
                    ja = len(ids_a & ids_b) / max(len(ids_a | ids_b), 1)
                    disc[f"{a}_vs_{b}"] = round(ja, 4)
                else:
                    disc[f"{a}_vs_{b}"] = None
        agg["discrimination_jaccard"] = disc
        print("discrimination (Jaccard):")
        for k, v in disc.items():
            print(f"  {k}: {v}")

    compact = {}
    for case, e in results.items():
        compact[case] = {k: v for k, v in e.items() if k != "responder_ids"}
    agg["results"] = compact
    with open(os.path.join(OUT, "NECTAR-005_generalization.json"), "w") as f:
        json.dump(agg, f, indent=2, default=str)
    audit_event(
        "exp.nectar_005_generalization",
        {
            "conditions": [c for c in results],
            "reproduced_ref": results.get("A_ref", {}).get("precision_vs_sugar_ref"),
            "partial_robustness": {
                c: results[c]["recall_vs_sugar_ref"]
                for c in ("A_partial_10", "A_partial_5")
                if c in results
            },
            "discrimination_jaccard": disc if len(results) >= 2 else None,
        },
    )


def run_temporal(case):
    """A_window_early: responders with first spike < 0.5 s; late: >= 0.5 s."""
    import brian2 as b2

    stim_idx = get_stim("sugar21")
    backend = Brian2Backend()
    backend.reset()
    backend.load_connectome(CONN, {"completeness_path": COMP})
    b2.seed(0)
    backend.stimulate(stim_idx, "stim", DURATION_S, rate=200.0)
    backend.run(DURATION_S)
    trains = backend.spike_trains()
    i2fid = backend._i2flyid
    early, late = set(), set()
    for idx, ts in trains.items():
        (early if ts[0] < 0.5 else late).add(i2fid[idx])

    df = pd.read_parquet(REF)
    ref_resp = set(df.groupby("flywire_id")["t"].count()[lambda s: s > 0].index)
    cohort = early if case == "A_window_early" else late
    ov = len(cohort & ref_resp)
    p = ov / max(len(cohort), 1)
    r = ov / len(ref_resp)
    entry = {
        "condition": case,
        "stimulus": "sugar21 window",
        "window": "first_spike<0.5s"
        if case == "A_window_early"
        else "first_spike>=0.5s",
        "n_driven": len(stim_idx),
        "our_responders": int(len(cohort)),
        "responder_ids": sorted(int(x) for x in cohort),
        "overlap_vs_sugar_ref": int(ov),
        "precision_vs_sugar_ref": round(p, 4),
        "recall_vs_sugar_ref": round(r, 4),
        "measured": True,
        "mock": False,
    }
    with open(os.path.join(OUT, f"NECTAR-005_{case}.json"), "w") as f:
        json.dump(entry, f, indent=2)
    print(json.dumps(entry, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="case name or --aggregate")
    ap.add_argument("--aggregate", action="store_true")
    args = ap.parse_args()
    if args.aggregate:
        aggregate()
    elif args.case in ("A_window_early", "A_window_late"):
        run_temporal(args.case)
    elif args.case in CASES:
        run_case(args.case)
    else:
        ap.error(f"unknown case {args.case!r}")


if __name__ == "__main__":
    main()
