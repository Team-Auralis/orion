"""FlyMemory — dopamine-modulated KC→MBON plasticity for NECTAR.

Ported from lixiang1076/fly-brain/dopamine_learning.py and extended with:
- ORION audit logging
- Brian2 backend integration
- Persistent memory on D: drive
- Structured readout for OMNIS evidence

Plasticity model (Phase 1 — manual modulation):
  PAM dopamine (reward):  strengthens active KC→MBON synapses  (mult × 1.5)
  PPL1 dopamine (punishment): weakens active KC→MBON synapses (mult × 0.3)
  Synapse weights clamped to [0.01, 10.0] × baseline.
"""

import json
import os
import numpy as np
import pandas as pd
from pathlib import Path

_MB_FILE = r"D:\orion\data\nectar\mb\mushroom_body_neurons.json"
_COMP_783 = r"D:\orion\data\nectar\connectome\Completeness_783.csv"
_MEMORY_PATH = r"D:\orion\data\nectar\results\fly_memory.json"


class FlyMemory:
    """Persistent memory store for mushroom-body learned associations."""

    def __init__(self, memory_path: str = None):
        self._memory_path = memory_path or _MEMORY_PATH
        self.mb_data = self._load_json(_MB_FILE)
        self.comp = pd.read_csv(_COMP_783, index_col=0)
        if self.comp.index.dtype != "int64":
            self.comp.index = self.comp.index.astype("int64")
        self.flyid2i = {fid: i for i, fid in enumerate(self.comp.index)}
        self.i2flyid = {i: fid for fid, i in self.flyid2i.items()}

        self.kc_indices = self._ids_to_indices(self._all_kc_ids())
        self.mbon_indices = self._ids_to_indices(self._all_mbon_ids())
        self.pam_indices = self._ids_to_indices(self._all_pam_ids())
        self.ppl_indices = self._ids_to_indices(self._all_ppl_ids())

        self.memory = self._load_memory()

    @staticmethod
    def _load_json(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_memory(self):
        if os.path.exists(self._memory_path):
            with open(self._memory_path, encoding="utf-8") as f:
                return json.load(f)
        return {
            "experiences": [],
            "weight_modifications": {},
            "total_experiences": 0,
        }

    def save_memory(self):
        os.makedirs(os.path.dirname(self._memory_path), exist_ok=True)
        with open(self._memory_path, "w") as f:
            json.dump(self.memory, f, indent=2, ensure_ascii=False)

    # --- KC / MBON ID extraction ---

    def _all_kc_ids(self):
        ids = []
        for group_ids in self.mb_data["kenyon_cells"].values():
            ids.extend(group_ids)
        return ids

    def _all_mbon_ids(self):
        ids = []
        for group_ids in self.mb_data["mbon"].values():
            ids.extend(group_ids)
        return ids

    def _all_pam_ids(self):
        ids = []
        for group_ids in self.mb_data["dan_pam_reward"].values():
            ids.extend(group_ids)
        return ids

    def _all_ppl_ids(self):
        ids = []
        for group_ids in self.mb_data["dan_ppl_punishment"].values():
            ids.extend(group_ids)
        return ids

    def _ids_to_indices(self, flywire_ids):
        return set(self.flyid2i[fid] for fid in flywire_ids if fid in self.flyid2i)

    # --- Active neuron extraction from spike trains ---

    def get_active_kc(self, spike_trains):
        return [
            i for i in self.kc_indices if i in spike_trains and len(spike_trains[i])
        ]

    def get_active_mbon(self, spike_trains):
        out = {}
        for i in self.mbon_indices:
            if i in spike_trains and len(spike_trains[i]):
                out[i] = {
                    "flyid": self.i2flyid.get(i, 0),
                    "spikes": len(spike_trains[i]),
                }
        return out

    def get_active_pam(self, spike_trains):
        return [
            i for i in self.pam_indices if i in spike_trains and len(spike_trains[i])
        ]

    def get_active_ppl(self, spike_trains):
        return [
            i for i in self.ppl_indices if i in spike_trains and len(spike_trains[i])
        ]

    # --- Plasticity modulation ---

    def apply_reward(self, active_kc, strength=1.5, label="reward"):
        return self._modulate(active_kc, strength, label, "reward")

    def apply_punishment(self, active_kc, strength=0.3, label="punishment"):
        return self._modulate(active_kc, strength, label, "punishment")

    def _modulate(self, active_kc, strength, label, signal_type):
        modified = 0
        for kc_idx in active_kc:
            for mbon_idx in self.mbon_indices:
                key = f"{kc_idx}:{mbon_idx}"
                current = self.memory["weight_modifications"].get(key, 1.0)
                new_val = current * strength
                new_val = max(0.01, min(10.0, new_val))
                self.memory["weight_modifications"][key] = round(new_val, 4)
                modified += 1

        self.memory["experiences"].append(
            {
                "label": label,
                "signal_type": signal_type,
                "strength": strength,
                "active_kc_count": len(active_kc),
                "synapses_modified": modified,
            }
        )
        self.memory["total_experiences"] = len(self.memory["experiences"])
        self.save_memory()

        return {
            "signal_type": signal_type,
            "label": label,
            "active_kc": len(active_kc),
            "synapses_modified": modified,
            "total_experiences": self.memory["total_experiences"],
        }

    def get_weight_multipliers(self):
        mods = {}
        for key, mult in self.memory["weight_modifications"].items():
            if mult != 1.0:
                pre, post = key.split(":")
                mods[(int(pre), int(post))] = mult
        return mods

    def apply_to_synapses(self, syn):
        """Apply learned weight multipliers to a Brian2 Synapses object.

        Only modifies synapses whose (pre, post) pair has a stored multiplier.
        Returns the number of synapse weights actually changed.
        """
        mods = self.get_weight_multipliers()
        if not mods:
            return 0
        # Vectorize: one pass over the synapse list with dict lookups instead
        # of O(mods x synapses) full-array scans per modifier.
        pre_arr = np.array(syn.i)
        post_arr = np.array(syn.j)
        mults = np.fromiter(
            (mods.get(p, 1.0) for p in zip(pre_arr.tolist(), post_arr.tolist())),
            dtype=float,
            count=len(pre_arr),
        )
        mask = mults != 1.0
        if not mask.any():
            return 0
        syn.w[mask] = syn.w[mask] * mults[mask]
        return int(mask.sum())

    def get_memory_summary(self):
        n_mods = sum(
            1 for v in self.memory["weight_modifications"].values() if v != 1.0
        )
        return {
            "total_experiences": self.memory["total_experiences"],
            "modified_synapses": n_mods,
            "recent_experiences": self.memory["experiences"][-5:],
        }

    def reset_memory(self):
        self.memory = {
            "experiences": [],
            "weight_modifications": {},
            "total_experiences": 0,
        }
        self.save_memory()
        return {"status": "memory_reset"}
