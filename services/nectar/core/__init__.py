"""
NECTARCore: Backend abstraction and engine orchestration for the
Drosophila whole-brain simulation instrument.
"""
from .backend import NectarBackend, NectarBackendError
from .engine import NectarEngine

__all__ = ["NectarBackend", "NectarBackendError", "NectarEngine"]