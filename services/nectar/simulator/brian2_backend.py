"""Brian2 backend: the PRIMARY NECTAR simulator.

Faithful port of the PhilShiu reference model (Shiu et al., Nature 634,
210-219, 2024): leaky integrate-and-fire neurons over the FlyWire FAFB
connectome with neurotransmitter-signed synaptic weights. Network
constants follow model.py as published.
"""

import os
import time
from textwrap import dedent

from ..connectome.loader import load_completeness, load_connectivity
from ..core.backend import NectarBackend, NectarBackendError


def _brian2_available() -> bool:
    try:
        import brian2  # noqa: F401

        return True
    except ImportError:
        return False


DEFAULT_PARAMS = {
    "v_0": -52.0,
    "v_rst": -52.0,
    "v_th": -45.0,
    "t_mbr": 20.0,
    "tau": 5.0,
    "t_rfc": 2.2,
    "t_dly": 1.8,
    "w_syn": 0.275,
    "r_poi": 150.0,
    "r_poi2": 0.0,
    "f_poi": 250,
}


class Brian2Backend(NectarBackend):
    """
    LIF network over the FlyWire connectome (PhilShiu reference model).
    """

    name = "brian2"

    def __init__(self, min_synapses: int = 1, params: dict = None, seed: int = None):
        if not _brian2_available():
            raise NectarBackendError("brian2 is not installed. Run: pip install brian2")
        self._min_synapses = min_synapses
        self._params = {**DEFAULT_PARAMS, **(params or {})}
        self._seed = seed
        self._net = None
        self._neu = None
        self._syn = None
        self._spk_mon = None
        self._pois = []
        self._N = 0
        self._i2flyid = {}
        self._loaded = False
        self._last_walltime_s = None

    def _ensure_loaded(self):
        if not self._loaded:
            raise NectarBackendError("load_connectome first.")

    def _seed_rng(self):
        """Make a run reproducible: brian2's PoissonInput draws from a global
        RNG (and per-neuron state), so any unseeded run - in particular the
        nectar experiments - yields different spike trains on every process.
        """
        import brian2 as b2
        import numpy as np

        np.random.seed(self._seed)
        b2.seed(self._seed)

    def load_connectome(self, path: str, constraints: dict) -> None:
        import brian2 as b2

        if self._seed is not None:
            self._seed_rng()

        completeness_path = constraints.get(
            "completeness_path",
            os.path.join(os.path.dirname(path), "Completeness_783.csv"),
        )
        df_comp = load_completeness(completeness_path)
        self._N = len(df_comp)
        if self._N == 0:
            raise NectarBackendError("Empty completeness roster.")
        self._i2flyid = {i: rid for i, rid in enumerate(df_comp.index)}
        self._flyid2i = {rid: i for i, rid in enumerate(df_comp.index)}

        edges = load_connectivity(path, min_synapses=self._min_synapses)
        p = self._params

        params_b2 = {
            "v_0": p["v_0"] * b2.mV,
            "v_rst": p["v_rst"] * b2.mV,
            "v_th": p["v_th"] * b2.mV,
            "t_mbr": p["t_mbr"] * b2.ms,
            "tau": p["tau"] * b2.ms,
            "t_rfc": p["t_rfc"] * b2.ms,
            "t_dly": p["t_dly"] * b2.ms,
            "w_syn": p["w_syn"] * b2.mV,
            "r_poi": p["r_poi"] * b2.Hz,
            "r_poi2": p["r_poi2"] * b2.Hz,
            "f_poi": p["f_poi"],
        }

        b2.start_scope()
        eqs = dedent("""
            dv/dt = (v_0 - v + g) / t_mbr : volt (unless refractory)
            dg/dt = -g / tau : volt (unless refractory)
            rfc : second
        """)
        neu = b2.NeuronGroup(
            self._N,
            model=eqs,
            method="linear",
            threshold="v > v_th",
            reset="v = v_rst; g = 0*mV",
            refractory="rfc",
            namespace=params_b2,
        )
        neu.v = p["v_0"] * b2.mV
        neu.g = 0 * b2.mV
        neu.rfc = params_b2["t_rfc"]

        syn = b2.Synapses(
            neu,
            neu,
            "w : volt (constant)",
            on_pre="g += w",
            delay=params_b2["t_dly"],
        )
        pre_idx = edges["pre_idx"].to_numpy()
        post_idx = edges["post_idx"].to_numpy()
        syn.connect(i=pre_idx, j=post_idx)
        if "sign" in edges.columns:
            syn.w = (
                edges["sign"].to_numpy()
                * edges["weight"].to_numpy()
                * p["w_syn"]
                * b2.mV
            )
        else:
            syn.w = edges["weight"].to_numpy() * p["w_syn"] * b2.mV

        spk_mon = b2.SpikeMonitor(neu)
        self._neu = neu
        self._syn = syn
        self._spk_mon = spk_mon
        self._pois = []
        self._loaded = True

    def stimulate(
        self, neurons: list, pattern: str, duration: float, rate: float = None
    ) -> None:
        self._ensure_loaded()
        import brian2 as b2

        p = self._params
        rate_arr = p["r_poi"] if rate is None else rate
        for i in neurons:
            if i < 0 or i >= self._N:
                raise FlyBrainBackendError(f"Neuron index {i} out of range.")
            poi = b2.PoissonInput(
                self._neu[i],
                target_var="v",
                N=1,
                rate=rate_arr * b2.Hz,
                weight=p["w_syn"] * p["f_poi"] * b2.mV,
            )
            self._neu[i].rfc = 0 * b2.ms
            self._pois.append(poi)

    def silence(self, neurons: list) -> None:
        self._ensure_loaded()
        import brian2 as b2

        for i in neurons:
            self._syn.w[i, :] = 0 * b2.mV
            self._syn.w[:, i] = 0 * b2.mV

    def apply_memory(self, fly_memory) -> dict:
        """Apply dopamine-modulated plasticity to loaded synapses.

        Args:
            fly_memory: memory.FlyMemory instance with stored weight modifiers.
        Returns:
            Dict with synapses_modified count and memory summary.
        """
        self._ensure_loaded()
        n = fly_memory.apply_to_synapses(self._syn)
        summary = fly_memory.get_memory_summary()
        return {"synapses_modified": n, "memory": summary}

    def step(self, dt: float) -> None:
        self._ensure_loaded()
        import brian2 as b2

        self._build_net().run(dt * b2.second)

    def run(self, duration_s: float) -> None:
        self._ensure_loaded()
        import brian2 as b2

        t0 = time.time()
        self._build_net().run(duration_s * b2.second)
        self._last_walltime_s = time.time() - t0

    def _build_net(self):
        if self._net is None:
            import brian2 as b2

            self._net = b2.Network(self._neu, self._syn, self._spk_mon, *self._pois)
        return self._net

    def spike_trains(self) -> dict:
        """Brian neuron id -> list of spike times (s)."""
        self._ensure_loaded()
        return {
            int(k): [float(t) for t in v]
            for k, v in self._spk_mon.spike_trains().items()
            if len(v)
        }

    def readout(self, groups: list) -> dict:
        self._ensure_loaded()
        trains = self.spike_trains()
        return {
            "backend": self.name,
            "n_neurons": self._N,
            "n_spiking": len(trains),
            "mean_rate_hz": round(
                sum(len(v) for v in trains.values())
                / max(self._N, 1)
                / max(self._last_walltime_s or 1.0, 1e-6),
                4,
            ),
            "walltime_s": self._last_walltime_s,
            "groups": {
                g: {"status": "readout_group_mapped_in_protocol"} for g in groups
            },
        }

    def checkpoint(self, path: str) -> None:
        self._ensure_loaded()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def health(self) -> dict:
        return {
            "status": "ok" if self._loaded else "idle",
            "backend": self.name,
            "n_neurons": self._N,
            "mock": False,
        }

    def reset(self) -> None:
        self._net = None
        self._neu = None
        self._syn = None
        self._spk_mon = None
        self._pois = []
        self._loaded = False


def default_backend():
    """Brian2Backend if usable, else an explicitly-marked NullBackend."""
    if _brian2_available():
        return Brian2Backend()
    from .null_backend import NullBackend

    return NullBackend()
