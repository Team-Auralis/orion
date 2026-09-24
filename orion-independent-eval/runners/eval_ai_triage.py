"""
Independent AI Triage Evaluator:
Evaluates whether ORION's triage layer generalizes across semantic variations
or collapses into brittle keyword matching when LLM inference is offline/uninstalled.
"""
from typing import Dict, Any, List

def evaluate_semantic_vs_regex_gap():
    """
    Tests:
    1. Direct literal keyword matching (e.g. 'FIRE', 'URGENT', 'DIE').
    2. Semantic paraphrases of catastrophic emergencies WITHOUT literal trigger keywords.
       (e.g., 'The residential timber dwelling is fully engulfed in flames',
              'The victim has ceased cardiac activity and is non-responsive',
              'Industrial toxic chlorine gas cloud drifting toward elementary school')
    3. Benign sentences containing literal trigger words as idioms.
       (e.g., 'I am dying of laughter from this joke',
              'The sunset looked like fire in the sky')
    """
    from services.ai_sentinel.main import _regex_tags
    
    test_cases = [
        # (text, true_emergency_severity, expected_primary_tag)
        ("There is a large fire and people are trapped!", "CRITICAL", "FIRE"),
        ("The residential timber dwelling is fully engulfed in flames, three children unaccounted for.", "CRITICAL", "FIRE"),
        ("The individual has ceased respiration and pulses are undetectable.", "CRITICAL", "MEDICAL"),
        ("River levels breached embankment, two-meter wall of brown water rushing down Main Street.", "HIGH", "FLOODING"),
        ("I am dying of laughter, that was the funniest comedy routine ever!", "LOW", None),
        ("The autumn leaves have a bright fire color this evening.", "LOW", None),
        ("Can someone help me move this sofa into the living room?", "LOW", None),
    ]

    results = []
    for text, ground_truth_sev, ground_truth_tag in test_cases:
        # Check deterministic regex fallback behavior
        msg_upper = text.upper()
        tags = _regex_tags(text)
        
        fallback_sev = "MODERATE"
        if "CRITICAL" in msg_upper or "DIE" in msg_upper or "URGENT" in msg_upper:
            fallback_sev = "CRITICAL"

        results.append({
            "text": text,
            "ground_truth_severity": ground_truth_sev,
            "fallback_severity": fallback_sev,
            "fallback_tags": tags,
            "severity_match": (fallback_sev == ground_truth_sev),
            "tag_match": (ground_truth_tag in tags) if ground_truth_tag else (len(tags) == 0)
        })

    return results
