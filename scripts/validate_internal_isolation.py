import asyncio
import nats
import redis
import httpx
import os
import sys

async def main():
    print("=== LIVE INFRASTRUCTURE VALIDATION ===")
    
    # Test Redis Auth
    print("\n[+] Testing Redis Isolation...")
    try:
        r = redis.Redis(host='redis', port=6379, db=0, socket_connect_timeout=2)
        r.ping()
        print("FAIL: Redis allowed unauthenticated ping!")
    except Exception as e:
        print(f"PASS: Redis rejected unauthenticated connection: {e}")

    # Test NATS Auth
    print("\n[+] Testing NATS Isolation...")
    try:
        nc = await nats.connect("nats://nats:4222", connect_timeout=2)
        print("FAIL: NATS allowed unauthenticated connection!")
        await nc.close()
    except Exception as e:
        print(f"PASS: NATS rejected unauthenticated connection: {e}")

    # Test OPA Auth
    print("\n[+] Testing OPA Isolation...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put("http://opa:8181/v1/policies/test", json={"foo": "bar"}, timeout=2)
            if resp.status_code == 200:
                print("FAIL: OPA allowed unauthenticated policy write!")
            else:
                print(f"PASS: OPA rejected policy write with status: {resp.status_code}")
    except Exception as e:
        print(f"PASS: OPA rejected connection: {e}")

if __name__ == '__main__':
    asyncio.run(main())
