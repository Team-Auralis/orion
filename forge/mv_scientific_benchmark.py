import time
import json
import random
import statistics
import struct
import zlib
try:
    import msgpack
except ImportError:
    import subprocess
    subprocess.check_call(['pip', 'install', 'msgpack'])
    import msgpack

print("ORION FORGE: Multi-Valued Scientific Benchmark (Phase 1-4)")

def generate_distribution(size, dist_type="uniform"):
    if dist_type == "uniform":
        return [random.randint(0, 3) for _ in range(size)]
    elif dist_type == "mostly-zero":
        return [0 if random.random() < 0.9 else random.randint(1, 3) for _ in range(size)]
    elif dist_type == "bursty":
        base = [0] * size
        for _ in range(size // 100): # 1% burst
            idx = random.randint(0, size-10)
            for i in range(10): base[idx+i] = 3
        return base

def benchmark_packing(states, iterations=30):
    results = {}
    
    # 1. JSON
    t0 = time.perf_counter()
    for _ in range(iterations): json_b = json.dumps(states).encode()
    t_json = (time.perf_counter() - t0) / iterations * 1000
    results['json'] = {'size': len(json_b), 'time_ms': t_json}

    # 2. MessagePack (Strong Baseline)
    t0 = time.perf_counter()
    for _ in range(iterations): mp_b = msgpack.packb(states)
    t_mp = (time.perf_counter() - t0) / iterations * 1000
    results['msgpack'] = {'size': len(mp_b), 'time_ms': t_mp}

    # 3. Zlib Compressed JSON (Strong Baseline)
    t0 = time.perf_counter()
    for _ in range(iterations): z_b = zlib.compress(json.dumps(states).encode())
    t_z = (time.perf_counter() - t0) / iterations * 1000
    results['zlib_json'] = {'size': len(z_b), 'time_ms': t_z}

    # 4. Quaternary Packed (2-bits)
    t0 = time.perf_counter()
    for _ in range(iterations):
        q_b = bytearray((len(states) + 3) // 4)
        for i, s in enumerate(states):
            q_b[i // 4] |= (s & 0b11) << ((i % 4) * 2)
    t_q = (time.perf_counter() - t0) / iterations * 1000
    results['quaternary_packed'] = {'size': len(q_b), 'time_ms': t_q}

    # 5. Ternary Packed (5 trits per byte)
    t0 = time.perf_counter()
    for _ in range(iterations):
        t_b = bytearray((len(states) + 4) // 5)
        for i in range(0, len(states), 5):
            chunk = states[i:i+5]
            val = 0
            mult = 1
            for s in chunk:
                val += min(s, 2) * mult
                mult *= 3
            t_b[i // 5] = val
    t_t = (time.perf_counter() - t0) / iterations * 1000
    results['ternary_packed'] = {'size': len(t_b), 'time_ms': t_t}

    # 6. Binary packed (1-bit, truncating > 1 for fair 2-state comparison)
    t0 = time.perf_counter()
    for _ in range(iterations):
        b_b = bytearray((len(states) + 7) // 8)
        for i, s in enumerate(states):
            b_b[i // 8] |= (min(s, 1)) << (i % 8)
    t_b_time = (time.perf_counter() - t0) / iterations * 1000
    results['binary_packed_1bit'] = {'size': len(b_b), 'time_ms': t_b_time}

    return results

print("\n--- Phase 4: Telemetry Scaling (Uniform) ---")
for scale in [100, 10_000, 50_000]:
    states = generate_distribution(scale, "uniform")
    res = benchmark_packing(states)
    print(f"Scale: {scale} states")
    for k, v in res.items():
        print(f"  {k:20} -> {v['size']:8} bytes | {v['time_ms']:.4f} ms")

print("\n--- Phase 28: Distributions (50,000 states) ---")
for dist in ["uniform", "mostly-zero", "bursty"]:
    states = generate_distribution(50000, dist)
    res = benchmark_packing(states)
    print(f"Dist: {dist}")
    for k, v in res.items():
        print(f"  {k:20} -> {v['size']:8} bytes | {v['time_ms']:.4f} ms")

