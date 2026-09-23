"""Phase-1 end-to-end smoke test on a small connectome subset.

Measures real wall time and peak RAM on THIS machine. No fabricated
metrics. Run:  python services/nectar/benchmarks/smoke_brian2.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

try:
    import psutil
except ImportError:
    psutil = None

import numpy as np

from services.nectar.connectome.subset import build_subset
from services.nectar.simulator.brian2_backend import Brian2Backend

CONN = r"D:\orion\data\\nectar\connectome\Connectivity_783.parquet"
COMP = r"D:\orion\data\\nectar\connectome\Completeness_783.csv"
WORK = r"D:\orion\data\\nectar\subsets"


def peak_ram_mb():
    if psutil is None:
        return None
    return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)


def main(n_neurons: int = 2000, duration_s: float = 0.5,
         n_drivers: int = 5):
    subset = build_subset(CONN, COMP, n_neurons=n_neurons, seed=42,
                          out_dir=WORK)
    print(f"[subset] {subset['n_neurons']} neurons, "
          f"{subset['n_connections']} edges")

    deg_out = np.bincount(subset["pre_idx"], minlength=subset["n_neurons"])
    deg_in = np.bincount(subset["post_idx"], minlength=subset["n_neurons"])
    drivers = deg_out.argsort()[::-1][:n_drivers]
    print(f"[drivers] top out-degree neurons (idx): {list(drivers)} "
          f"out={deg_out[drivers]} in={deg_in[drivers]}")

    sub_conn = os.path.join(WORK, f"connectivity_{n_neurons}.parquet")
    sub_comp = os.path.join(WORK, f"completeness_{n_neurons}.csv")

    backend = Brian2Backend()
    backend.load_connectome(sub_conn, {"completeness_path": sub_comp})
    print(f"[load] brian2 network built | n={backend._N} | "
          f"RAM {peak_ram_mb()} MB")

    backend.stimulate(list(drivers), "hub_driver", duration_s)

    backend.run(duration_s)
    elapsed = backend._last_walltime_s
    trains = backend.spike_trains()
    total = sum(len(v) for v in trains.values())
    print(f"[run] {duration_s}s bio-time in {elapsed:.2f}s wall "
          f"(x{elapsed / max(duration_s, 1e-9):.1f} slower than real-time)")

    print(f"[readout] spikes={total} spiking_neurons={len(trains)}/"
          f"{backend._N} | RAM {peak_ram_mb()} MB")

    active_rate = len(trains) / backend._N * 100
    print(f"[evidence-check] active=% of subset: {active_rate:.2f}%")
    print("[health]", backend.health())


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    d = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    main(n_neurons=n, duration_s=d)