import json
import os

from ..connectome.loader import load_connectivity, build_id_map
from ..core.backend import NectarBackend, NectarBackendError


class NullBackend(NectarBackend):
    """
    MOCK backend used when no real simulator is installed.

    Exposed for tests, CI, and environments where Brian2 cannot run.
    Every output carries mock=True so downstream consumers can never
    mistake it for measured data.
    """

    name = "null"

    def __init__(self, seed: int = 0):
        self._loaded = False
        self._seed = seed

    def load_connectome(self, path: str, constraints: dict) -> None:
        self._loaded = True

    def stimulate(self, neurons: list, pattern: str, duration: float) -> None:
        if not self._loaded:
            raise NectarBackendError("load_connectome first.")

    def step(self, dt: float) -> None:
        if not self._loaded:
            raise NectarBackendError("load_connectome first.")

    def readout(self, groups: list) -> dict:
        return {
            "mock": True,
            "backend": self.name,
            "groups": {g: {"mean_rate_hz": 0.0, "n_spikes": 0} for g in groups},
        }

    def checkpoint(self, path: str) -> None:
        payload = {"mock_backend": True, "seed": self._seed}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f)

    def health(self) -> dict:
        return {"status": "ok", "backend": self.name, "mock": True}

    def reset(self) -> None:
        self._loaded = False