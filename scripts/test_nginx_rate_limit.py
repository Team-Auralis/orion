import requests
import time

URL = "https://localhost:443/v1/incidents"
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_rate_limit():
    print("=== Nginx End-to-End Rate Limit Test ===")
    
    print("\n[+] Testing burst from Client A (Real IP: 127.0.0.1)")
    blocked = False
    for i in range(25):
        resp = requests.post(URL, json={"type": "TEST", "message": "flood", "location": {"latitude": 0, "longitude": 0}, "source": "test"}, verify=False)
        if resp.status_code == 429:
            blocked = True
            print(f"    -> Client A blocked on request {i+1} as expected (429 Too Many Requests)")
            break
        elif resp.status_code != 200:
            print(f"    -> Unexpected status: {resp.status_code}")
            break
    
    if not blocked:
        print("FAIL: Client A was not rate limited!")
        return

    print("\n[+] Testing spoofed X-Forwarded-For bypass from Client A...")
    headers = {"X-Forwarded-For": "203.0.113.5", "X-Real-IP": "203.0.113.5"}
    resp = requests.post(URL, json={"type": "TEST", "message": "flood", "location": {"latitude": 0, "longitude": 0}, "source": "test"}, headers=headers, verify=False)
    
    if resp.status_code == 429:
        print("PASS: Spoofed headers ignored. Client A still blocked!")
    else:
        print(f"FAIL: Spoofed headers allowed bypass! Status: {resp.status_code}")

if __name__ == '__main__':
    test_rate_limit()

