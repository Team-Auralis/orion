"""NECTAR-003: Degradation & control conditions.

Probes whether the published sugar match (NECTAR-002 @200 Hz) is genuinely
CAUSED by the connectome wiring, by destroying one aspect of the world at a
time and measuring the response under the same 200 Hz / 1 s sugar protocol.

Controls (each run in a fresh process):
  zero-input       no stimulus at all
  random-target    drive 21 random neurons instead of the 21 sugar GRNs
  shuffled-IDs     POST-HOC statistical null: expected random overlap with the
                   448 reference responders if identity carried no information
                   (analytic, no simulation; ~|ours|*448/127400 ~= 1.5)
  shuffled-conn    global rewiring (full random permutation of pre/post)
  degclass-conn    degree-class-preserving shuffle (out-deg & in-deg sequences
                   individually preserved exactly, wiring rerandomized)
  reduced-conn     keep only weight >= 2 edges (14.7M -> 7.4M)
  tox-signs        flip the Excitatory/inhibitory sign of every edge
  dt-variation     dt 0.5 ms and 0.01 ms vs the dt=0.1 ms baseline

Expected VALIDATION SIGNATURE: zero-input -> near-zero activity;
random-target/shuffled/tox/dt-stability all show the responder profile breaks
down (overlap with 200-Hz reference collapses) — proving the real match is not
an artifact of machinery, stimulus current, or recording, but of wiring.

No fabrication. Every number measured under the frozen config.
"""
import sys
import os
import io
import json
import time
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.nectar.simulator.brian2_backend import Brian2Backend

CONN = r"D:\orion\data\nectar\connectome\Connectivity_630.parquet"
COMP = r"D:\orion\data\nectar\connectome\Completeness_630.csv"
OUT = r"D:\orion\data\nectar\results"
CTRL = r"D:\orion\data\nectar\controls"
REF_200 = r"D:\orion\data\nectar\results\reference_sugarR.parquet"

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
N_REF_RESPONDERS = 448
N_NEURONS = 127400


def _load_ref_responders():
    df = pd.read_parquet(REF_200)
    n_trials = df["trial"].nunique()
    rates = df.groupby("flywire_id")["t"].count() / n_trials
    return set(rates[rates > 0].index)


def run_token(control, seed=0, dt=None):
    comp = pd.read_csv(COMP, index_col=0)
    f2i = {rid: i for i, rid in enumerate(comp.index)}
    sugar_idx = [f2i[f] for f in SUGAR_FIDS if f in f2i]

    out = {
        "experiment": "NECTAR-003",
        "control": control,
        "seed": seed,
        "dt_ms": dt,
        "measured": True,
        "mock": False,
    }

    ref = _load_ref_responders()

    # baseline responder set: real connectome, real sugar drive, 200 Hz, dt=0.1
    baseline = run_brian(comp, CONN, sugar_idx, 200.0, None, seed=seed)
    out["baseline_responders"] = int(len(baseline))

    if control == "zero-input":
        resp = run_brian(comp, CONN, [], 200.0, None, seed=seed)
    elif control == "random-target":
        rng = np.random.default_rng(seed)
        pool = [i for i in range(N_NEURONS) if i not in set(sugar_idx)]
        rand = list(rng.choice(pool, size=len(sugar_idx), replace=False))
        resp = run_brian(comp, CONN, rand, 200.0, None, seed=seed)
    elif control == "shuffled-IDs":
        # statistical null, no simulation needed
        exp_overlap = int(round(len(baseline) * N_REF_RESPONDERS / N_NEURONS))
        over = (baseline & ref)
        out["analytic_true_overlap"] = int(len(over))
        out["expected_random_overlap"] = exp_overlap
        out["null_supported"] = len(over) > exp_overlap * 10  # real >> chance
        return out
    elif control == "shuffled-conn":
        path = make_control_parquet("shuffled-conn")
        resp = run_brian(comp, path, sugar_idx, 200.0, None, seed=seed)
    elif control == "degclass-conn":
        path = make_control_parquet("degclass-conn")
        resp = run_brian(comp, path, sugar_idx, 200.0, None, seed=seed)
    elif control == "reduced-conn":
        path = make_control_parquet("reduced-conn")
        resp = run_brian(comp, path, sugar_idx, 200.0, None, seed=seed)
    elif control == "tox-signs":
        path = make_control_parquet("tox-signs")
        resp = run_brian(comp, path, sugar_idx, 200.0, None, seed=seed)
    elif control == "dt-variation":
        resp = run_brian(comp, CONN, sugar_idx, 200.0, dt, seed=seed)
    else:
        raise ValueError(control)

    overlap = int(len(resp & ref))
    precision = overlap / max(len(resp), 1)
    recall = overlap / N_REF_RESPONDERS
    out.update({
        "our_responders": int(len(resp)),
        "overlap_vs_ref": overlap,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "overlap_vs_baseline": int(len(resp & baseline)),
    })
    return out


def run_brian(comp, conn_path, stim_idx, rate, dt, seed=0):
    backend = Brian2Backend()
    backend.reset()
    backend.load_connectome(conn_path, {"completeness_path": r"D:\orion\data\nectar\connectome\Completeness_630.csv"})
    if dt is not None:
        import brian2 as b2
        b2.defaultclock.dt = dt * b2.ms
    if stim_idx:
        backend.stimulate(stim_idx, "sugar", DURATION_S, rate=rate)
    backend.run(DURATION_S)
    trains = backend.spike_trains()
    return set(backend._i2flyid[idx] for idx in trains)


def make_control_parquet(name):
    os.makedirs(CTRL, exist_ok=True)
    dst = os.path.join(CTRL, f"Connectivity_630_{name}.parquet")
    if os.path.exists(dst):
        return dst
    df = pd.read_parquet(CONN)
    n = len(df)
    src = df["Presynaptic_ID"].to_numpy(np.int64)
    dst_ = df["Postsynaptic_ID"].to_numpy(np.int64)
    w = df["Connectivity"].to_numpy(np.float32)
    ex = df["Excitatory"].to_numpy(np.int8) if "Excitatory" in df.columns else None

    comp = pd.read_csv(COMP, index_col=0)
    comp_ix = {rid: i for i, rid in enumerate(comp.index)}
    rev_ix = {i: rid for rid, i in comp_ix.items()}
    to_idx = lambda a: np.array([comp_ix[x] for x in a], dtype=np.int64)
    to_id = lambda a: np.array([rev_ix[x] for x in a], dtype=np.int64)

    if name == "shuffled-conn":
        rng = np.random.default_rng(42)
        src = rng.permutation(src)
        dst_ = rng.permutation(dst_)
    elif name == "degclass-conn":
        src_i = to_idx(src)
        dst_i = to_idx(dst_)
        out_deg = np.bincount(src_i, minlength=N_NEURONS)
        in_deg = np.bincount(dst_i, minlength=N_NEURONS)
        key_src = out_deg[src_i]
        key_dst = in_deg[dst_i]
        src_i = shuffle_within_class(src_i.copy(), key_src)
        dst_i = shuffle_within_class(dst_i.copy(), key_dst)
        src = to_id(src_i)
        dst_ = to_id(dst_i)
    elif name == "reduced-conn":
        keep = w >= 2
        src, dst_, w, ex = src[keep], dst_[keep], w[keep], ex[keep] if ex is not None else None
    elif name == "tox-signs":
        if ex is not None:
            ex = 1 - ex
        else:
            raise ValueError("no Excitatory column in source")
    else:
        raise ValueError(name)

    pre_idx = to_idx(src)
    post_idx = to_idx(dst_)

    out = pd.DataFrame({
        "Presynaptic_ID": src,
        "Postsynaptic_ID": dst_,
        "Connectivity": w,
        "Presynaptic_Index": pre_idx,
        "Postsynaptic_Index": post_idx,
    })
    if ex is not None:
        out["Excitatory"] = ex
    out.to_parquet(dst, index=False)
    return dst


def shuffle_within_class(arr, key):
    order = np.argsort(key, kind="stable")
    arr_sorted = arr[order].copy()
    keys_sorted = key[order]
    idx = np.flatnonzero(np.r_[True, keys_sorted[1:] != keys_sorted[:-1]])
    idx = np.r_[idx, len(arr)]
    rng = np.random.default_rng(42)
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a > 1:
            rng.shuffle(arr_sorted[a:b])
    return arr_sorted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True,
                    choices=["zero-input", "random-target", "shuffled-IDs",
                             "shuffled-conn", "degclass-conn", "reduced-conn",
                             "tox-signs", "dt-variation"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dt", type=float, default=None)
    args = ap.parse_args()

    t0 = time.time()
    report = run_token(args.control, seed=args.seed, dt=args.dt)
    report["wall_s"] = round(time.time() - t0, 1)
    path = os.path.join(OUT, f"NECTAR-003_{args.control}.json")
    if args.dt is not None:
        path = os.path.join(OUT, f"NECTAR-003_{args.control}_dt{args.dt}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()