"""NECTAR-004: Learning specificity controls (deterministic per-phase).

FIXES the RNG flaw found in EXP-LEARN-001: phases there drew from the drifting
global numpy RNG, so the 41->72 spike "gain" was confounded by RNG noise. Here
every phase is RNG-seeded per (seed, phase), and the whole protocol is repeated
across seeds so feasibility/robustness is measured, not assumed.

Protocol per condition x seed:
  baseline_A[s,phas_0]      drive odor A, no memory
  baseline_B[s,phas_1]      drive odor B, no memory
  recall_<cond>[s,phas_2]   fresh load + apply learned weights (or ablated),
                            drive the relevant odor

Conditions:
  positive-control      reward odor A, weights applied at recall
  no-plasticity         reward computed (memory populated) but NOT applied
  no-dopamine           no reward, weights applied (empty)
  scrambled-dopamine    reward odor B, recall A (contingency: A must NOT gain)
  random-kc             reward 30 random non-driven KCs, recall A (must not gain)
  degree-matched-kc     reward 30 KCs degree-matched to odor A's KC->MBON
                        projection, recall A (must not gain despite equal synapses)

Verdict requires: positive gain >> per-seed noise AND all ablations ~1.0 with a
smoke-clear separation. Mean learn_factor and std across seeds reported.
"""
import sys
import os
import time
import json
import random
import gc

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.nectar.simulator.brian2_backend import Brian2Backend
from services.nectar.memory.flymemory import FlyMemory
from services.nectar.safety.audit import audit_event

CONN = r"D:\orion\data\nectar\connectome\Connectivity_783.parquet"
COMP = r"D:\orion\data\nectar\connectome\Completeness_783.csv"
OUT = r"D:\orion\data\nectar\results"
DURATION_S = 0.4
DRIVE_RATE_HZ = 200.0
N_ODOR = 30
SEED = 2026
CONDITIONS = ["positive-control", "no-plasticity", "no-dopamine",
              "scrambled-dopamine", "random-kc", "degree-matched-kc"]
RECALL_ODOR = {"positive-control": "A", "no-plasticity": "A",
               "no-dopamine": "A", "scrambled-dopamine": "A",
               "random-kc": "A", "degree-matched-kc": "A"}
REWARD_TARGET = {"positive-control": "A", "no-plasticity": "A",
                 "no-dopamine": "none", "scrambled-dopamine": "B",
                 "random-kc": "random", "degree-matched-kc": "degmatch"}


def build_odors(memory):
    kc_pool = sorted(memory.kc_indices)
    rng = random.Random(SEED)
    half = len(kc_pool) // 2
    odor_a = rng.sample(kc_pool[:half], N_ODOR)
    odor_b = rng.sample(kc_pool[half:], N_ODOR)
    return odor_a, odor_b


def kc_to_mbon_degree(memory):
    comp = pd.read_csv(COMP, index_col=0)
    fid2i = {fid: i for i, fid in enumerate(comp.index)}
    pre = pd.read_parquet(CONN)["Presynaptic_ID"].map(fid2i).to_numpy()
    post = pd.read_parquet(CONN)["Postsynaptic_ID"].map(fid2i).to_numpy()
    mbons = memory.mbon_indices
    mask = np.isin(post, list(mbons))
    deg = np.bincount(pre[mask], minlength=len(comp))
    return {int(i): int(d) for i, d in enumerate(deg)}


def degree_matched_sample(odor_a, kg, rng):
    ctrl = []
    exclude = set(odor_a) | set(ctrl)
    for d in [kg[k] for k in odor_a]:
        cands = [k for k in kg if kg[k] == d and k not in exclude]
        if not cands:
            cands = [k for k in kg if k not in exclude]
        pick = rng.choice(cands)
        ctrl.append(pick)
        exclude.add(pick)
    return ctrl


def _run_phase(backend, stimulus_indices, memory, label, rng_seed, apply_learned=False):
    import brian2 as b2
    backend.reset()
    backend.load_connectome(CONN, {"completeness_path": COMP})
    b2.seed(rng_seed)
    if apply_learned:
        backend.apply_memory(memory)
    backend.stimulate(stimulus_indices, label, DURATION_S, rate=DRIVE_RATE_HZ)
    t0 = time.time()
    backend.run(DURATION_S)
    trains = backend.spike_trains()
    mbon = memory.get_active_mbon(trains)
    mbon_spikes = sum(v["spikes"] for v in mbon.values())
    print(f"    [{label:<24} rng={rng_seed}] n_spiking={len(trains):>5} "
          f"MBON spikes={mbon_spikes:>5} KC fired={len(memory.get_active_kc(trains)):>3} "
          f"wall={time.time()-t0:.0f}s")
    gc.collect()
    return {"label": label, "n_spiking": len(trains), "mbon_spikes": mbon_spikes,
            "rng_seed": rng_seed, "wall_s": time.time() - t0}


def build_rewarded(memory, odor_a, odor_b, cond, kg):
    memory.reset_memory()
    target = REWARD_TARGET[cond]
    if target == "A":
        memory.apply_reward(odor_a, strength=1.5, label=f"reward odor A ({cond})")
    elif target == "B":
        memory.apply_reward(odor_b, strength=1.5, label=f"reward odor B ({cond})")
    elif target == "random":
        rng = random.Random(4242)
        rand_kcs = rng.sample(sorted(set(memory.kc_indices) - set(odor_a)), N_ODOR)
        memory.apply_reward(rand_kcs, strength=1.5, label=f"reward random KCs ({cond})")
    elif target == "degmatch":
        rng = random.Random(999)
        deg_kcs = degree_matched_sample(odor_a, kg, rng)
        memory.apply_reward(deg_kcs, strength=1.5, label=f"reward deg-matched KCs ({cond})")
    return memory


def run_condition(cond, seeds):
    memory = FlyMemory()
    odor_a, odor_b = build_odors(memory)
    kg = kc_to_mbon_degree(memory)
    backend = Brian2Backend()

    base_file = os.path.join(OUT, "NECTAR-004_baselines.json")
    cached = {}
    if os.path.exists(base_file):
        with open(base_file) as f:
            cached = json.load(f)

    results = {"condition": cond, "seeds": {}, "measured": True, "mock": False}
    for s in seeds:
        rng_base = s * 1000
        if str(s) in cached:
            base_a = {"mbon_spikes": cached[str(s)]["baseline_A_mbon_spikes"]}
            base_b = {"mbon_spikes": cached[str(s)]["baseline_B_mbon_spikes"]}
            print(f"  [seed {s}] using cached baseline A={base_a['mbon_spikes']} B={base_b['mbon_spikes']}")
        else:
            base_a = _run_phase(backend, odor_a, memory, f"baseline_A_s{s}", rng_base + 0)
            base_b = _run_phase(backend, odor_b, memory, f"baseline_B_s{s}", rng_base + 1)
            cached[str(s)] = {"baseline_A_mbon_spikes": base_a["mbon_spikes"],
                              "baseline_B_mbon_spikes": base_b["mbon_spikes"]}
            with open(base_file, "w") as f:
                json.dump(cached, f, indent=2)
        mem_r = build_rewarded(memory, odor_a, odor_b, cond, kg)
        apply = cond != "no-plasticity"
        if cond == "scrambled-dopamine":
            rec_a = _run_phase(backend, odor_a, mem_r, f"recall_A_s{s}", rng_base + 2, apply_learned=True)
            learn = rec_a["mbon_spikes"] / max(base_a["mbon_spikes"], 1)
            results["scrambled_gain_on_B"] = _run_phase(
                backend, odor_b, mem_r, f"recall_B_s{s}", rng_base + 3, apply_learned=True)["mbon_spikes"] / max(base_b["mbon_spikes"], 1)
        else:
            rec = _run_phase(backend, odor_a, mem_r, f"recall_A_s{s}", rng_base + 2, apply_learned=apply)
            learn = rec["mbon_spikes"] / max(base_a["mbon_spikes"], 1)
        results["seeds"][s] = {
            "baseline_A_mbon_spikes": base_a["mbon_spikes"],
            "recall_mbon_spikes": rec["mbon_spikes"] if cond != "scrambled-dopamine" else rec_a["mbon_spikes"],
            "learn_factor": round(learn, 4),
        }
        print(f"  [seed {s}] learn_factor = {learn:.3f}")
        # checkpoint per seed
        with open(os.path.join(OUT, f"NECTAR-004_{cond}_s{s}.json"), "w") as f:
            json.dump({**results["seeds"][s], "condition": cond, "seed": s},
                      f, indent=2)
    vals = [results["seeds"][s]["learn_factor"] for s in results["seeds"]]
    results["learn_factor_mean"] = round(float(np.mean(vals)), 4)
    results["learn_factor_std"] = round(float(np.std(vals)), 4) if len(vals) > 1 else None
    results["n_seeds"] = len(vals)
    return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", nargs="+", default=CONDITIONS)
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    aggregate = []
    for cond in args.conditions:
        # skip fully-checkpointed condition unless forced
        done = all(os.path.exists(os.path.join(OUT, f"NECTAR-004_{cond}_s{s}.json"))
                   for s in args.seeds)
        if done and not args.force:
            print(f"[skip] {cond} (checkpoints exist)")
            continue
        print(f"\n=== {cond} ({len(args.seeds)} seeds) ===")
        res = run_condition(cond, args.seeds)
        aggregate.append(res)

    if aggregate:
        with open(os.path.join(OUT, "NECTAR-004_learning_controls.json"), "w") as f:
            json.dump(aggregate, f, indent=2, default=str)
        for r in aggregate:
            print(f"  {r['condition']:<20} mean={r['learn_factor_mean']} "
                  f"std={r['learn_factor_std']}")
        summary = {r["condition"]: {"mean": r["learn_factor_mean"],
                                    "std": r["learn_factor_std"]} for r in aggregate}
        audit_event("exp.nectar_004_learning_controls", {"conditions": summary})
    else:
        print("nothing to run")


if __name__ == "__main__":
    main()