import pytest

from services.ai_sentinel.main import analyze_incident, classify_severity_laya


@pytest.mark.asyncio
async def test_laya_fast_path_used(monkeypatch):
    # Laya labels CRITICAL -> fast path returns without hitting Ollama/fallback.
    monkeypatch.setattr(
        "services.ai_sentinel.main.classify_severity_laya",
        lambda message: "CRITICAL",
    )
    result = await analyze_incident("Urgent! Fire and people might die!")

    assert result["severity"] == "CRITICAL"
    assert result["model_used"] == "laya"
    assert result["model_role"] == "SYSTEM1_LAYA"
    assert result["fallback_active"] is False
    assert result["primary_model_status"].startswith("ONLINE")


@pytest.mark.asyncio
async def test_laya_unavailable_falls_through(monkeypatch):
    # Laya returns None -> existing deterministic fallback still fires.
    monkeypatch.setattr(
        "services.ai_sentinel.main.classify_severity_laya",
        lambda message: None,
    )
    result = await analyze_incident(
        "Help! There is a huge fire and people are trapped!"
    )

    assert result["fallback_active"] is True
    assert "FIRE" in result["tags"]
    assert "MEDICAL" in result["tags"]


@pytest.mark.asyncio
async def test_classify_severity_laya_degrades_gracefully(monkeypatch):
    # Never downloads weights in CI: TESTING=1 forces the None path.
    monkeypatch.setenv("TESTING", "1")
    result = classify_severity_laya("Urgent! Fire and people might die!")
    assert result is None
