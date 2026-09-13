import pytest
from scripts.hardware_decision_engine import check_download_preflight, audit_host_telemetry, calculate_feasibility

def test_preflight_blocks_excessive_size():
    """Verify that attempting to allocate 55.6 GB on a 23 GB drive is strictly blocked."""
    res = check_download_preflight(model_size_gb=55.6, target_drive="D:/")
    assert res["allowed"] is False
    assert "INSUFFICIENT SPACE" in res["reason"]

def test_preflight_enforces_safety_margin():
    """Verify that a download that leaves <5 GB free space is blocked."""
    telemetry = audit_host_telemetry()
    free_d = telemetry["disk_d_free_gb"]
    
    # Try downloading something that leaves only 2 GB
    unsafe_size = free_d - 2.0
    res = check_download_preflight(model_size_gb=unsafe_size, target_drive="D:/")
    assert res["allowed"] is False
    assert "SAFETY VIOLATION" in res["reason"]

def test_preflight_permits_safe_3b_model():
    """Verify that a ~2.0 GB 3B Q4 model is safely allowed with ample margin."""
    res = check_download_preflight(model_size_gb=2.0, target_drive="D:/")
    assert res["allowed"] is True
    assert "PREFLIGHT PASSED" in res["reason"]
    assert res["remaining_after_gb"] > 15.0

def test_feasibility_matrix_tiers():
    """Verify that the feasibility matrix includes all standard tiers."""
    telemetry = audit_host_telemetry()
    tiers = calculate_feasibility(telemetry)
    tier_names = [t["class"] for t in tiers]
    assert any("0.5B" in name for name in tier_names)
    assert any("3B" in name for name in tier_names)
    assert any("7B" in name for name in tier_names)
    assert any("14B" in name for name in tier_names)
    assert any("27B" in name for name in tier_names)
    assert any("70B" in name for name in tier_names)
