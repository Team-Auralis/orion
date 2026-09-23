"""Tests for product generation pipeline (B2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Force DEGRADED mode for all tests
os.environ["ORION_FORCE_NO_OLLAMA"] = "1"

from orion.config import get_config
from orion.db import get_session, init_db
from orion.models import Product
from orion.products import (
    ProductSpec,
    generate_product,
    list_products,
    get_product,
    update_status,
    quality_gate,
    _degraded_fallback,
)


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    """Fresh database for each test."""
    # Point config to temp directory
    os.environ["ORION_DATA_DIR"] = str(tmp_path)
    # Reset config singleton
    import orion.config as config_module

    config_module._config_singleton = None
    # Reset DB engine
    import orion.db as db_module

    db_module._reset_engine()
    # Initialize
    init_db()
    yield
    # Cleanup
    config_module._config_singleton = None
    db_module._reset_engine()


def test_product_spec_validation():
    """Test ProductSpec validates required fields and price resolution."""
    spec = ProductSpec(
        kind="template",
        title="Test Template",
        description="A test template for testing",
        target_audience="developers",
        features=["feature1", "feature2"],
        estimated_hours_to_create=2.0,
        difficulty="easy",
        price_tier="medium",
    )
    assert spec.resolve_price_cents() == 1500

    # Explicit price overrides tier
    spec2 = ProductSpec(
        kind="notes",
        title="Test Notes",
        description="Test notes for testing",
        target_audience="students",
        estimated_hours_to_create=1.0,
        difficulty="easy",
        price_usd_cents=2500,
        price_tier="low",  # should be ignored
    )
    assert spec2.resolve_price_cents() == 2500

    # Missing both price fields should fail at generation time
    spec3 = ProductSpec(
        kind="tool",
        title="Test Tool",
        description="A test tool for testing",
        target_audience="users",
        estimated_hours_to_create=1.0,
        difficulty="medium",
    )
    with pytest.raises(ValueError, match="Either price_usd_cents or price_tier"):
        spec3.resolve_price_cents()


def test_pricing_tier_mapping():
    """Test pricing tier mapping from config."""
    cfg = get_config()
    tiers = cfg.product_pricing
    assert tiers["low"] == 500
    assert tiers["medium"] == 1500
    assert tiers["high"] == 3000
    assert tiers["premium"] == 5000


def test_generate_product_degraded_mode(tmp_path):
    """Generate a template product in DEGRADED mode."""
    spec = ProductSpec(
        kind="template",
        title="Notion Project Tracker",
        description="A comprehensive project tracking template for Notion with Kanban boards, time tracking, and client portals",
        target_audience="freelancers",
        features=["kanban", "time-tracking", "client-portal"],
        estimated_hours_to_create=3.0,
        difficulty="medium",
        price_tier="medium",
        tags=["notion", "productivity", "freelance"],
        license="MIT",
    )

    product = generate_product(spec)

    # Verify product record
    assert product.id is not None
    assert len(product.id) == 12
    assert product.spec_json is not None
    assert product.content_path is not None
    assert product.status == "QUALITY_FAILED"  # DEGRADED mode marks as failed
    assert product.quality_passed is False
    assert product.price_usd_cents == 1500

    # Verify files were written
    product_dir = get_config().data_dir / product.content_path
    assert product_dir.exists()
    files = list(product_dir.iterdir())
    assert len(files) > 0
    # Should have template.md
    assert any(f.name == "template.md" for f in files)

    # Verify content has expected structure
    content = files[0].read_text(encoding="utf-8")
    assert "Notion Project Tracker" in content
    assert "freelancers" in content
    assert "kanban" in content.lower()
    assert "DEGRADED" in content or "model unavailable" in content.lower()

    # Verify metadata includes degraded reason
    meta = json.loads(product.metadata_json)
    assert meta["degraded_reason"] is not None
    assert "model_degraded" in " ".join(meta["quality_reasons"])


def test_generate_product_tool_degraded(tmp_path):
    """Generate a tool product in DEGRADED mode."""
    spec = ProductSpec(
        kind="tool",
        title="CSV Cleaner",
        description="A Python script to clean and normalize CSV files",
        target_audience="data analysts",
        features=["remove-duplicates", "normalize-dates", "handle-missing"],
        estimated_hours_to_create=2.0,
        difficulty="easy",
        price_tier="low",
    )

    product = generate_product(spec)

    assert product.status == "QUALITY_FAILED"
    assert product.quality_passed is False
    assert product.price_usd_cents == 500

    product_dir = get_config().data_dir / product.content_path
    files = list(product_dir.iterdir())
    assert any(f.name == "main.py" for f in files)

    # Verify Python syntax is valid
    py_file = next(f for f in files if f.name == "main.py")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(py_file)],
        capture_output=True,
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr.decode()}"


def test_quality_gate_passes_for_valid_content(tmp_path):
    """Quality gate passes for valid generated content."""
    # Create a valid product directory
    product_dir = tmp_path / "test_product"
    product_dir.mkdir()

    # Write a valid template (markdown, >500 chars, no placeholders)
    template = product_dir / "template.md"
    template.write_text(
        "# Project Tracker\n\n"
        "A comprehensive project tracking system for freelancers and agencies "
        "who need to manage multiple client projects simultaneously.\n\n"
        "## Features\n"
        "- Kanban board with custom columns for each project stage\n"
        "- Time tracking with detailed reports and export capabilities\n"
        "- Client portal with shared views and controlled access\n"
        "- Invoice generation directly from tracked time entries\n"
        "- Automated reminders for deadlines and follow-ups\n\n"
        "## Usage\n"
        "Duplicate this template to your Notion workspace and start tracking "
        "immediately. Customize the columns, tags, and views to match your "
        "specific workflow requirements.\n\n"
        "## License\n"
        "MIT\n",
        encoding="utf-8",
    )

    passed, reasons = quality_gate(product_dir, "template")
    assert passed is True
    assert reasons == []


def test_quality_gate_fails_on_placeholders(tmp_path):
    """Quality gate fails when placeholders are present."""
    product_dir = tmp_path / "test_product"
    product_dir.mkdir()

    template = product_dir / "template.md"
    template.write_text(
        "# TODO: Project Tracker\n\n"
        "Replace YOUR_NAME_HERE with actual content.\n"
        "FIXME: Add real features.\n",
        encoding="utf-8",
    )

    passed, reasons = quality_gate(product_dir, "template")
    assert passed is False
    # Patterns are returned in lowercase
    assert any("todo" in r for r in reasons)
    assert any("your_name_here" in r for r in reasons)
    assert any("fixme" in r for r in reasons)


def test_quality_gate_fails_on_small_content(tmp_path):
    """Quality gate fails when content is too small."""
    product_dir = tmp_path / "test_product"
    product_dir.mkdir()

    template = product_dir / "template.md"
    template.write_text("# Tiny\n\nToo short.", encoding="utf-8")

    passed, reasons = quality_gate(product_dir, "template")
    assert passed is False
    assert any("too small" in r.lower() or "small" in r.lower() for r in reasons)


def test_quality_gate_fails_on_syntax_error(tmp_path):
    """Quality gate fails on Python syntax errors."""
    product_dir = tmp_path / "test_product"
    product_dir.mkdir()

    tool_file = product_dir / "main.py"
    tool_file.write_text(
        "def broken(\n    print('missing close paren')\n",
        encoding="utf-8",
    )

    passed, reasons = quality_gate(product_dir, "tool")
    assert passed is False
    assert any("syntax error" in r.lower() for r in reasons)


def test_list_products(tmp_path):
    """Test listing products with and without status filter."""
    # Generate a few products
    spec1 = ProductSpec(
        kind="template",
        title="Template 1",
        description="First test template for testing purposes",
        target_audience="users",
        estimated_hours_to_create=1.0,
        difficulty="easy",
        price_tier="low",
    )
    spec2 = ProductSpec(
        kind="notes",
        title="Notes 1",
        description="First test notes for testing purposes",
        target_audience="students",
        estimated_hours_to_create=1.0,
        difficulty="easy",
        price_tier="medium",
    )

    p1 = generate_product(spec1)
    p2 = generate_product(spec2)

    # List all
    all_products = list_products()
    assert len(all_products) == 2

    # Filter by status
    failed_products = list_products(status="QUALITY_FAILED")
    assert len(failed_products) == 2

    # Filter by non-existent status
    empty = list_products(status="PUBLISHED")
    assert len(empty) == 0


def test_get_product(tmp_path):
    """Test getting a product by ID."""
    spec = ProductSpec(
        kind="checklist",
        title="Launch Checklist",
        description="Pre-launch checklist for SaaS products",
        target_audience="founders",
        estimated_hours_to_create=0.5,
        difficulty="easy",
        price_tier="low",
    )

    product = generate_product(spec)

    # Get by ID
    fetched = get_product(product.id)
    assert fetched is not None
    assert fetched.id == product.id
    # Title is in spec_json
    import json

    spec_data = json.loads(fetched.spec_json)
    assert spec_data["title"] == "Launch Checklist"

    # Non-existent ID
    not_found = get_product("nonexistent123")
    assert not_found is None


def test_update_status(tmp_path):
    """Test updating product status."""
    spec = ProductSpec(
        kind="asset_pack",
        title="UI Icons",
        description="A pack of 50 modern UI icons",
        target_audience="designers",
        estimated_hours_to_create=5.0,
        difficulty="medium",
        price_tier="high",
    )

    product = generate_product(spec)
    assert product.status == "QUALITY_FAILED"

    # Update status
    updated = update_status(product.id, "READY_TO_PUBLISH")
    assert updated is not None
    assert updated.status == "READY_TO_PUBLISH"

    # Verify persisted
    fetched = get_product(product.id)
    assert fetched.status == "READY_TO_PUBLISH"

    # Non-existent ID
    result = update_status("nonexistent", "PUBLISHED")
    assert result is None


def test_cli_product_generate(tmp_path):
    """Test CLI product generate command in DEGRADED mode."""
    env = os.environ.copy()
    env["ORION_DATA_DIR"] = str(tmp_path)
    env["ORION_FORCE_NO_OLLAMA"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orion.cli",
            "product",
            "generate",
            "--kind",
            "template",
            "--title",
            "CLI Test Template",
            "--description",
            "A test template generated via CLI for verification",
            "--audience",
            "testers",
            "--features",
            "feature1,feature2",
            "--tier",
            "medium",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "product_id:" in result.stdout
    assert "path:" in result.stdout
    assert "status: QUALITY_FAILED" in result.stdout
    assert "quality_passed: False" in result.stdout
    assert "price_usd_cents: 1500" in result.stdout


def test_cli_product_list(tmp_path):
    """Test CLI product list command."""
    env = os.environ.copy()
    env["ORION_DATA_DIR"] = str(tmp_path)
    env["ORION_FORCE_NO_OLLAMA"] = "1"

    # Generate a product first
    subprocess.run(
        [
            sys.executable,
            "-m",
            "orion.cli",
            "product",
            "generate",
            "--kind",
            "notes",
            "--title",
            "List Test",
            "--description",
            "Test notes for list command",
            "--audience",
            "students",
            "--tier",
            "low",
        ],
        capture_output=True,
        env=env,
        cwd=Path(__file__).parent.parent,
    )

    # List products
    result = subprocess.run(
        [sys.executable, "-m", "orion.cli", "product", "list"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0
    assert "List Test" in result.stdout or "QUALITY_FAILED" in result.stdout


def test_cli_product_show(tmp_path):
    """Test CLI product show command."""
    env = os.environ.copy()
    env["ORION_DATA_DIR"] = str(tmp_path)
    env["ORION_FORCE_NO_OLLAMA"] = "1"

    # Generate a product
    gen_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orion.cli",
            "product",
            "generate",
            "--kind",
            "template",
            "--title",
            "Show Test",
            "--description",
            "Test template for show command verification",
            "--audience",
            "developers",
            "--tier",
            "high",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parent.parent,
    )

    # Extract product_id from output
    import re

    match = re.search(r"product_id:\s*(\w+)", gen_result.stdout)
    assert match, "Could not find product_id in generate output"
    product_id = match.group(1)

    # Show product
    result = subprocess.run(
        [sys.executable, "-m", "orion.cli", "product", "show", product_id],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0
    assert product_id in result.stdout
    assert "Show Test" in result.stdout
    assert "QUALITY_FAILED" in result.stdout
    assert "degraded" in result.stdout.lower()


def test_degraded_fallback_content():
    """Test degraded fallback generates valid minimal content for each kind."""
    for kind in ["template", "notes", "tool", "asset_pack", "checklist", "starter_kit"]:
        spec = ProductSpec(
            kind=kind,
            title=f"Test {kind}",
            description=f"Test {kind} for testing",
            target_audience="testers",
            estimated_hours_to_create=1.0,
            difficulty="easy",
            price_tier="low",
        )
        content = _degraded_fallback(spec)
        assert len(content) > 100
        assert "Test" in content
        assert "DEGRADED" in content or "model unavailable" in content.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
