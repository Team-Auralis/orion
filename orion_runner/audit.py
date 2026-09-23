"""ORION Runner - audit-log helpers.

Public home for the training-runs.jsonl utilities. The implementations live
in .experiment (module scope, so the run wrapper can use them without a
circular import); this module re-exports them for a stable public location.
"""
from .experiment import (
    get_git_commit,
    append_row,
    remove_row,
    replace_or_append,
    latest_run,
    latest_run_for,
    new_run_id,
)

__all__ = [
    "get_git_commit",
    "append_row",
    "remove_row",
    "replace_or_append",
    "latest_run",
    "latest_run_for",
    "new_run_id",
]