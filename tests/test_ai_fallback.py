import pytest
import asyncio
from services.ai_sentinel.main import analyze_incident

@pytest.mark.asyncio
async def test_ai_fallback_regex_critical():
    # Test that a timeout triggers the regex fallback correctly for critical scenarios
    # The analyze_incident function tries to hit localhost:11434, which is currently down.
    # It should hit the 2.0s timeout and use the deterministic fallback.
    
    sos_message = "Help! There is a huge fire and people are trapped in the building! We need help now!"
    result = await analyze_incident(sos_message)
    
    assert "FIRE" in result["tags"]
    assert "MEDICAL" in result["tags"] # Because "HELP" is in the message
    assert result["severity"] == "MODERATE" # Wait, the message doesn't contain CRITICAL, DIE, URGENT.
    # Let's test with a word that triggers CRITICAL
    
    critical_message = "Urgent! Fire and people might die!"
    crit_result = await analyze_incident(critical_message)
    
    assert "FIRE" in crit_result["tags"]
    assert crit_result["severity"] == "CRITICAL"

@pytest.mark.asyncio
async def test_ai_fallback_regex_flooding():
    flood_msg = "The water level is rising fast, massive flood in the basement."
    result = await analyze_incident(flood_msg)
    
    assert "FLOODING" in result["tags"]
    assert result["severity"] == "MODERATE"
