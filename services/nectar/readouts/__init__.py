"""Readout registry: which neuron groups NECTAR reports, labeled by anatomy."""

GROUPS = {
    "antennal_lobe": {
        "label": "AL",
        "n_outputs": "PNs → LH + KC",
    },
    "mushroom_body": {
        "label": "MB",
        "kcs": "Kenyon cells",
        "mbons": "MBONs",
    },
    "lateral_horn": {
        "label": "LH",
    },
    "optic_lobe": {
        "label": "OL",
    },
    "motor_output": {
        "label": "MOT",
    },
    "bon": {
        "label": "BON",
        "description": "Higher associative processing",
    },
}


def list_readouts():
    """All registered readout groups with their labels."""
    return {k: v["label"] for k, v in GROUPS.items()}


def readout_groups(experiment_type: str) -> list:
    """Return the readout groups relevant for a given experiment type."""
    if experiment_type == "olfaction":
        return ["antennal_lobe", "mushroom_body", "lateral_horn"]
    if experiment_type == "visuomotor":
        return ["optic_lobe", "mushroom_body", "motor_output"]
    return list(GROUPS.keys())