"""Neuron atlas: named stimuli → FlyWire ID mappings.

Loads neuron_atlas.json (lixiang1076/fly-brain) providing 11 named stimuli
(sweet, bitter, walk_forward, escape, smell_danger, etc.) mapped to concrete
FlyWire neuron IDs for direct Brian2 stimulation.
"""

import json
import pandas as pd

_ATLAS_PATH = r"D:\orion\data\nectar\mb\neuron_atlas.json"
_COMP_783 = r"D:\orion\data\nectar\connectome\Completeness_783.csv"


class NeuronAtlas:
    """Map named stimuli and output neurons to Brian2 integer indices."""

    def __init__(self, atlas_path: str = None, completeness_path: str = None):
        atlas_path = atlas_path or _ATLAS_PATH
        comp_path = completeness_path or _COMP_783

        with open(atlas_path, encoding="utf-8") as f:
            self._atlas = json.load(f)

        comp = pd.read_csv(comp_path, index_col=0)
        if comp.index.dtype != "int64":
            comp.index = comp.index.astype("int64")
        self._flyid2i = {fid: i for i, fid in enumerate(comp.index)}

        self._stimuli = self._atlas.get("stimuli", {})
        self._outputs = self._atlas.get("output_neurons", {})

    @property
    def stimulus_names(self):
        return list(self._stimuli.keys())

    @property
    def output_neuron_names(self):
        return list(self._outputs.keys())

    def stimulus_neuron_ids(self, name):
        """Return FlyWire IDs for a named stimulus, or [] if unknown."""
        entry = self._stimuli.get(name)
        if entry is None:
            return []
        return entry.get("neuron_ids", [])

    def stimulus_indices(self, name):
        """Return Brian2 integer indices for a named stimulus."""
        fids = self.stimulus_neuron_ids(name)
        return [self._flyid2i[f] for f in fids if f in self._flyid2i]

    def output_neuron_index(self, name):
        """Return the Brian2 index for a named output neuron, or None."""
        entry = self._outputs.get(name)
        if entry is None:
            return None
        fid = entry.get("id")
        if fid is None:
            return None
        return self._flyid2i.get(fid)

    def stimulus_info(self, name):
        """Full info dict for a stimulus (label, description, neuron count)."""
        entry = self._stimuli.get(name, {})
        return {
            "name": name,
            "label": entry.get("label", name),
            "description": entry.get("description", ""),
            "keywords": entry.get("keywords", []),
            "n_neurons": len(entry.get("neuron_ids", [])),
        }

    def summarize(self):
        return {
            "stimuli": self.stimulus_names,
            "n_stimuli": len(self._stimuli),
            "output_neurons": self.output_neuron_names,
            "n_outputs": len(self._outputs),
        }
