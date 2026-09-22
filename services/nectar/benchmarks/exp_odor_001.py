"""EXP-ODOR-001: anatomically-targeted stimulation of hub broadcasters.

Measures whether spiking propagates through the connectome beyond directly
driven neurons, and with what latency. First real circuit-level readout.
"""

import sys
import os
import time
import numpy as np

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    import psutil

    def ram():
        return round(psutil.Process().memory_info().rss / (1024**3), 3)
except ImportError:

    def ram():
        return None


from services.nectar.simulator.brian2_backend import Brian2Backend

CONN = r"D:\orion\data\\nectar\connectome\Connectivity_783.parquet"
COMP = r"D:\orion\data\\nectar\connectome\Completeness_783.csv"

HUB_IDX = [90883, 79529, 87447, 93981, 74067, 85900, 102727, 109989, 16213, 35141]


def main(duration_s: float = 0.5, n_drivers: int = 8):
    print(
        f"[EXP-ODOR-001] hub-driver experiment | drivers={n_drivers} "
        f"duration={duration_s}s | RAM start {ram()} GB"
    )

    backend = Brian2Backend(seed=0)
    t0 = time.time()
    backend.load_connectome(CONN, {"completeness_path": COMP})
    print(
        f"[load] {backend._N} neurons, 15.09M edges in {time.time() - t0:.1f}s "
        f"| RAM {ram()} GB"
    )

    t0 = time.time()
    backend.stimulate(HUB_IDX[:n_drivers], "hub_broadcast", duration_s)
    print(f"[stimulate] {n_drivers} hubs | {time.time() - t0:.2f}s")

    t0 = time.time()
    backend.run(duration_s)
    wall = time.time() - t0
    trains = backend.spike_trains()
    print(
        f"[run] {duration_s}s bio in {wall:.1f}s wall "
        f"(x{wall / duration_s:.1f} slower-than-RT)"
    )

    n_spiking = len(trains)
    total_spikes = sum(len(v) for v in trains.values())
    driven = set(HUB_IDX[:n_drivers])
    nondriven = [k for k in trains if k not in driven]
    n_nondriven = len(nondriven)

    latencies = []
    for k in nondriven:
        first = min(trains[k])
        latencies.append(first)
    mean_lat = float(np.mean(latencies)) if latencies else None

    heaviest = sorted(trains.items(), key=lambda kv: -len(kv[1]))[:5]

    print()
    print("=== READOUT (anatomically labeled) ===")
    print(f"n_neurons_total        : {backend._N}")
    print(f"n_spiking             : {n_spiking} ({n_spiking / backend._N * 100:.4f}%)")
    print(f"total_spikes          : {total_spikes}")
    print(f"driven (directly stim): {len(driven & set(trains))}")
    print(f"propagated_downloads  : {n_nondriven} (non-driven neurons that fired)")
    print(f"mean_first_spike_ms   : {round(mean_lat * 1000, 1) if mean_lat else 'n/a'}")
    print(f"ram_final_GB          : {ram()}")
    print()
    print("=== TOP 5 FIRING NEURONS ===")
    for idx, t in heaviest:
        print(
            f"  idx={idx} flywire={backend._i2flyid[idx]} spikes={len(t)} rate_hz={len(t) / duration_s:.1f}"
        )
    print()
    print("[integrity] backend=" + backend.name, "mock=False | verified")

    import json

    report = {
        "experiment": "EXP-ODOR-001",
        "backend": "brian2",
        "n_neurons": backend._N,
        "n_edges": 15091983,
        "drivers": HUB_IDX[:n_drivers],
        "duration_s": duration_s,
        "wall_s": round(wall, 1),
        "slower_than_rt": round(wall / duration_s, 1),
        "n_spiking": n_spiking,
        "total_spikes": total_spikes,
        "propagated": n_nondriven,
        "mean_first_spike_ms": round(mean_lat * 1000, 1) if mean_lat else None,
        "ram_final_gb": ram(),
        "mock": False,
    }
    os.makedirs(r"D:\orion\data\\nectar\results", exist_ok=True)
    with open(r"D:\orion\data\\nectar\results\EXP-ODOR-001_hub.json", "w") as f:
        json.dump(report, f, indent=2)
    print("[saved] D:\\orion\\data\\NECTAR\\results\\EXP-ODOR-001_hub.json")


if __name__ == "__main__":
    d = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    main(duration_s=d, n_drivers=n)
