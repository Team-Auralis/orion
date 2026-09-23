"""Product generation engine — creates real, sellable digital products from specs.

ORION generates genuine digital products (templates, study notes, tools, asset packs)
from a spec, quality-checks them, prices them from config tiers, writes files to
workspace/products/, and registers a Product row with all metadata needed for publishing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from orion.config import get_config
from orion.db import get_session
from orion.log import get_logger
from orion.models import Product
from orion.router import ModelRouter, DEGRADED

log = get_logger("products")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProductGenerationError(RuntimeError):
    """Raised when product generation fails after retries."""


# ---------------------------------------------------------------------------
# Product specification
# ---------------------------------------------------------------------------


class ProductSpec(BaseModel):
    """Specification for a digital product to generate."""

    kind: str = Field(
        description="Product kind",
        pattern=r"^(template|notes|tool|asset_pack|checklist|starter_kit)$",
    )
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=10, max_length=2000)
    target_audience: str = Field(min_length=1, max_length=200)
    features: list[str] = Field(default_factory=list, max_length=20)
    estimated_hours_to_create: float = Field(ge=0.1, le=1000)
    difficulty: str = Field(pattern=r"^(easy|medium|hard)$")
    price_usd_cents: Optional[int] = Field(default=None, ge=0)
    price_tier: Optional[str] = Field(
        default=None, pattern=r"^(low|medium|high|premium)$"
    )
    tags: list[str] = Field(default_factory=list, max_length=20)
    license: str = Field(default="MIT", pattern=r"^(MIT|CC0|custom)$")

    @field_validator("price_usd_cents", "price_tier", mode="before")
    @classmethod
    def _require_one_price(cls, v, info):
        # At least one of price_usd_cents or price_tier must be provided
        # This is checked after model construction in the generation logic
        return v

    def resolve_price_cents(self) -> int:
        """Resolve price to USD cents from either explicit price or tier mapping."""
        if self.price_usd_cents is not None:
            return self.price_usd_cents
        if self.price_tier is not None:
            cfg = get_config()
            tiers = getattr(cfg, "product_pricing", {})
            if not tiers:
                # Fallback defaults if config not loaded
                tiers = {"low": 500, "medium": 1500, "high": 3000, "premium": 5000}
            return tiers.get(self.price_tier, 1500)
        raise ValueError("Either price_usd_cents or price_tier must be specified")


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


PLACEHOLDER_PATTERNS = [
    r"todo",
    r"fixme",
    r"your_name_here",
    r"lorem ipsum",
    r"placeholder",
    r"example\.com",
    r"your_",
    r"insert_",
    r"<.*>",
]


def _check_placeholders(content: str) -> list[str]:
    """Return list of placeholder patterns found in content."""
    found = []
    content_lower = content.lower()
    for pattern in PLACEHOLDER_PATTERNS:
        import re

        if re.search(pattern, content_lower):
            found.append(pattern)
    return found


def _check_syntax(file_path: Path) -> tuple[bool, Optional[str]]:
    """Check syntax of a code file. Returns (passed, error_message)."""
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", str(file_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, None
        except subprocess.TimeoutExpired:
            return False, "Syntax check timeout"
        except Exception as e:
            return False, str(e)
    # For other file types, we don't have a syntax checker
    return True, None


def quality_gate(product_dir: Path, kind: str) -> tuple[bool, list[str]]:
    """Run quality checks on generated product. Returns (passed, reasons)."""
    reasons = []

    # Find all files in the product directory
    files = list(product_dir.rglob("*"))
    files = [f for f in files if f.is_file()]

    if not files:
        reasons.append("No files generated")
        return False, reasons

    total_chars = 0
    total_lines = 0
    code_files = 0

    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file - skip text checks
            continue

        total_chars += len(content)
        total_lines += content.count("\n") + 1

        # Check for placeholders
        placeholders = _check_placeholders(content)
        if placeholders:
            reasons.append(
                f"Placeholders found in {file_path.name}: {', '.join(placeholders)}"
            )

        # Syntax check for code files
        if file_path.suffix.lower() in (
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".json",
            ".yaml",
            ".yml",
        ):
            code_files += 1
            passed, error = _check_syntax(file_path)
            if not passed:
                reasons.append(f"Syntax error in {file_path.name}: {error}")

    # Minimum size checks based on kind
    if kind in ("notes", "template", "checklist", "starter_kit"):
        if total_chars < 500:
            reasons.append(
                f"Content too small: {total_chars} chars (minimum 500 for {kind})"
            )
    elif kind in ("tool", "asset_pack"):
        if total_lines < 50 and code_files > 0:
            reasons.append(
                f"Code too small: {total_lines} lines (minimum 50 for {kind})"
            )

    return len(reasons) == 0, reasons


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _build_generation_prompt(spec: ProductSpec) -> tuple[str, str]:
    """Build system and user prompts for product generation."""
    system = (
        "You are an expert digital product creator. Generate complete, original, "
        "production-ready digital products. No placeholders, no TODO comments, "
        "no lorem ipsum. Output must be a single file or zip-ready directory "
        "structure that a customer could purchase and use immediately."
    )

    features_text = ", ".join(spec.features) if spec.features else "none specified"
    user = (
        f"Create a complete, original {spec.kind} for {spec.target_audience} "
        f"about: {spec.description}. Features: {features_text}. "
        f"Difficulty: {spec.difficulty}. Estimated creation time: "
        f"{spec.estimated_hours_to_create} hours. License: {spec.license}. "
        f"Tags: {', '.join(spec.tags) if spec.tags else 'none'}. "
        f"Output must be production-ready quality — a real product someone would pay for."
    )

    return system, user


def _write_product_files(product_dir: Path, content: str, kind: str) -> list[Path]:
    """Write generated content to product directory. Returns list of written files."""
    product_dir.mkdir(parents=True, exist_ok=True)

    # For simplicity, write as a single file based on kind
    # In a more advanced version, the model could return a file tree
    if kind == "tool":
        # Assume Python tool
        main_file = product_dir / "main.py"
        main_file.write_text(content, encoding="utf-8")
        return [main_file]
    elif kind in ("template", "checklist"):
        # Markdown template
        main_file = product_dir / "template.md"
        main_file.write_text(content, encoding="utf-8")
        return [main_file]
    elif kind == "notes":
        # Study notes as markdown
        main_file = product_dir / "notes.md"
        main_file.write_text(content, encoding="utf-8")
        return [main_file]
    elif kind == "asset_pack":
        # Could be multiple files, for now single zip-ready description
        main_file = product_dir / "assets.md"
        main_file.write_text(content, encoding="utf-8")
        return [main_file]
    elif kind == "starter_kit":
        # Starter kit with README
        main_file = product_dir / "README.md"
        main_file.write_text(content, encoding="utf-8")
        return [main_file]
    else:
        # Default to markdown
        main_file = product_dir / "product.md"
        main_file.write_text(content, encoding="utf-8")
        return [main_file]


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _degraded_fallback(spec: ProductSpec) -> str:
    """Generate a minimal valid product when model is unavailable."""
    degraded_note = "[DEGRADED: model unavailable — minimal placeholder]"
    if spec.kind == "template":
        return f"""# {spec.title}

A {spec.kind} for {spec.target_audience}.

## Description
{spec.description}

## Features
{chr(10).join(f"- {f}" for f in spec.features) if spec.features else "No features specified"}

## Usage
Replace this placeholder content with your actual template.

## License
{spec.license}

{degraded_note}
"""
    elif spec.kind == "notes":
        return f"""# {spec.title}

Study notes for {spec.target_audience}.

## Overview
{spec.description}

## Key Topics
{chr(10).join(f"- {f}" for f in spec.features) if spec.features else "No topics specified"}

## Notes
[Generated in DEGRADED mode - model unavailable. Replace with actual content.]

## License
{spec.license}

{degraded_note}
"""
    elif spec.kind == "tool":
        return f'''#!/usr/bin/env python3
"""{spec.title} - A tool for {spec.target_audience}."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="{spec.description}")
    parser.add_argument("--demo", action="store_true", help="Run demo")
    args = parser.parse_args()

    if args.demo:
        print("{spec.title} demo mode")
        print("Features: {", ".join(spec.features) if spec.features else "none"}")
    else:
        print("Run with --demo for demonstration")


if __name__ == "__main__":
    main()

# {degraded_note}
'''
    else:
        return f"""# {spec.title}

{spec.description}

## Details
- Kind: {spec.kind}
- Audience: {spec.target_audience}
- Features: {", ".join(spec.features) if spec.features else "none"}
- Difficulty: {spec.difficulty}
- License: {spec.license}

[Generated in DEGRADED mode - model unavailable. This is a minimal placeholder.]

{degraded_note}
"""


def generate_product(spec: ProductSpec, session=None) -> Product:
    """Generate a product from spec, quality-check it, write files, register in DB.

    Args:
        spec: ProductSpec with all product details
        session: Optional SQLAlchemy session (creates own if not provided)

    Returns:
        Product ORM instance with all metadata

    Raises:
        ProductGenerationError: If generation fails after retries
    """
    router = ModelRouter()
    product_id = uuid.uuid4().hex[:12]
    product_dir = get_config().data_dir / "workspace" / "products" / product_id

    # Clean up any existing directory
    if product_dir.exists():
        shutil.rmtree(product_dir)

    # Generate content with retry logic
    content = None
    quality_passed = False
    quality_reasons = []
    degraded_reason = None

    for attempt in range(2):  # Try twice
        if attempt == 0:
            # First attempt: use model
            system_prompt, user_prompt = _build_generation_prompt(spec)
            role = "coding" if spec.kind in ("tool", "asset_pack") else "analyst"
            result = router.generate(role, system_prompt, user_prompt)

            if result.status == DEGRADED:
                degraded_reason = result.error or "model unavailable"
                content = _degraded_fallback(spec)
            else:
                content = result.text
        else:
            # Second attempt: stricter prompt
            system_prompt, user_prompt = _build_generation_prompt(spec)
            stricter_system = (
                system_prompt
                + " ABSOLUTELY NO PLACEHOLDERS. Every section must have real content."
            )
            result = router.generate(role, stricter_system, user_prompt)

            if result.status == DEGRADED:
                content = _degraded_fallback(spec)
                degraded_reason = result.error or "model unavailable on retry"
            else:
                content = result.text

        # Write files and run quality gate
        written_files = _write_product_files(product_dir, content, spec.kind)
        quality_passed, quality_reasons = quality_gate(product_dir, spec.kind)

        if quality_passed:
            break
        # Clean up for retry
        shutil.rmtree(product_dir)
        product_dir.mkdir(parents=True, exist_ok=True)

    # If still failed after retries, keep the last attempt but mark as failed
    if not quality_passed:
        # Write the last attempt anyway for inspection
        _write_product_files(product_dir, content, spec.kind)

    # Compute metadata
    total_size = sum(f.stat().st_size for f in product_dir.rglob("*") if f.is_file())
    main_file = (
        next(product_dir.iterdir()) if any(product_dir.iterdir()) else product_dir
    )
    file_hash = _compute_file_hash(main_file) if main_file.is_file() else ""

    price_cents = spec.resolve_price_cents()

    # Determine status
    if degraded_reason:
        status = "QUALITY_FAILED"
        quality_passed = False
        quality_reasons.append(f"model_degraded: {degraded_reason}")
    elif not quality_passed:
        status = "QUALITY_FAILED"
    else:
        status = "READY_TO_PUBLISH"

    # Create Product record
    product = Product(
        id=product_id,
        spec_json=spec.model_dump_json(),
        content_path=str(product_dir.relative_to(get_config().data_dir)),
        file_hash=file_hash,
        size_bytes=total_size,
        quality_passed=quality_passed,
        price_usd_cents=price_cents,
        status=status,
        metadata_json=json.dumps(
            {
                "quality_reasons": quality_reasons,
                "degraded_reason": degraded_reason,
                "generation_attempts": 2 if not quality_passed else 1,
            }
        ),
    )

    # Persist
    own_session = session is None
    if own_session:
        with get_session() as s:
            s.add(product)
    else:
        session.add(product)

    log.info(
        "product generated",
        extra={
            "product_id": product_id,
            "kind": spec.kind,
            "status": status,
            "quality_passed": quality_passed,
            "price_usd_cents": price_cents,
        },
    )

    return product


def list_products(status: Optional[str] = None, session=None) -> list[Product]:
    """List products, optionally filtered by status."""
    own_session = session is None
    if own_session:
        with get_session() as s:
            query = s.query(Product)
            if status:
                query = query.filter(Product.status == status)
            return query.order_by(Product.created_at.desc()).all()
    else:
        query = session.query(Product)
        if status:
            query = query.filter(Product.status == status)
        return query.order_by(Product.created_at.desc()).all()


def get_product(product_id: str, session=None) -> Optional[Product]:
    """Get a product by ID."""
    own_session = session is None
    if own_session:
        with get_session() as s:
            return s.query(Product).filter(Product.id == product_id).first()
    else:
        return session.query(Product).filter(Product.id == product_id).first()


def update_status(product_id: str, status: str, session=None) -> Optional[Product]:
    """Update product status."""
    own_session = session is None
    if own_session:
        with get_session() as s:
            product = s.query(Product).filter(Product.id == product_id).first()
            if product:
                product.status = status
                product.updated_at = datetime.now(timezone.utc).isoformat()
            return product
    else:
        product = session.query(Product).filter(Product.id == product_id).first()
        if product:
            product.status = status
            product.updated_at = datetime.now(timezone.utc).isoformat()
        return product
