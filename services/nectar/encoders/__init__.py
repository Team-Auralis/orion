"""Stimulus encoding: translate ORION protocols into neuron-group stimulations."""

ENCODERS = {
    "phaneron": "background",
    "odour": "odour_puff",
    "panel": "visual_panel",
    "fc": "feature_column",
}


def encode(stimulus_name: str, target_group: str) -> dict:
    if stimulus_name not in ENCODERS:
        raise KeyError(f"Unknown stimulus {stimulus_name!r}. Known: {sorted(ENCODERS)}")
    return {
        "pattern": ENCODERS[stimulus_name],
        "target_group": target_group,
        "mock": stimulus_name.startswith("mock"),
    }