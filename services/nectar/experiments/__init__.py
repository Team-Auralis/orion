"""Experiment registry: labeled experiment types with integrity requirements."""

EXPERIMENTS = {
    "EXP-ODOR-001": {
        "name": "Olfactory circuit: AL → MBON → LH",
        "type": "olfaction",
        "connectome_subset": "antennal_lobe_enriched",
        "groups": ["antennal_lobe", "mushroom_body", "lateral_horn"],
        "hypothesis": "Stimulating AL inputs reproduces MBON-to-LH output mapping from Zheng et al.",
        "control": "background_stimulus",
        "duration_s": 0.5,
        "mock": False,
    },
    "EXP-ODOR-002": {
        "name": "Olfactory habituation dynamics",
        "type": "olfaction",
        "connectome_subset": "antennal_lobe_enriched",
        "groups": ["antennal_lobe", "mushroom_body"],
        "hypothesis": "Repeated odor stimulation reduces MBON response within 200ms.",
        "control": "background_stimulus",
        "duration_s": 1.0,
        "mock": False,
    },
    "EXP-MOCK-001": {
        "name": "Null-backend smoke test (MOCK)",
        "type": "smoke",
        "connectome_subset": None,
        "groups": ["antennal_lobe"],
        "hypothesis": "NullBackend produces labeled mock output without Brian2.",
        "control": None,
        "duration_s": 0.1,
        "mock": True,
    },
}


def get_experiment(exp_id: str) -> dict:
    if exp_id not in EXPERIMENTS:
        raise KeyError(f"Unknown experiment {exp_id!r}.")
    return EXPERIMENTS[exp_id]