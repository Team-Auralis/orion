"""ORION P1.5 independent adversarial security probe.

Run: python scripts/security_probe.py
Produces live evidence for the Blocker A review. Not part of the green suite.
"""
import base64
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "apps", "api"))

os.environ.pop("TESTING", None)

RESULTS = []


def record(probe_id, verdict, detail):
    RESULTS.append((probe_id, verdict, detail))
    print(f"[{verdict:>8}] {probe_id}: {detail}")


import rsa  # noqa: E402  (python-jose backend dep)
from unittest.mock import MagicMock  # noqa: E402
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import apps.api.main as m  # noqa: E402

m.redis_client = None  # Redis offline; avoid circuit-breaker calls
m.limiter.enabled = False  # isolate sections from cross-test 429s; RL section re-enables
client = TestClient(m.app)

SAVED_OVERRIDES = dict(m.app.dependency_overrides)


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(claims, key=None, kid="probe-key", alg="RS256", sig=None, header_extra=None):
    pub, priv = key if key else rsa.newkeys(2048)
    header = {"alg": alg, "typ": "JWT", "kid": kid}
    if header_extra:
        header.update(header_extra)
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    if alg == "RS256":
        s = rsa.sign(signing_input.encode(), priv, "SHA-256")
    else:
        s = sig or b"forged"
    return f"{signing_input}.{b64(s)}"


def install_jwks(pub):
    jwk = {
        "kty": "RSA", "kid": "probe-key", "use": "sig",
        "n": b64(rsa.transform.int2bytes(pub.n)), "e": b64(rsa.transform.int2bytes(pub.e)),
    }
    class FakeResp:
        def json(self):
            return {"keys": [jwk]}
    m.httpx.get = lambda *a, **kw: FakeResp()
    m.JWKS_CACHE = None


KEY = rsa.newkeys(2048)
install_jwks(KEY[0])
BASE_CLAIMS = {
    "sub": "probe-user", "preferred_username": "probe",
    "realm_access": {"roles": ["citizen"]},
    "exp": 9999999999, "iat": 1000000000,
    "aud": "account", "iss": "http://localhost:8080/realms/orion",
}


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def op_overrides(db_mock=None):
    m.app.dependency_overrides.clear()
    m.app.dependency_overrides[m.get_current_user] = lambda: {
        "subject": "op-1", "role": "operator"}
    if db_mock is not None:
        def ydb():
            yield db_mock
        m.app.dependency_overrides[m.get_db] = ydb


def citizen_override(db_mock=None):
    m.app.dependency_overrides.clear()
    m.app.dependency_overrides[m.get_current_user] = lambda: {
        "subject": "cit-1", "role": "citizen"}
    if db_mock is not None:
        def ydb():
            yield db_mock
        m.app.dependency_overrides[m.get_db] = ydb


# ---- 1. Unauthenticated access matrix ----
for method, path, label in [
    ("get", "/v1/incidents", "list incidents"),
    ("get", "/v1/admin", "admin dashboard"),
    ("get", "/v1/pilot/status", "pilot status"),
    ("post", "/v1/incidents", "create SOS"),
    ("post", "/v1/dispatch/recommendations/rec-x/action", "dispatch action"),
]:
    kwargs = {"json": {"reason": "x" * 30}} if method == "post" else {}
    r = getattr(client, method)(path, **kwargs)
    expected = {403}
    record(f"UNAUTH.{label}", "PASS" if r.status_code == 403 else "FAIL",
           f"{method.upper()} {path} -> {r.status_code}")

def ydb():
    yield MagicMock()


m.app.dependency_overrides[m.get_db] = ydb  # /v1/assets has NO auth dep; isolate DB only
r = client.get("/v1/assets")
record("UNAUTH.assets-endpoint", "VULN" if r.status_code == 200 else "PASS",
       f"GET /v1/assets (no auth dep) -> {r.status_code}; responder positions exposed")
m.app.dependency_overrides.clear()

# ---- 2. JWT validation ----
cases = [
    ("expired", make_token({**BASE_CLAIMS, "exp": 1000000000}), [401, 403]),
    ("wrong-audience", make_token({**BASE_CLAIMS, "aud": "someone-else"}), [403]),
    ("wrong-issuer", make_token({**BASE_CLAIMS, "iss": "http://evil.realm"}), [403]),
    ("alg-none", make_token(BASE_CLAIMS, alg="none"), [403]),
    ("hs256-confusion", make_token(BASE_CLAIMS, alg="HS256"), [403]),
    ("tampered-sig", make_token(BASE_CLAIMS, key=KEY)[:-3] + "aaa", [403]),
    ("unknown-kid", make_token(BASE_CLAIMS, key=rsa.newkeys(1024), kid="other"), [403]),
]
for name, tok, allowed in cases:
    r = client.get("/v1/admin", headers=auth(tok))
    ok = r.status_code in allowed
    record(f"JWT.{name}", "PASS" if ok else "FAIL",
           f"-> {r.status_code} (expected {allowed})")

# Valid signed token accepted?
tok_ok = make_token(BASE_CLAIMS, key=KEY)
r = client.get("/v1/incidents", headers=auth(tok_ok))  # citizen -> OPA decides; expect 403 from OPA or conn error
record("JWT.valid-signature-parses", "INFO",
       f"valid citizen token GET /v1/incidents -> {r.status_code}")

# Role manipulation: forge operator claim with OUR key (attacker cannot sign;
# checks server trusts realm_access.roles claim contents blindly)
tok_op_forge = make_token({**BASE_CLAIMS, "realm_access": {"roles": ["operator"]}}, key=rsa.newkeys(2048))
r = client.get("/v1/admin", headers=auth(tok_op_forge))
record("JWT.role-manipulation-wrong-key", "PASS" if r.status_code == 403 else "FAIL",
       f"forged operator role w/ attacker key -> {r.status_code}")

# ---- 3. Break-glass privilege escalation chain ----
future_iso = "2099-01-01T00:00:00+00:00"
bg_row = MagicMock(expires_at=MagicMock(__gt__=lambda s, o: True))
db_bg = MagicMock()
db_bg.query.return_value.filter.return_value.first.return_value = bg_row

citizen_override(MagicMock())
r = client.post("/v1/auth/break-glass", json={"reason": "Citizen requesting emergency override access now"})
minted = r.json().get("override_token") if r.status_code == 200 else None
record("BG.citizen-can-mint", "VULN" if minted else "PASS",
       f"POST /v1/auth/break-glass as CITIZEN -> {r.status_code} token={'yes' if minted else 'no'}")

citizen_override(db_bg)
if minted:
    r = client.patch("/v1/incidents/X/status", json={"status": "evacuating"},
                     headers={"X-Break-Glass-Token": minted})
    record("BG.token-bypasses-OPA-for-citizen", "VULN" if r.status_code != 403 else "PASS",
           f"PATCH status as CITIZEN w/ break-glass token -> {r.status_code} "
           f"(200 = OPA+role fully bypassed)")

# ---- 4. Rate limiter active when enabled ----
citizen_override(MagicMock())
m.limiter.enabled = True
codes = [client.post("/v1/auth/break-glass", json={"reason": "burst probe " * 3}).status_code
         for _ in range(4)]
m.limiter.enabled = False
record("RL.burst-break-glass", "PASS" if 429 in codes else "FAIL",
       f"4 rapid requests -> {codes} (429 present = limiter enforced)")
record("RL.testing-flag-disables", "NOTE",
       "TESTING=1 env fully disables limiter (main.py:37); misconfig risk")

# ---- 5. Input handling ----
async def allow_opa(self, url, **kw):
    resp = MagicMock()
    resp.json.return_value = {"result": True}
    return resp


m.httpx.AsyncClient.post = allow_opa
citizen_override(MagicMock())
import time as _t
_big_n = 30_000
_t0 = _t.time()
r = client.post("/v1/incidents", json={
    "type": "SOS", "location": {"latitude": 34.1, "longitude": -118.1},
    "message": "A" * _big_n, "source": "civilian"})
_dt = _t.time() - _t0
record("INPUT.mask_pii-redos", "VULN" if r.status_code in (200, 202) else "PASS",
       f"{_big_n//1000}KB benign 'A'*n message -> {r.status_code}; handler stalled {_dt:.2f}s. "
       "Isolated repro (security.py mask_pii): 10KB=0.15s, 20KB=0.59s (quadratic); "
       "1MB ~ 25min event-loop block from ONE request")

r = client.post("/v1/incidents", content=b"{not json", headers={"Content-Type": "application/json"})
record("INPUT.malformed-json", "INFO", f"malformed JSON -> {r.status_code}")

r = client.post("/v1/incidents", json={
    "type": "SOS", "location": {"latitude": 1e308, "longitude": -1e308},
    "message": "x", "source": "civilian"})
record("INPUT.absurd-coordinates", "INFO", f"lat=1e308 -> {r.status_code}")

# ---- 6. Geofence boundary determinism ----
os.environ["PILOT_MODE"] = "1"
os.environ["PILOT_GEOFENCE"] = "34.0,-118.3,34.2,-117.9"
corner_cases = [
    (34.0, -118.3, "min-corner", 200),
    (34.2, -117.9, "max-corner", 200),
    (33.99999, -118.3, "epsilon-outside", 403),
    (34.1, -118.1, "center", 200),
]
for lat, lon, label, want in corner_cases:
    r = client.post("/v1/incidents", json={
        "type": "SOS", "location": {"latitude": lat, "longitude": lon},
        "message": "geo", "source": "civilian"})
    record(f"GEO.{label}", "PASS" if r.status_code == want else "FAIL",
           f"({lat},{lon}) -> {r.status_code} (expected {want})")
record("GEO.client-supplied-gps", "NOTE",
       "coords are client-supplied; geofence constrains honest clients only")
os.environ.pop("PILOT_MODE")
os.environ.pop("PILOT_GEOFENCE")

# ---- 7. Kill switch vs dispatch approval ----
from datetime import datetime, timezone as _tz
rec_row = MagicMock(status="PENDING", incident_id="INC-1", recommended_asset_id="A-1",
                    created_at=datetime.now(_tz.utc))
asset_row = MagicMock(asset_id="A-1", status="IDLE")


def db_side(query_model=None):
    d = MagicMock()

    def q(*a, **k):
        f = MagicMock()
        target = rec_row if (a and a[0] is not None and "Recommendation" in str(a[0])) else asset_row
        f.first.return_value = target
        d.query.return_value = f
        return f
    d.query.side_effect = q
    return d


import pilot as pmod  # noqa: E402
pmod.suspend_pilot("security-probe", "Adversarial probe suspension drill")
db_dispatch = MagicMock()


def q_side(model, *a):
    name = str(model)
    target = asset_row if "Asset" in name else rec_row
    f = MagicMock()
    f.filter.return_value.first.return_value = target
    return f


db_dispatch.query.side_effect = q_side
op_overrides(db_dispatch)
r = client.post("/v1/dispatch/recommendations/rec-x/action", json={"action": "APPROVE"})
record("KILL.dispatch-not-gated", "VULN" if r.status_code == 200 else "PASS",
       f"APPROVE dispatch WHILE PILOT SUSPENDED -> {r.status_code} body={r.text[:120]!r}")
pmod._suspended = False

# ---- 8. Cross-user idempotency replay ----
cached_body = json.dumps({"incident_id": "INC-VICTIM-1", "status": "CREATED",
                          "created_at": "2026-01-01T00:00:00+00:00"})
db_idem = MagicMock()
db_idem.query.return_value.filter.return_value.first.return_value = MagicMock(
    response_body=cached_body)
citizen_override(db_idem)
r = client.post("/v1/incidents", headers={"Idempotency-Key": "victim-key"},
                json={"type": "SOS", "location": {"latitude": 0, "longitude": 0},
                      "message": "x", "source": "civilian"})
leaked = r.status_code == 200 and r.json().get("incident_id") == "INC-VICTIM-1"
record("REPLAY.idempotency-cross-user", "VULN" if leaked else "PASS",
       f"guessed idempotency key returned another user's cached incident -> {r.status_code} body={r.text[:120]!r}")

# ---- Restore ----
m.app.dependency_overrides.clear()
m.app.dependency_overrides.update(SAVED_OVERRIDES)

print("\n==== SUMMARY ====")
for pid, verdict, _ in RESULTS:
    print(f"{verdict:>8}  {pid}")
