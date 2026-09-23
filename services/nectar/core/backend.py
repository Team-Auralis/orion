class NectarBackendError(RuntimeError):
    pass


class NectarBackend:
    """
    Contract every NECTAR simulator backend must implement.

    Backends are interchangeable: Brian2 (CPU, reference), Brian2GeNN (GPU,
    elevation path), and NullBackend (MOCK) all conform to this interface.
    """

    name = "abstract"

    def load_connectome(self, path: str, constraints: dict) -> None:
        raise NotImplementedError

    def stimulate(self, neurons: list, pattern: str, duration: float) -> None:
        raise NotImplementedError

    def step(self, dt: float) -> None:
        raise NotImplementedError

    def readout(self, groups: list) -> dict:
        raise NotImplementedError

    def checkpoint(self, path: str) -> None:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError