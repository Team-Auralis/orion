"""NECTAR-002: Independent sugar-validation sweep.

Reproduces the published sugarR experiment on v630 across the drive-rate range
reported in Nature (Shiu et al. 2024: 10-200 Hz). For each frequency:

  - runs n_trials full-brain 1.0 s simulations of the 21 sugar GRNs
  - computes precision | recall | F1 | overlap | FP | FN
  - spike-count correlation, firing-rate correlation (Pearson over shared
    responders, ours vs 30-trial published reference)
  - first-spike latency correlation, population activity

200 Hz compares to reference_sugarR.parquet; 100 Hz to the 100 Hz reference;
other frequencies to the 200 Hz reference as a tuning check (expect recall to
drop monotonically with drive but overlap to stay high — frequency tuning).

Seeds: Brian2 PoissonInput draws from numpy's global RNG; different seeds give
independent input instantiations. Results checkpoint to
results/NECTAR-002_{freq}Hz_seed{s}.json and an aggregate is written at the end.

No fabrication: every number measured on this machine under the frozen config.
"""
import sys
import os
import time
import json
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.nectar.simulator.brian2_backend import Brian2Backend

CONN = r"D:\orion\data\nectar\connectome\Connectivity_630.parquet"
COMP = r"D:\orion\data\nectar\connectome\Completeness_630.csv"
OUT = r"D:\orion\data\nectar\results"
REF_200 = r"D:\orion\data\nectar\results\reference_sugarR.parquet"
REF_100 = r"D:\orion\data\nectar\results\reference_sugarR_100Hz.parquet"

SUGAR_FIDS = [
    720575940624963786, 720575940630233916, 720575940637568838,
    720575940638202345, 720575940617000768, 720575940630797113,
    720575940632889389, 720575940621754367, 720575940621502051,
    720575940640649691, 720575940639332736, 720575940616885538,
    720575940639198653, 720575940620900446, 720575940617937543,
    720575940632425919, 720575940633143833, 720575940612670570,
    720575940628853239, 720575940629176663, 720575940611875570,
]

DURATION_S = 1.0


def _pearson(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def load_reference(freq):
    path = REF_200 if freq != 100 else REF_100
    df = pd.read_parquet(path)
    n_trials = df["trial"].nunique()
    counts = df.groupby("flywire_id")["t"].count()  # total spikes over trials
    rate = counts / n_trials
    first = df.groupby("flywire_id")["t"].min()
    responders = set(rate.index[rate > 0])
    return {
        "n_trials": n_trials,
        "responders": responders,
        "rate": rate,
        "counts": counts,
        "first_spike": first,
        "n_responders": int(len(responders)),
    }


def run_sugar_sweep(freq, n_trials, seed):
    comp = pd.read_csv(COMP, index_col=0)
    f2i = {rid: i for i, rid in enumerate(comp.index)}
    sugar_idx = [f2i[f] for f in SUGAR_FIDS if f in f2i]
    ref = load_reference(freq)

    backend = Brian2Backend()
    per_neuron_hz = {}
    per_neuron_first = {}
    total_spikes = 0
    active_union = set()
    run_wall = []
    np.random.seed(seed)

    for trial in range(n_trials):
        backend.reset()
        backend.load_connectome(CONN, {"completeness_path": COMP})
        backend.stimulate(sugar_idx, "sugar", DURATION_S, rate=float(freq))
        t0 = time.time()
        backend.run(DURATION_S)
        run_wall.append(time.time() - t0)
        trains = backend.spike_trains()
        for idx, ts in trains.items():
            fid = backend._i2flyid[idx]  # flywire root ID space (match reference)
            per_neuron_hz.setdefault(fid, []).append(len(ts) / DURATION_S)
            per_neuron_first.setdefault(fid, []).append(ts[0])
            total_spikes += len(ts)
        active_union |= set(trains.keys())

    ours_rate = {fid: float(np.mean(v)) for fid, v in per_neuron_hz.items()}
    ours_first = {fid: float(np.mean(v)) for fid, v in per_neuron_first.items()}
    ours_responders = set(fid for fid, r in ours_rate.items() if r > 0)

    shared = ours_responders & ref["responders"]
    fp = ours_responders - ref["responders"]
    fn = ref["responders"] - ours_responders
    precision = len(shared) / max(len(ours_responders), 1)
    recall = len(shared) / max(len(ref["responders"]), 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    # rate correlation over shared responders (all in flywire ID space)
    mine_r = [ours_rate[fid] for fid in shared]
    ref_r = [ref["rate"][fid] for fid in shared]
    rate_corr = _pearson(mine_r, ref_r)

    # spike-count correlation (counts scaled to per-trial mean)
    mine_c = [ours_rate[fid] * DURATION_S for fid in shared]
    ref_c = [ref["counts"][fid] / ref["n_trials"] for fid in shared]
    count_corr = _pearson(mine_c, ref_c)

    # latency: first-spike time correlation over shared, plus mean
    mine_f = [ours_first[fid] for fid in shared]
    ref_f = [ref["first_spike"][fid] for fid in shared]
    lat_corr = _pearson(mine_f, ref_f)
    lat_mean_ours = float(np.mean(mine_f)) if mine_f else float("nan")
    lat_mean_ref = float(np.mean(ref_f)) if ref_f else float("nan")

    report = {
        "experiment": "NECTAR-002",
        "freq_hz": freq,
        "n_trials": n_trials,
        "seed": seed,
        "duration_s": DURATION_S,
        "sugar_neurons_driven": len(sugar_idx),
        "our_responders": int(len(ours_responders)),
        "ref_responders": ref["n_responders"],
        "overlap": int(len(shared)),
        "false_positives": int(len(fp)),
        "false_negatives": int(len(fn)),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "rate_corr": round(rate_corr, 4) if rate_corr == rate_corr else None,
        "spike_count_corr": round(count_corr, 4) if count_corr == count_corr else None,
        "latency_corr": round(lat_corr, 4) if lat_corr == lat_corr else None,
        "latency_mean_ours_s": round(lat_mean_ours, 4),
        "latency_mean_ref_s": round(lat_mean_ref, 4),
        "population_total_spikes": int(total_spikes),
        "population_active_pct": round(len(ours_responders) / 127400 * 100, 4),
        "mean_run_wall_s": round(float(np.mean(run_wall)), 2),
        "ref_materialization": "200Hz" if freq != 100 else "100Hz",
        "measured": True,
        "mock": False,
    }
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freqs", type=int, nargs="+", default=[200, 150, 100, 50, 25])
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    all_reports = []
    for freq in args.freqs:
        for seed in args.seeds:
            path = os.path.join(OUT, f"NECTAR-002_{freq}Hz_seed{seed}.json")
            if os.path.exists(path) and not args.force:
                with open(path) as f:
                    report = json.load(f)
                print(f"[skip] {freq}Hz seed{seed} exists")
                all_reports.append(report)
                continue
            print(f"[run] freq={freq}Hz seed={seed} trials={args.trials}")
            report = run_sugar_sweep(freq, args.trials, seed)
            with open(path, "w") as f:
                json.dump(report, f, indent=2)
            print(f"  -> P={report['precision']:.3f} R={report['recall']:.3f} "
                  f"F1={report['f1']:.3f} overlap={report['overlap']} "
                  f"FP={report['false_positives']} FN={report['false_negatives']} "
                  f"rate_corr={report['rate_corr']} wall={report['mean_run_wall_s']}s/run")
            all_reports.append(report)

    agg = os.path.join(OUT, "NECTAR-002_aggregate.json")
    with open(agg, "w") as f:
        json.dump(all_reports, f, indent=2)
    print(f"\n[aggregate] {agg} — {len(all_reports)} (freq,seed) conditions")


if __name__ == "__main__":
    main()