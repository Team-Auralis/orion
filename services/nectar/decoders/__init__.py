"""Readout decoding: map raw spike traces into structured neuron-group reports."""


def decode_spikes(trace, group_map: dict, dt: float) -> dict:
    """Compute mean firing rate per annotated group from a spike trace."""
    report = {}
    for group, neuron_ids in group_map.items():
        if not neuron_ids:
            report[group] = {"n_neurons": 0, "mean_rate_hz": None, "n_spikes": 0}
            continue
        spikes = {n: len(trace.get(n, [])) for n in neuron_ids}
        total = sum(spikes.values())
        duration_s = trace.get("_duration_s", 1.0)
        report[group] = {
            "n_neurons": len(neuron_ids),
            "mean_rate_hz": round(total / len(neuron_ids) / duration_s, 4),
            "n_spikes": total,
        }
    return report