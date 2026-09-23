"""ORION Runner - experiment-driven training framework for the ORION project.

Design adapted from higgsfield (https://github.com/higgsfield-ai/higgsfield,
Apache-2.0 - see THIRD_PARTY.md), customised for ORION's single-node
LoRA-SFT/export/deploy stack:

- @experiment("name", seed=42) and @param(...) decorators declare experiments
  and their hyperparameters in the function signature.
- discovery.discover_experiments() lists experiments purely via AST (no imports).
- run_experiment() executes a registered experiment and writes an audit row to
  logs/training_runs.jsonl, compatible with the legacy training-record schema.
- loader.pack_sequences() implements higgsfield-style organic batching.
- deploy.deploy() bridges a finished merge into Ollama via deploy_orion.py.
"""
from .experiment import (
    experiment,
    param,
    Params,
    all_experiments,
    get_experiment,
    run_experiment,
    latest_run,
    latest_run_for,
    get_git_commit,
)
from .params import Param, schema_for
from .discovery import discover_experiments, ExperimentSpec
from .audit import new_run_id, append_row, remove_row, latest_run, latest_run_for  # noqa: F401
from .loader import pack_sequences, tokenize_samples

__all__ = [
    "experiment",
    "param",
    "Params",
    "Param",
    "schema_for",
    "discover_experiments",
    "ExperimentSpec",
    "all_experiments",
    "get_experiment",
    "run_experiment",
    "latest_run",
    "latest_run_for",
    "get_git_commit",
    "pack_sequences",
    "tokenize_samples",
]