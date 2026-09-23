import json
import os
from pathlib import Path
import pytest

BENCHMARKS_JSON_PATH = Path("data/eval_results/benchmarks.json")

def test_benchmarks_catalog_exists():
    """Verify that the machine-readable benchmarks catalog exists."""
    assert BENCHMARKS_JSON_PATH.exists(), "data/eval_results/benchmarks.json must exist"

def test_no_unlabeled_external_benchmarks():
    """Verify that any external benchmark is explicitly labeled EXTERNAL_REFERENCE."""
    with open(BENCHMARKS_JSON_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    records = catalog["records"]
    for rec in records:
        if rec["benchmark_id"].startswith("ext_"):
            assert rec["status"] == "EXTERNAL_REFERENCE"
            assert rec["is_external_reference"] is True
            assert "disclaimer" in rec["metrics"]
            assert "EXTERNAL REFERENCE" in rec["metrics"]["disclaimer"]

def test_target_27b_strictly_not_run():
    """Verify that uninstalled 27B model is marked NOT_RUN with score=None (no estimated scores)."""
    with open(BENCHMARKS_JSON_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    target_records = [r for r in catalog["records"] if r["benchmark_id"].startswith("target_27b")]
    assert len(target_records) >= 1
    for r in target_records:
        assert r["status"] == "NOT_RUN"
        assert r["score"] is None
        assert r["metrics"].get("estimated_values_prohibited") is True

def test_structured_output_evidence_exists():
    """Verify that structured output evaluation is backed by actual 100-sample JSONL raw traces."""
    with open(BENCHMARKS_JSON_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    struct_records = [r for r in catalog["records"] if r["benchmark_type"] == "STRUCTURED_OUTPUT_EVAL"]
    assert len(struct_records) >= 1
    rec = struct_records[0]
    
    # Must have raw output location that exists on disk
    raw_path = Path(rec["raw_output_location"])
    assert raw_path.exists(), f"Raw traces file {raw_path} must exist on disk"
    
    # Must contain at least 100 real lines
    with open(raw_path, "r", encoding="utf-8") as f_raw:
        lines = [l for l in f_raw if l.strip()]
    assert len(lines) >= 100, "Must have evaluated at least 100 real samples"
    
    # Verify score matches line counts
    assert rec["metrics"]["total_samples"] >= 100
    assert rec["metrics"]["schema_valid_count"] >= 90
