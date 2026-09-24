"""ORION-HIVE: minimal distributed training prototype (T8).

A small simulated heterogeneous fleet on one box: each worker is a real
multiprocessing.Process (IPC over an OS pipe, not threads) with a declared
DeviceEnvelope (role + cpu/ram budgets + measured tok/s); a coordinator
registers workers, capability-probes them, dispatches disjoint token shards
by role, aggregates updates FedAvg-style (weighted by tokens trained) with a
server-side optimizer, checkpoints the global state, and records every run
through scripts/repro.py::record_experiment into logs/training_runs.jsonl.

T8 = prototype + proof of mechanics; T9 runs the formal benchmark on top.
"""

__version__ = "0.1.0"
