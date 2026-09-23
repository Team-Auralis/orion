import sys
import time
import json
import random
import numpy as np

def benchmark(name, func, iterations=1000):
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    end = time.perf_counter()
    return (end - start) * 1000 / iterations

print("=== ORION FORGE: MULTI-VALUED COMPUTING RESEARCH ===")
print("Running benchmarks...")

# 1. EDGE AI
print("\n--- 1. EDGE AI ---")
N = 1000
fp32_weights = np.random.randn(N, N).astype(np.float32)
int8_weights = np.random.randint(-127, 127, (N, N), dtype=np.int8)
# Ternary packed: 5 trits (3^5 = 243) fit in 1 byte (uint8)
ternary_packed = np.random.randint(0, 243, (N, N // 5), dtype=np.uint8)

print(f"FP32 Weights Size: {fp32_weights.nbytes / 1024 / 1024:.2f} MB")
print(f"INT8 Weights Size: {int8_weights.nbytes / 1024 / 1024:.2f} MB")
print(f"TERNARY (Packed) Size: {ternary_packed.nbytes / 1024 / 1024:.2f} MB")

def fp32_mac(): np.dot(fp32_weights[0], fp32_weights[1])
def int8_mac(): np.dot(int8_weights[0], int8_weights[1])

print(f"FP32 MAC (1k elements): {benchmark('fp32', fp32_mac):.4f} ms")
print(f"INT8 MAC (1k elements): {benchmark('int8', int8_mac):.4f} ms")
print("Ternary MAC is theoretically faster in custom ASIC, but slower in CPU due to unpacking.")

# 2. TELEMETRY ENCODING
print("\n--- 2. TELEMETRY ENCODING ---")
num_sensors = 10000
states_binary = [random.choice([0, 1]) for _ in range(num_sensors)]
states_ternary = [random.choice([0, 1, 2]) for _ in range(num_sensors)]
states_quaternary = [random.choice([0, 1, 2, 3]) for _ in range(num_sensors)]

json_bin = json.dumps(states_binary).encode('utf-8')
json_ter = json.dumps(states_ternary).encode('utf-8')
packed_bin = bytearray(num_sensors // 8) # 1 bit per state
packed_ter = bytearray(num_sensors // 5) # 5 trits per byte (3^5=243 < 256)
packed_quat = bytearray(num_sensors // 4) # 2 bits per state (4 per byte)

print(f"JSON Array (Binary): {len(json_bin)} bytes")
print(f"JSON Array (Ternary): {len(json_ter)} bytes")
print(f"Packed Binary (1 bit): {len(packed_bin)} bytes")
print(f"Packed Ternary (5 trits/byte): {len(packed_ter)} bytes")
print(f"Packed Quaternary (2 bits): {len(packed_quat)} bytes")

def pack_ternary():
    # Simulate packing 5 trits into a byte
    for i in range(0, num_sensors, 5):
        chunk = states_ternary[i:i+5]
        if len(chunk) == 5:
            val = chunk[0]*81 + chunk[1]*27 + chunk[2]*9 + chunk[3]*3 + chunk[4]
            
def pack_binary():
    # Simulate packing 8 bits into a byte
    for i in range(0, num_sensors, 8):
        chunk = states_binary[i:i+8]
        if len(chunk) == 8:
            val = sum(c << j for j, c in enumerate(chunk))

print(f"Pack Binary time: {benchmark('pack_bin', pack_binary, 100):.4f} ms")
print(f"Pack Ternary time: {benchmark('pack_ter', pack_ternary, 100):.4f} ms")

# 7. RESILIENCE / FAILURE REPRESENTATION
print("\n--- 7. RESILIENCE / FAILURE REPRESENTATION ---")
def handle_binary(state):
    if state == 1: return "OK"
    else: return "FAIL_OVER"

def handle_ternary(state):
    if state == 1: return "OK"
    elif state == 0: return "DEGRADED_MODE"
    else: return "FAIL_OVER"

print(f"Binary Logic eval: {benchmark('bin_logic', lambda: handle_binary(1)):.6f} ms")
print(f"Ternary Logic eval: {benchmark('ter_logic', lambda: handle_ternary(0)):.6f} ms")

print("\nConclusion generation ready.")
