"""EXP-LEARN-001: Olfactory associative learning in the mushroom body.

Design v2 — the mushroom body stores odor identity as a SPARSE KENYON CELL
ensemble (odor code) that MBONs read out. Driving sensory GRNs alone does not
reach KCs within short runtimes, so this experiment:

  (a) MEASURES sensory propagation depth (do sugar GRN drive any KC/MBON?)
  (b) TESTS associativity at the odor-code layer: two fixed KC ensembles
      (odor A, odor B); only A is reward-paired (PAM-like dopamine).
      Prediction: A's MBON output rises after reward; B's does not.

Protocol (full v783 brain, Brian2 CPU):
  1. sensory_probe      drive taste_sweet GRNs (200 Hz), report KC/MBON depth
  2. baseline_A / _B    drive KC ensembles, measure MBON output
  3. acquisition_A      drive KC_A, record active KCs, apply reward (x1.5)
  4. recall_A           fresh load + learned weights, drive KC_A, remeasure
  5. recall_B           fresh load + learned weights, drive KC_B (control)

Pass criteria:  learn_factor > 1.05  AND  control_drift < 1.10
All metrics measured empirically. No fabricated numbers.
"""

import sys
import os
import time
import json
import random

import numpy as np

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from services.nectar.simulator.brian2_backend import Brian2Backend
from services.nectar.memory.flymemory import FlyMemory
from services.nectar.connectome.atlas import NeuronAtlas
from services.nectar.safety.audit import audit_event

CONN = r"D:\orion\data\nectar\connectome\Connectivity_783.parquet"
COMP = r"D:\orion\data\nectar\connectome\Completeness_783.csv"
DURATION_S = 0.4
DRIVE_RATE_HZ = 200.0
N_ODOR_A = 30
N_ODOR_B = 30
SEED = 2026


def _run_phase(
    backend, stimulus_indices, memory, label, rate=DRIVE_RATE_HZ, apply_learned=False
):
    backend.reset()
    backend.load_connectome(CONN, {"completeness_path": COMP})
    if apply_learned:
        mem_result = backend.apply_memory(memory)
    else:
        mem_result = None
    backend.stimulate(stimulus_indices, label, DURATION_S, rate=rate)
    t0 = time.time()
    backend.run(DURATION_S)
    trains = backend.spike_trains()
    mbon = memory.get_active_mbon(trains)
    mbon_spikes = sum(v["spikes"] for v in mbon.values())
    n_kc = len(memory.get_active_kc(trains))
    print(
        f"  [{label}] n_spiking={len(trains):>6} | "
        f"MBON active={len(mbon):>2} | MBON spikes={mbon_spikes:>6} | "
        f"KC fired={n_kc:>4} | wall={time.time() - t0:.1f}s"
    )
    return {
        "label": label,
        "n_spiking": len(trains),
        "n_active_kc": n_kc,
        "mbon_active": len(mbon),
        "mbon_spikes": mbon_spikes,
        "all_mbon_spikes": {str(k): v["spikes"] for k, v in mbon.items()},
        "synapses_modified_at_load": (
            mem_result["synapses_modified"] if mem_result else 0
        ),
        "wall_s": time.time() - t0,
    }


def main(n_repeat: int = 1):
    memory = FlyMemory()
    memory.reset_memory()
    rng = random.Random(SEED)

    kc_pool = sorted(memory.kc_indices)
    n_odor_a = min(N_ODOR_A, len(kc_pool) // 2)
    n_odor_b = min(N_ODOR_B, len(kc_pool) // 2)
    odor_a = rng.sample(kc_pool[: len(kc_pool) // 2], n_odor_a)
    odor_b = rng.sample(kc_pool[len(kc_pool) // 2 :], n_odor_b)

    atlas = NeuronAtlas()
    sensory = atlas.stimulus_indices("taste_sweet")
    print(f"[atlas] taste_sweet mapped: {len(sensory)} GRNs")
    print(f"[odor code] A: {n_odor_a} KC, B: {n_odor_b} KC (disjoint)")
    print(
        f"[memory] KC={len(memory.kc_indices)} MBON={len(memory.mbon_indices)} "
        f"PAM={len(memory.pam_indices)} PPL={len(memory.ppl_indices)}"
    )

    backend = Brian2Backend(seed=SEED)

    for rep in range(n_repeat):
        print(f"\n=== REPETITION {rep + 1}/{n_repeat} ===")

        probe = _run_phase(backend, sensory, memory, "sensory_probe_GRNs")

        base_a = _run_phase(backend, odor_a, memory, "baseline_odorA")
        base_b = _run_phase(backend, odor_b, memory, "baseline_odorB")

        acq = _run_phase(backend, odor_a, memory, "acquisition_odorA")
        reward = memory.apply_reward(
            odor_a, strength=1.5, label="EXP-LEARN-001 reward (odor A)"
        )
        print(
            f"  [reward] {reward['synapses_modified']} KC->MBON synapses "
            f"strengthened (x1.5) for {len(odor_a)} driven KC"
        )

        recall_a = _run_phase(
            backend, odor_a, memory, "recall_odorA_learned", apply_learned=True
        )
        recall_b = _run_phase(
            backend, odor_b, memory, "recall_odorB_control", apply_learned=True
        )

        learn_factor = recall_a["mbon_spikes"] / max(base_a["mbon_spikes"], 1)
        control_drift = recall_b["mbon_spikes"] / max(base_b["mbon_spikes"], 1)
        n_mods = sum(1 for v in memory.get_weight_multipliers().values() if v != 1.0)

        result = {
            "experiment": "EXP-LEARN-001",
            "data": "v783",
            "design": "odor-code associative learning (KC ensembles)",
            "duration_s": DURATION_S,
            "drive_rate_hz": DRIVE_RATE_HZ,
            "n_odor_a_kc": len(odor_a),
            "n_odor_b_kc": len(odor_b),
            "repetition": rep + 1,
            "sensory_probe": probe,
            "baseline_odorA": base_a,
            "baseline_odorB": base_b,
            "acquisition": acq,
            "reward": reward,
            "recall_odorA": recall_a,
            "recall_odorB": recall_b,
            "learn_factor": round(learn_factor, 4),
            "control_drift": round(control_drift, 4),
            "synapses_with_modified_weights": n_mods,
            "sensory_reaches_kc": probe["n_active_kc"] > 0,
            "sensory_reaches_mbon": probe["mbon_active"] > 0,
            "learned": learn_factor > 1.05,
            "control_stable": control_drift < 1.10,
            "measured": True,
            "mock": False,
        }
        print(f"\n  learn_factor={learn_factor:.3f} (odorA MBON recall/baseline)")
        print(f"  control_drift={control_drift:.3f} (odorB MBON recall/baseline)")
        print(f"  modified_synapses={n_mods}")
        print(
            f"  sensory_probe -> KC fired: {probe['n_active_kc']}, "
            f"MBON active: {probe['mbon_active']}"
        )

    os.makedirs(r"D:\orion\data\nectar\results", exist_ok=True)
    path = r"D:\orion\data\nectar\results\EXP-LEARN-001.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    audit_event(
        "exp.learn_001",
        {
            "learn_factor": result["learn_factor"],
            "control_drift": result["control_drift"],
            "synapses_modified": result["synapses_with_modified_weights"],
            "sensory_reaches_kc": result["sensory_reaches_kc"],
            "sensory_reaches_mbon": result["sensory_reaches_mbon"],
        },
    )
    print(f"\n[saved] {path}")
    print(f"[audit] EXP-LEARN-001 event written to nectar_audit.jsonl")
    return result


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    main(n_repeat=n)
