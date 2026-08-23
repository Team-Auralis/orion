"""
ORION Red Team Probe v2 - adversarial runtime verification at current HEAD.
Bounded, local-only, TestClient-based. Prints structured findings.
"""
import sys, os, json, time, uuid, threading, concurrent.futures

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["TESTING"] = "1"
os.environ.setdefault("PILOT_MODE", "1")
os.environ.setdefault("PILOT_GEOFENCE", "33.9,-118.6,34.3,-117.8")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from apps.api import database as db_mod
from apps.api.database import Base, Incident, Asset, DispatchRecommendation, OutboxEvent, BreakGlassSession

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(ENGINE)
TestSession = sessionmaker(bind=ENGINE, autoflush=False)

RESULTS = []
def record(name, verdict, detail):
    RESULTS.append((name, verdict, detail))
    print(f"[{verdict:>18}] {name}: {detail}")

# --- App + overrides ---
from apps.api import main as m
from fastapi.testclient import TestClient

m.engine = ENGINE
m.SessionLocal = TestSession
db_mod.engine = ENGINE
db_mod.SessionLocal = TestSession

def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()
m.app.dependency_overrides[m.get_db] = override_get_db

OPA_CALLS = []
class _FakeResp:
    def __init__(self, data): self._d = data
    def json(self): return self._d

async def _fake_post(self, url, json=None, timeout=None, **kw):
    OPA_CALLS.append(json)
    inp = (json or {}).get("input", {})
    role = inp.get("role"); action = inp.get("action")
    allowed = role == "operator" or (role == "citizen" and action == "sos:create")
    return _FakeResp({"result": allowed})
import httpx
httpx.AsyncClient.post = _fake_post

OPERATOR = {"subject": "op-redteam", "role": "operator", "username": "op"}
CITIZEN = {"subject": "cit-redteam", "role": "citizen", "username": "cit"}

def install_user(u):
    m.app.dependency_overrides[m.get_current_user] = lambda request=None: u

client = TestClient(m.app, raise_server_exceptions=False)

def seed_world():
    db = TestSession()
    db.query(Incident).delete(); db.query(Asset).delete()
    db.query(DispatchRecommendation).delete(); db.query(OutboxEvent).delete()
    db.query(BreakGlassSession).delete()
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    for aid in ("RT-A1", "RT-A2"):
        db.add(Asset(asset_id=aid, type="AMBULANCE",
                     latitude=34.05, longitude=-118.24, status="IDLE", version=1))
    inc = Incident(id="RT-INC-1", type="fire",
                   message="rt", latitude=34.05, longitude=-118.24, status="OPEN",
                   user_id="cit", created_at=now)
    db.add(inc); db.commit(); db.close()

# =========================================================
print("\n=== PHASE 1: ATTACK SURFACE (route/deps enumeration) ===")
routes = []
for r in m.app.routes:
    if hasattr(r, "methods") and hasattr(r, "path"):
        deps = [d.name for d in getattr(r, "dependant", None).dependencies] if getattr(r, "dependant", None) else []
        limiter = any(getattr(d, "name", "") == "request" for d in deps)  # slowapi injects 'request'
        routes.append((sorted(r.methods), r.path, deps))
for meths, path, deps in sorted(routes, key=lambda x: x[1]):
    print(f"  {'/'.join(meths):<6} {path:<55} deps={deps}")
record("RECON.route-map", "INFO", f"{len(routes)} routes enumerated")

# =========================================================
print("\n=== PHASE 4: BREAK-GLASS ===")
seed_world()
install_user(CITIZEN)
r = client.post("/v1/auth/break-glass", json={"reason": "redteam citizen mint attempt 1234"})
record("BG.citizen-mint", "PASS(blocked)" if r.status_code == 403 else "VULN", f"status={r.status_code} body={r.text[:120]}")

install_user(OPERATOR)
r = client.post("/v1/auth/break-glass", json={"reason": "legitimate operator drill reason here"})
bg_token = None
if r.status_code == 200:
    bg_token = r.json().get("break_glass_token") or r.json().get("token")
record("BG.operator-mint", "INFO", f"status={r.status_code} keys={list(r.json().keys())[:6]}")

if bg_token:
    # BG bypass scope: citizen-forbidden action with OPERATOR jwt + bg -> allowed (expected design)
    h = {"X-Break-Glass-Token": bg_token}
    before = len(OPA_CALLS)
    r2 = client.patch("/v1/incidents/RT-INC-1/status", json={"status": "RESOLVED"}, headers=h)
    used_opa = len(OPA_CALLS) > before
    record("BG.bypass-scope(operator)", "INFO", f"patch={r2.status_code} opa_consulted={used_opa}")
    # Identity binding: same token, different subject
    install_user({"subject": "attacker-other", "role": "citizen", "username": "x"})
    r3 = client.patch("/v1/incidents/RT-INC-1/status", json={"status": "RESOLVED"},
                      headers={"Authorization": "Bearer whatever", "X-Break-Glass-Token": bg_token})
    record("BG.identity-binding", "PASS" if r3.status_code == 403 else "VULN",
           f"other-subject reuse={r3.status_code}")
else:
    record("BG.bypass-scope", "NOT TESTED", "no token returned; inspect response shape")

install_user(CITIZEN)

# =========================================================
print("\n=== PHASE 10: IDEMPOTENCY ===")
seed_world()
hdr = {"Idempotency-Key": "rt-key-race-1"}
payload = {"type": "flood", "location": {"latitude": 34.05, "longitude": -118.24},
           "message": "race sos", "source": "mobile_app"}

# sequential replay
r1 = client.post("/v1/incidents", json=payload, headers=hdr)
id1 = r1.json().get("incident_id")
r2 = client.post("/v1/incidents", json=payload, headers=hdr)
id2 = r2.json().get("incident_id")
record("IDEM.sequential-replay", "PASS" if id1 == id2 and r2.status_code == 200 else "FAIL",
       f"id1={id1} id2={id2} s2={r2.status_code}")

# concurrent duplicate race (true parallelism)
def fire(_):
    c = TestClient(m.app, raise_server_exceptions=False)
    return c.post("/v1/incidents", json=payload, headers=hdr).json().get("incident_id")
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    ids = list(ex.map(fire, range(8)))
uniq = set(x for x in ids if x)
db = TestSession(); n_rows = db.query(Incident).filter(Incident.message == "race sos").count(); db.close()
record("IDEM.concurrent-race",
       "PARTIAL(check-then-insert race)" if len(uniq) > 1 else ("PASS" if n_rows <= 1 else "VULN"),
       f"unique_ids={len(uniq)} db_rows={n_rows} ids={ids}")

# cross-user leak
hdr2 = {"Idempotency-Key": hdr["Idempotency-Key"]}
install_user({"subject": "victim-B", "role": "citizen", "username": "b"})
r3 = client.post("/v1/incidents", json={**payload, "message": "victim B emergency"}, headers=hdr2)
leaked_id = r3.status_code == 200 and r3.json().get("incident_id") == id1
record("IDEM.cross-user-leak", "VULN(confirmed)" if leaked_id else "PASS",
       f"B posted different message w/ A's key -> status={r3.status_code} got_A_id={leaked_id}")

# =========================================================
print("\n=== PHASE 4b: BG TOKEN PLAINTEXT STORAGE ===")
if bg_token:
    db = TestSession()
    row = db.query(BreakGlassSession).filter(BreakGlassSession.user_id == "op-redteam").order_by(BreakGlassSession.id.desc()).first()
    stored_raw = bool(row) and row.token == bg_token
    db.close()
    record("BG.plaintext-in-db", "CONFIRMED" if stored_raw else "NOT CONFIRMED",
           f"raw token recoverable from DB row: {stored_raw}")

# =========================================================
print("\n=== PHASE 11: OUTBOX FALSE-ACK / SILENT LOSS ===")
seed_world()
class DeadNC:
    @property
    def is_connected(self): return False
    def publish(self, *a, **kw): raise RuntimeError("dead")

m.nc = DeadNC()
db = TestSession(); out_before = db.query(OutboxEvent).count(); db.close()
t0 = time.time()
r = client.post("/v1/incidents/RT-INC-1/status", json={"status": "RESOLVED"})
dt = time.time() - t0
db = TestSession(); out_after = db.query(OutboxEvent).count(); db.close()
record("OUTBOX.false-ack-disconnected", 
       "VULN" if r.status_code == 200 and out_after == out_before else "PASS",
       f"NATS disconnected -> status={r.status_code} ({dt*1000:.0f}ms), outbox_delta={out_after-out_before}, "
       f"client told '{str(r.json())[:60]}' while event went nowhere")

class ExplodingJS:
    def __init__(self): self.calls = []
    def publish(self, *a, **kw):
        self.calls.append(1); raise RuntimeError("jetstream down")
class HalfDeadNC:
    def __init__(self): self.core_publishes = []
    @property
    def is_connected(self): return True
    def jetstream(self): return self._js
    _js = None
    def publish(self, subj, data):
        self.core_publishes.append((subj, data))
hd = HalfDeadNC(); hd._js = ExplodingJS()
m.nc = hd
db = TestSession(); out_before = db.query(OutboxEvent).count(); db.close()
r2 = client.post("/v1/incidents/RT-INC-1/status", json={"status": "RESOLVED"})
db = TestSession(); out_after = db.query(OutboxEvent).count(); db.close()
record("OUTBOX.js-fail-fallback",
       "INFO" if r2.status_code == 200 else f"FINDING({r2.status_code})",
       f"js.publish raised -> core fallback publishes={len(hd.core_publishes)} (unacked), "
       f"http={r2.status_code}, outbox_delta={out_after-out_before}")
m.nc = None

# =========================================================
print("\n=== PHASE 5: HITL BYPASS / RACES ===")
seed_world()
from datetime import datetime, timezone, timedelta

def mk_rec(rec_id, asset_id, age_s=0):
    db = TestSession()
    db.add(DispatchRecommendation(
        id=rec_id, incident_id="RT-INC-1", recommended_asset_id=asset_id,
        reason="rt", status="PENDING",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_s)))
    db.commit(); db.close()

mk_rec("RT-R1", "RT-A1"); mk_rec("RT-R2", "RT-A1"); mk_rec("RT-REXP", "RT-A1", age_s=700)
mk_rec("RT-R3", "RT-A2"); mk_rec("RT-R4", "RT-A2")

install_user(OPERATOR)
# control: expired rec must be rejected
re_ = client.post("/v1/dispatch/recommendations/RT-REXP/action", json={"action": "APPROVE"})
record("HITL.expired-blocked", "PASS" if re_.status_code == 400 else "VULN", f"status={re_.status_code}")

# double-approve race on same rec
def act(_):
    c = TestClient(m.app, raise_server_exceptions=False)
    return c.post("/v1/dispatch/recommendations/RT-R1/action", json={"action": "APPROVE"}).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    codes = sorted(ex.map(act, range(4)))
db = TestSession()
dispatch_events = db.query(OutboxEvent).filter(OutboxEvent.topic == "asset.dispatched").count()
rec_status = db.query(DispatchRecommendation).filter(DispatchRecommendation.id == "RT-R1").first().status
db.close()
record("HITL.double-approve-race",
       "PASS" if dispatch_events <= 1 and codes.count(200) <= 1 else "VULN",
       f"codes={codes} dispatch_events={dispatch_events} rec_status={rec_status}")

# two recs, same asset, sequential -> second must fail
ra = client.post("/v1/dispatch/recommendations/RT-R3/action", json={"action": "APPROVE"})
rb = client.post("/v1/dispatch/recommendations/RT-R4/action", json={"action": "APPROVE"})
record("HITL.same-asset-double-dispatch",
       "PASS" if rb.status_code == 400 else "VULN",
       f"approve1={ra.status_code} approve2(same asset)={rb.status_code} detail='{rb.json().get('detail','')[:50]}'")

# kill switch gates approval?
from apps.api import pilot as pilot_mod
pilot_mod.redis_client = None
os.environ["PILOT_MODE"] = "1"
rc = client.post("/v1/dispatch/recommendations/RT-R2/action", json={"action": "APPROVE"})
record("HITL.pilot-misconfig-failclosed", "INFO" if rc.status_code == 503 else "NOTE",
       f"pilot ON, no redis -> {rc.status_code} (None=unknown treated fail-closed)")

# =========================================================
print("\n=== PHASE 7: KILL SWITCH vs REDIS CONTROL ===")
class DictRedis:
    def __init__(self): self.store = {}
    def get(self, k): return self.store.get(k)
    def setex(self, k, ttl, v): self.store[k] = v
    def set(self, k, v): self.store[k] = v
    def delete(self, *ks):
        for k in ks: self.store.pop(k, None)
    def incr(self, k):
        self.store[k] = str(int(self.store.get(k, "0")) + 1); return int(self.store[k])

dr = DictRedis()
dr.setex("pilot:suspended", 3600, "1"); dr["pilot:suspended_by"] = "chief"; dr["pilot:suspension_reason"] = "drill"
pilot_mod.redis_client = dr
try:
    pilot_mod.enforce_pilot_active()
    blocked = False
except Exception:
    blocked = True
record("KS.suspend-blocks", "PASS" if blocked else "VULN", f"suspension key present -> blocked={blocked}")

# attacker with Redis write access deletes the suspension
dr.delete("pilot:suspended", "pilot:suspended_by", "pilot:suspension_reason")
try:
    pilot_mod.enforce_pilot_active()
    opened = True
except Exception:
    opened = False
record("KS.redis-flush-fails-open",
       "CHAIN(redis-write => kill-switch defeat)" if opened else "PASS",
       f"PILOT_MODE still ON; after key deletion enforcement passes={opened}")
pilot_mod.redis_client = None

# Redis write -> authorization plane DoS (fail-closed)
m.redis_client = dr; dr.setex("circuit_open:OPA", 300, "1")
install_user(CITIZEN)
rd = client.post("/v1/incidents", json=payload)
record("KS.circuit-forge-dos",
       "CHAIN(redis-write => total authz outage)" if rd.status_code == 503 else f"NOTE({rd.status_code})",
       f"circuit_open:OPA forged -> SOS ingestion={rd.status_code}")
m.redis_client = None

# =========================================================
print("\n=== PHASE 6/8/9: INPUT ABUSE ===")
seed_world(); install_user(CITIZEN)

nan_payload = {"type": "quake", "location": {"latitude": float("nan"), "longitude": float("inf")},
               "message": "nan sos", "source": "mobile_app"}
rn = client.post("/v1/incidents", json=nan_payload)
geo_note = ""
if rn.status_code == 200:
    rl = client.get("/v1/incidents")
    geo_note = "NaN-in-response" if "NaN" in rl.text or "Infinity" in rl.text else "sanitized"
record("INPUT.nan-inf-coords",
       "BLOCKED" if rn.status_code in (400, 422) else f"FINDING(stored {rn.status_code}; {geo_note})",
       f"status={rn.status_code} {geo_note}")

deep_body = '{"a":' * 15000 + "1" + "}" * 15000
t0 = time.time()
try:
    rdep = client.post("/v1/incidents", content=deep_body.encode(), headers={"Content-Type": "application/json"})
    dep_status = rdep.status_code
except Exception as e:
    dep_status = f"exc:{type(e).__name__}"
record("INPUT.deep-nesting-bomb", "INFO", f"~75KB depth-15k -> {dep_status} in {time.time()-t0:.2f}s")

rm = client.get("/v1/pilot/suspend")
rp = client.patch("/v1/assets", json={})
record("API.method-confusion", "PASS" if rm.status_code == 405 and rp.status_code == 405 else "CHECK",
       f"GET suspend={rm.status_code} PATCH assets={rp.status_code}")

r_noauth = client.get("/v1/dispatch/recommendations")
r_assets = client.get("/v1/assets")
record("API.anon-probes", "MIXED", f"anon recommendations={r_noauth.status_code}, anon ASSETS={r_assets.status_code}"
       + (" <- UNAUTHENTICATED RESPONDER DATA" if r_assets.status_code == 200 else ""))

big_msg = "@" + "x" * 100000
t0 = time.time()
rbig = client.post("/v1/incidents", json={"type": "t", "location": {"latitude": 34.05, "longitude": -118.24},
                                          "message": big_msg, "source": "web"})
record("DOS.mask_pii-100KB", "MEASURED", f"status={rbig.status_code} handler_time={time.time()-t0:.3f}s (quadratic regex)")

# =========================================================
print("\n=== METRICS / PRIVACY SNIFF ===")
try:
    rmet = client.get("/metrics")
    body = rmet.text[:200000]
    leaks = [w for w in ("Authorization", "password", "BREAK_GLASS", "phone", "@") if w.lower() in body.lower()]
    record("PRIVACY.metrics", "CLEAN" if not leaks else f"REVIEW:{leaks}", f"status={rmet.status_code} len={len(body)}")
except Exception as e:
    record("PRIVACY.metrics", "NOT AVAILABLE", str(e)[:80])

# =========================================================
print("\n================ SUMMARY ================")
counts = {}
for _, v, _d in RESULTS:
    key = v.split("(")[0]
    counts[key] = counts.get(key, 0) + 1
for name, verdict, detail in RESULTS:
    print(f"{verdict:<38} | {name}")
print("\nCOUNTS:", json.dumps(counts))
