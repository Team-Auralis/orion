"""Tests for the ORION tool registry and secure command runner
(:mod:`orion.tools`).

Registry surface, honest NotImplementedError for unbuilt tools, and the
CommandRunner security envelope (allowlist, blocklist, shell metacharacters,
timeout, workspace confinement). No database needed.
"""

from __future__ import annotations

import os
import sys

import pytest

import orion.tools as tools
from orion.tools import CommandRunner

TOOL_NAMES = [
    "search_web",
    "open_page",
    "extract_page",
    "browser_click",
    "browser_type",
    "take_screenshot",
    "create_file",
    "read_file",
    "run_python",
    "run_test",
    "calculate",
    "query_database",
    "record_expense",
    "record_revenue",
    "create_opportunity",
    "create_draft",
    "request_approval",
]

UNBUILT_TOOLS = [
    "search_web",
    "open_page",
    "extract_page",
    "browser_click",
    "browser_type",
    "take_screenshot",
    "run_python",
    "run_test",
    "create_draft",
]


# ---------------------------------------------------------------------------
# Registry surface
# ---------------------------------------------------------------------------


def test_registry_exposes_every_declared_tool():
    by_name = {t.name: t for t in tools.list_tools()}
    assert set(by_name) == set(TOOL_NAMES)
    for name in TOOL_NAMES:
        spec = by_name[name]
        assert spec.input_schema.get("type") == "object", name
        assert isinstance(spec.input_schema.get("properties"), dict), name
        assert isinstance(spec.output_schema, dict) and spec.output_schema, name
        assert spec.handler is not None, name


def test_get_tool_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown tool"):
        tools.get_tool("definitely_not_a_tool")


@pytest.mark.parametrize("name", UNBUILT_TOOLS)
def test_unbuilt_tools_raise_not_implemented(name):
    spec = tools.get_tool(name)
    with pytest.raises(NotImplementedError) as exc_info:
        spec.handler({})
    assert "not implemented in this build" in str(exc_info.value)


# ---------------------------------------------------------------------------
# CommandRunner — secure subprocess
# ---------------------------------------------------------------------------


def test_allowlisted_command_runs_and_captures_stdout():
    runner = CommandRunner()
    result = runner.run([sys.executable, "-c", "print(1+1)"])
    assert result.exit_code == 0
    assert "2" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    "blocked",
    [
        ["rm", "-rf", "/"],
        ["del", "/s", "C:\\orphan"],
        ["format", "C:"],
        ["shutdown", "/s"],
        ["mkfs", "/dev/sda"],
    ],
)
def test_blocked_commands_refused_before_exec(blocked):
    """Destructive commands never reach a subprocess (denied pre-exec)."""
    runner = CommandRunner()
    result = runner.run(blocked)
    assert result.exit_code == tools.EXIT_BLOCKED
    assert "blocked" in result.stderr.lower()


@pytest.mark.parametrize(
    "cmd",
    [
        "echo a; echo b",
        "echo a | sort",
        "echo a && echo b",
        "echo a > out.txt",
    ],
)
def test_shell_metacharacters_rejected(cmd):
    runner = CommandRunner()
    result = runner.run(cmd)
    assert result.exit_code == tools.EXIT_BLOCKED
    assert "metacharacter" in result.stderr.lower()


def test_non_allowlisted_command_refused():
    runner = CommandRunner()
    result = runner.run(["powershell", "-Command", "Get-ChildItem"])
    assert result.exit_code == tools.EXIT_BLOCKED
    assert "allowlist" in result.stderr.lower()


def test_sleeping_command_killed_by_timeout():
    runner = CommandRunner(max_runtime_seconds=2)
    result = runner.run([sys.executable, "-c", "import time; time.sleep(60)"])
    assert result.exit_code == tools.EXIT_TIMEOUT
    assert "timeout" in result.stdout.lower()


# ---------------------------------------------------------------------------
# create_file / read_file — workspace confinement
# ---------------------------------------------------------------------------


def test_create_and_read_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WORKSPACE_ROOT", tmp_path / "workspace")
    created = tools.get_tool("create_file").handler(
        {"path": "products/note.txt", "content": "hello world"}
    )
    assert created["path"] == os.path.join("products", "note.txt")
    assert created["bytes"] == 11

    read = tools.get_tool("read_file").handler({"path": "products/note.txt"})
    assert read["content"] == "hello world"
    assert read["bytes"] == 11
    assert read["truncated"] is False


@pytest.mark.parametrize(
    "bad_path",
    ["../escape.txt", "a/../../escape.txt", "..\\escape.txt"],
)
def test_path_traversal_refused(tmp_path, monkeypatch, bad_path):
    monkeypatch.setattr(tools, "WORKSPACE_ROOT", tmp_path / "workspace")
    with pytest.raises(ValueError, match="escapes workspace"):
        tools.get_tool("create_file").handler({"path": bad_path, "content": "x"})


def test_absolute_path_escape_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WORKSPACE_ROOT", tmp_path / "workspace")
    absolute = (tmp_path / "outside.txt").resolve()
    with pytest.raises(ValueError, match="escapes workspace"):
        tools.get_tool("create_file").handler({"path": str(absolute), "content": "x"})
    with pytest.raises(ValueError, match="escapes workspace"):
        tools.get_tool("read_file").handler({"path": str(absolute)})
