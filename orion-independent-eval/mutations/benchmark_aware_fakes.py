"""
Sophisticated Adversarial Fakes designed to evade simple benchmark checks.
Includes:
- Benchmark-aware fake: behaves correctly on known ranges, cheats on shifted data.
- Boundary-biased fake: hardcodes a slightly shifted boundary.
- Stuttered history fake.
"""
import math

class BenchmarkAwareGeoFake:
    """
    Passes on standard latitudes ([-60, 60]), but returns a dummy constant
    when evaluated on unseen high-latitude Arctic cluster (lat > 80).
    """
    def __call__(self, lat1, lon1, lat2, lon2):
        # Evades uniform random tests by computing true math
        if abs(lat1) < 70.0 and abs(lat2) < 70.0:
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
            a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2)**2
            return 2 * 6371.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        # Cheats / collapses on distribution shift (Arctic cluster)
        return 999.999

class BenchmarkAwareCyberFake:
    """
    Detects ASSET-TELEPORT correctly for speeds far from 160 km/h,
    but fails on micro-boundary threshold tests ([159.9, 160.1]).
    """
    def __call__(self, speed_kmh):
        # Coarse heuristic that fails at exact 160.0 boundary
        return speed_kmh > 175.0
