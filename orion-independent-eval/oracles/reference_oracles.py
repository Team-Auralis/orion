"""
Independent Reference Oracles for all tested ORION subsystems.
ZERO imports of ORION source code. Pure math/logic definitions.
"""
import math
from typing import List, Tuple, Dict, Any, Optional

EARTH_RADIUS_KM = 6371.0

# 1. Spherical Haversine (atan2 form)
def oracle_haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c

# 2. Ellipsoidal Geodesic Distance Reference (Vincenty inverse formula on WGS-84)
def oracle_wgs84_ellipsoidal_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[float]:
    """Computes accurate ellipsoidal geodesic distance on WGS-84 (a=6378.137km, f=1/298.257223563)."""
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return 0.0
    a = 6378.137
    f = 1 / 298.257223563
    b = a * (1 - f)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    U1 = math.atan((1 - f) * math.tan(phi1))
    U2 = math.atan((1 - f) * math.tan(phi2))
    L = math.radians(lon2 - lon1)
    Lambda = L
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)
    
    for _ in range(100):
        sinLambda, cosLambda = math.sin(Lambda), math.cos(Lambda)
        sinSigma = math.sqrt((cosU2 * sinLambda) ** 2 + (cosU1 * sinU2 - sinU1 * cosU2 * cosLambda) ** 2)
        if sinSigma == 0:
            return 0.0
        cosSigma = sinU1 * sinU2 + cosU1 * cosU2 * cosLambda
        sigma = math.atan2(sinSigma, cosSigma)
        sinAlpha = (cosU1 * cosU2 * sinLambda) / sinSigma
        cos2Alpha = 1 - sinAlpha ** 2
        cos2SigmaM = cosSigma - 2 * sinU1 * sinU2 / cos2Alpha if cos2Alpha != 0 else 0
        C = (f / 16) * cos2Alpha * (4 + f * (4 - 3 * cos2Alpha))
        LambdaPrev = Lambda
        Lambda = L + (1 - C) * f * sinAlpha * (sigma + C * sinSigma * (cos2SigmaM + C * cosSigma * (-1 + 2 * cos2SigmaM ** 2)))
        if abs(Lambda - LambdaPrev) < 1e-12:
            break
    else:
        return None # Did not converge (e.g. nearly antipodal)

    uSq = cos2Alpha * (a ** 2 - b ** 2) / (b ** 2)
    A = 1 + (uSq / 16384) * (4096 + uSq * (-768 + uSq * (320 - 175 * uSq)))
    B = (uSq / 1024) * (256 + uSq * (-128 + uSq * (74 - 47 * uSq)))
    deltaSigma = B * sinSigma * (cos2SigmaM + (B / 4) * (cosSigma * (-1 + 2 * cos2SigmaM ** 2) - (B / 6) * cos2SigmaM * (-3 + 4 * sinSigma ** 2) * (-3 + 4 * cos2SigmaM ** 2)))
    s = b * A * (sigma - deltaSigma)
    return s

# 3. Coordinate validation
def oracle_validate_coordinates(lat: float, lon: float) -> bool:
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
        return False
    return (-90.0 <= lat <= 90.0) and (-180.0 <= lon <= 180.0)

# 4. CRDT Lattice Reducer
LATTICE_RANK = {"CREATED": 0, "REPORTED": 1, "TRIAGED": 2, "DISPATCHING": 3, "EVACUATING": 4, "RESOLVED": 5}
def oracle_crdt_reduce(history: List[str]) -> str:
    max_rank = -1
    max_state = "CREATED"
    for s in history:
        clean_s = str(s).strip().upper()
        rank = LATTICE_RANK.get(clean_s, -1)
        if rank > max_rank:
            max_rank = rank
            max_state = clean_s
    return max_state

# 5. Independent Multi-Rule Cyber Oracles
def oracle_check_rule_teleport(lat1, lon1, lat2, lon2, dt_seconds, max_kmh=160.0):
    if not oracle_validate_coordinates(lat1, lon1) or not oracle_validate_coordinates(lat2, lon2):
        return False
    if dt_seconds <= 0:
        return oracle_haversine_distance_km(lat1, lon1, lat2, lon2) > 0.1
    dist = oracle_haversine_distance_km(lat1, lon1, lat2, lon2)
    speed = dist / (dt_seconds / 3600.0)
    return speed > max_kmh

def oracle_check_rule_ks_tamper(role: str, outcome: str, action: str, had_active_suspension: bool = True) -> bool:
    unauthorized = (role != "operator")
    failed = (outcome != "success")
    resumed_without_state = (action == "resume" and had_active_suspension is False)
    return unauthorized or failed or resumed_without_state

def oracle_check_rule_auth_bruteforce(failure_timestamps: List[float], window_s: int = 300, threshold: int = 5) -> bool:
    """True if there are >= threshold failures within any window_s seconds."""
    sorted_ts = sorted(failure_timestamps)
    for i in range(len(sorted_ts)):
        count = sum(1 for t in sorted_ts if 0 <= t - sorted_ts[i] <= window_s)
        if count >= threshold:
            return True
    return False

def oracle_check_rule_payload_oversize(size_bytes: int, cap_bytes: int = 262144) -> bool:
    return size_bytes > cap_bytes
