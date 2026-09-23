import requests
import random
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("ORION Multi-Valued Computing Telemetry Test (Live via Nginx Proxy)")

states = [random.randint(0, 3) for _ in range(50000)]
payload = {
    "device_id": "AEGIS-MVT-01",
    "states": states
}

try:
    response = requests.post("https://localhost:443/v1/telemetry/compress", json=payload, verify=False)
    if response.status_code == 200:
        data = response.json()
        print("\n--- RESULTS FROM ORION API ---")
        print(f"Original JSON array size: {data['json_size_bytes']} bytes")
        print(f"Quaternary Packing (2 bits): {data['quaternary_size_bytes']} bytes (Time: {data['quaternary_time_ms']:.4f} ms)")
        print(f"Ternary Packing (5 trits): {data['ternary_size_bytes']} bytes (Time: {data['ternary_time_ms']:.4f} ms)")
        
        savings = 100 - (data['quaternary_size_bytes'] / data['json_size_bytes'] * 100)
        print(f"\nConclusion: Quaternary packing inside ORION API reduces telemetry payload size by {savings:.2f}%.")
    else:
        print(f"Error {response.status_code}: {response.text}")
except Exception as e:
    print(f"Connection failed: {e}")
