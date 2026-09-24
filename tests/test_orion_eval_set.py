"""Unit tests for the forensic ORION eval set: every item must be ID-valid,
self-consistent, and (when the corpus is present) pass the corpus-builder
contamination check with 0 hits."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.forensic.orion_eval_set import (
    ORION_CHANCE_PER_ITEM,
    ORION_ITEMS,
    orion_probe_text,
)  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "data" / "training" / "corpus" / "manifest.json"


def test_items_are_valid():
    assert len(ORION_ITEMS) == 40
    kinds = [it["kind"] for it in ORION_ITEMS]
    assert kinds.count("completion") == 30
    assert kinds.count("mc") == 10
    for it in ORION_ITEMS:
        assert it["kind"] in ("completion", "mc")
        assert isinstance(it["prompt"], str) and it["prompt"].strip()
        if it["kind"] == "mc":
            assert len(it["options"]) == 4
            assert 0 <= it["answer"] < 4
        else:
            assert isinstance(it["answer"], str) and it["answer"].strip()


def test_probe_text_is_nonempty_everywhere():
    for it in ORION_ITEMS:
        probe = orion_probe_text(it)
        assert isinstance(probe, str) and len(probe) >= 20


def test_chances_in_range():
    assert ORION_CHANCE_PER_ITEM["completion"] < 1.0
    assert ORION_CHANCE_PER_ITEM["mc"] == 0.25


@pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="corpus manifest not present")
def test_orion_items_are_not_contaminated():
    from scripts.training.corpus_builder import check_leak

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    hits = []
    for it in ORION_ITEMS:
        hits += check_leak(manifest, orion_probe_text(it))
    assert hits == [], f"ORION items leak into the training corpus: {hits}"
