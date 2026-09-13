import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from services.ai_sentinel.main import analyze_incident

client = TestClient(app)

def test_ai_health_endpoint():
    """Verify /v1/ai/health returns accurate, unpadded model telemetry."""
    response = client.get("/v1/ai/health")
    assert response.status_code == 200
    data = response.json()
    
    # 1. Production Model
    assert "production_model" in data
    prod = data["production_model"]
    assert prod["name"] == "qwen2:0.5b"
    assert prod["role"] == "PRODUCTION_BASELINE"
    assert "backend" in prod
    
    # 2. Target Research Model
    assert "target_research_model" in data
    target = data["target_research_model"]
    assert target["name"] == "Qwen3.8-27B"
    assert target["weights_present"] is False
    assert "UNINSTALLED" in target["runtime_status"]
    
    # 3. Fallback Engine
    assert "fallback_engine" in data
    assert data["fallback_engine"]["name"] == "deterministic_regex_v1"
    
    # 4. Benchmark Policy Transparency
    assert "benchmarks_policy" in data
    assert data["benchmarks_policy"]["literature_benchmarks_measured_by_orion"] is False

@pytest.mark.asyncio
async def test_analyze_incident_fallback_transparency():
    """Verify that when Ollama is down/unreachable, fallback is NOT silent."""
    # When Ollama is down or times out:
    res = await analyze_incident("Help! Major chemical spill and fire on 4th street!")
    
    # Must preserve triage result
    assert "FIRE" in res["tags"]
    
    # Must explicitly declare fallback status (Task H & E)
    assert res["fallback_active"] is True
    assert res["fallback_reason"] is not None
    assert res["primary_model_status"] in ["OFFLINE", "TIMEOUT", "UNREACHABLE", "HTTP_ERROR"]
    assert res["model_used"] == "deterministic_regex_v1"
    assert res["model_role"] == "DETERMINISTIC_FALLBACK"
