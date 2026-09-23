"""NECTAR-006: ORION-benefit benchmark (transfer + margin design).

Question: at a fixed budget (same neuron count, same downstream readout over the
top-8000 spike counts, euclidean nearest-centroid, leave-one-seed-out CV), does
NECTAR's biological wiring beat generic/stripped alternatives?

Task (non-circular): a downstream sees only population spike counts — it never
sees which neurons were driven. It must
  (a) SEPARATE three modalities (sugar / bitter / danger) — identity accuracy,
  (b) TRANSFER to a degraded input: a stimulus from only 5 of the 21 sugar GRNs
      (partial5) must be classified as "sugar" (transfer rate).

Input-only caveat is reported, not hidden: the driven sets are class-disjoint
by construction, so identity separation is partly attributable to the stimulus
stream itself; the part of the question that is about the connectome is the
MARGIN and the TRANSFER rate, and their collapse under wiring destruction.

Arms (same N, same input drives, same readout):
  real        v630 connectome (NECTAR)
  shuffled    same connectome, synapses shuffled
  reservoir   random echo-state net, same N

Always fresh process per case (Brian2 global registry leaks across in-process
reruns; OOM on 8 GB). Seeds 0/1/2 for LOO-CV determinism (b2.seed / np.seed
documented per arm).

Usage:  python nectar_006_benefit.py --case real:partial5:1
        python nectar_006_benefit.py --evaluate
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
from services.nectar.connectome.atlas import NeuronAtlas
from services.nectar.safety.audit import audit_event

CONN_REAL = r"D:\orion\data\nectar\connectome\Connectivity_630.parquet"
CONN_SHUFFLED = r"D:\orion\data\nectar\controls\Connectivity_630_shuffled-conn.parquet"
COMP = r"D:\orion\data\nectar\connectome\Completeness_630.csv"
OUT = r"D:\orion\data\nectar\results"
DURATION_S = 1.0
TOP_K = 8000

SUGAR_FIDS = [
    720575940624963786, 720575940630233916, 720575940637568838,
    720575940638202345, 720575940617000768, 720575940630797113,
    720575940632889389, 720575940621754367, 720575940621502051,
    720575940640649691, 720575940639332736, 720575940616885538,
    720575940639198653, 720575940620900446, 720575940617937543,
    720575940632425919, 720575940633143833, 720575940612670570,
    720575940628853239, 720575940629176663, 720575940611875570,
]

ARMS = ("real", "shuffled", "reservoir")
CLASSES = ("sugar", "bitter", "danger")
STIMS = CLASSES + ("partial5", "control")
SEEDS = (0, 1, 2)


def stim_indices(kind):
    comp = pd.read_csv(COMP, index_col=0)
    f2i = {rid: i for i, rid in enumerate(comp.index)}
    atlas = NeuronAtlas()
    if kind == "sugar":
        return [f2i[f] for f in SUGAR_FIDS if f in f2i]
    if kind == "partial5":
        return [f2i[f] for f in SUGAR_FIDS[:5] if f in f2i]
    if kind == "bitter":
        return [f2i[f] for f in atlas.stimulus_neuron_ids("taste_bitter")
                if f in f2i]
    if kind == "danger":
        return [f2i[f] for f in atlas.stimulus_neuron_ids("smell_danger")
                if f in f2i]
    if kind == "control":
        return []
    raise ValueError(kind)


def run_brian_arm(conn_path, stim_idx, seed):
    import brian2 as b2
    backend = Brian2Backend()
    backend.reset()
    backend.load_connectome(conn_path, {"completeness_path": COMP})
    b2.seed(seed)
    if stim_idx:
        backend.stimulate(stim_idx, "stim", DURATION_S, rate=200.0)
    t0 = time.time()
    backend.run(DURATION_S)
    wall = time.time() - t0
    trains = backend.spike_trains()
    i2fid = backend._i2flyid
    counts = {i2fid[idx]: len(ts) for idx, ts in trains.items()}
    return counts, wall


def run_reservoir(stim_idx, seed):
    rng = np.random.RandomState(5000 + seed)
    n = 127400
    c = 10
    pre = rng.randint(0, n, size=n * c)
    post = np.tile(np.arange(n), c)
    w = (rng.rand(n * c) - 0.5) * 0.8
    drive = np.zeros(n)
    for i in stim_idx:
        drive[i] = 1.0
    r = rng.rand(n) - 0.5
    dt = 1e-3
    leak = dt / 20e-3
    crossings = np.zeros(n, dtype=np.int32)
    steps = int(DURATION_S / dt)
    # pre-buffer input to avoid per-step allocation
    input_tanh = np.empty(n)
    t0 = time.time()
    for _ in range(steps):
        np.tanh(r, out=input_tanh)
        acc = np.zeros(n)
        np.add.at(acc, post, w * input_tanh[pre])
        new = (1.0 - leak) * r + leak * (0.5 * acc + drive)
        crossed = (r <= 0.0) & (new > 0.0)
        crossings[crossed] += 1
        r = new
    wall = time.time() - t0
    return {int(i): int(v) for i, v in enumerate(crossings)}, wall


def run_case(spec):
    arm, stim, seed = spec.split(":")
    seed = int(seed)
    stim_idx = stim_indices(stim)
    if arm == "real":
        counts, wall = run_brian_arm(CONN_REAL, stim_idx, seed)
    elif arm == "shuffled":
        counts, wall = run_brian_arm(CONN_SHUFFLED, stim_idx, seed)
    elif arm == "reservoir":
        counts, wall = run_reservoir(stim_idx, seed)
    else:
        raise ValueError(arm)

    ids = sorted(counts, key=lambda f: -counts[f])[:TOP_K]
    entry = {
        "arm": arm, "stim": stim, "seed": seed,
        "n_driven": len(stim_idx),
        "n_responders": int(len(counts)),
        "topk_ids": [int(x) for x in ids],
        "topk_counts": [int(counts[x]) for x in ids],
        "wall_s": round(wall, 2),
        "measured": True, "mock": False,
    }
    path = os.path.join(OUT, f"NECTAR-006_{arm}_{stim}_seed{seed}.json")
    with open(path, "w") as f:
        json.dump(entry, f, indent=2)
    print(json.dumps({k: entry[k] for k in
                      ("arm", "stim", "seed", "n_responders", "wall_s")}))


def driven_ids_for(stim):
    """Return flywire IDs of driven neurons (topk_ids are root IDs)."""
    comp = pd.read_csv(COMP, index_col=0)
    return set(int(comp.index[i]) for i in stim_indices(stim))


def featurize(recs, feat, per_rec_driven):
    fmap = {f: i for i, f in enumerate(feat)}
    X = np.zeros((len(recs), len(feat)))
    for ri, r in enumerate(recs):
        driven = per_rec_driven.get(recs[ri]["stim"], set()) if per_rec_driven else set()
        for fid, c in zip(r["topk_ids"], r["topk_counts"]):
            j = fmap.get(fid)
            if j is not None and fid not in driven:
                X[ri, j] += c
    return X


def evaluate(no_driven=False):
    allrecs = []
    for arm in ARMS:
        for stim in STIMS:
            for seed in SEEDS:
                path = os.path.join(OUT, f"NECTAR-006_{arm}_{stim}_seed{seed}.json")
                if os.path.exists(path):
                    with open(path) as f:
                        allrecs.append(json.load(f))

    driven = {s: driven_ids_for(s) for s in STIMS}
    summary = {"experiment": "NECTAR-006", "measured": True, "mock": False}
    if no_driven:
        summary["feature_filter"] = "driven-neuron IDs excluded from features"
    for arm in ARMS:
        arm_recs = [r for r in allrecs if r["arm"] == arm]
        if len(arm_recs) < 12:
            print(f"[skip] {arm}: only {len(arm_recs)}/12 runs present")
            continue
        test_acc = []
        transfer_hits = []
        margins = []
        for held in SEEDS:
            train = [r for r in arm_recs if r["seed"] != held]
            test = [r for r in arm_recs if r["seed"] == held]
            feat = sorted({f for r in train for f in r["topk_ids"]})
            if no_driven:
                feat = sorted({f for f in feat if not any(
                    f in d for d in driven.values())})
            Xtr = featurize(train, feat, driven if no_driven else None)
            labs = [r["stim"] for r in train]
            centroids = {}
            for st in CLASSES:
                idx = [i for i, l in enumerate(labs) if l == st]
                centroids[st] = Xtr[idx].mean(axis=0) if idx else np.zeros(len(feat))
            Xte = featurize(test, feat, driven if no_driven else None)
            for ri, r in enumerate(test):
                if r["stim"] in CLASSES:
                    dists = {st: float(np.linalg.norm(Xte[ri] - cen))
                             for st, cen in centroids.items()}
                    test_acc.append(dists[r["stim"]] == min(dists.values()))
                elif r["stim"] == "partial5":
                    dists = {st: float(np.linalg.norm(Xte[ri] - cen))
                             for st, cen in centroids.items()}
                    order = sorted(dists, key=dists.get)
                    transfer_hits.append(order[0] == "sugar")
                    margins.append(dists[order[1]] - dists["sugar"])
        n_t = len(test_acc)
        n_tr = len(transfer_hits)
        summary[arm] = {
            "identity_accuracy": (round(sum(test_acc) / n_t, 4)
                                  if n_t else None),
            "n_identity_trials": n_t,
            "transfer_rate_partial5_to_sugar": (round(
                sum(transfer_hits) / n_tr, 4) if n_tr else None),
            "n_transfer_trials": n_tr,
            "transfer_margin_mean": (round(float(np.mean(margins)), 4)
                                     if margins else None),
            "transfer_margin_std": (round(float(np.std(margins)), 4)
                                    if margins else None),
            "mean_wall_s": round(float(np.mean(
                [r["wall_s"] for r in arm_recs])), 2),
            "n_neurons": 127400,
        }
        print(f"  {arm}: identity={summary[arm]['identity_accuracy']} "
              f"transfer={summary[arm]['transfer_rate_partial5_to_sugar']} "
              f"margin={summary[arm]['transfer_margin_mean']} "
              f"wall={summary[arm]['mean_wall_s']}s")
    summary["chance_identity"] = 1 / 3
    summary["chance_transfer"] = 1 / 3
    path = os.path.join(
        OUT, "NECTAR-006_benefit.json" if not no_driven
        else "NECTAR-006_benefit_nodriven.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    audit_event("exp.nectar_006_benefit",
                {k: v for k, v in summary.items() if k != "origin_path"})
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="ARM:STIM:SEED")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--no-driven", action="store_true",
                    help="exclude driven-neuron features from readout")
    args = ap.parse_args()
    if args.evaluate:
        evaluate(no_driven=args.no_driven)
    elif args.case:
        run_case(args.case)
    else:
        ap.error("provide --case ARM:STIM:SEED or --evaluate")


if __name__ == "__main__":
    main()