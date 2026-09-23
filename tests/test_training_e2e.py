"""
End-to-End Training Pipeline Verification Tests
==============================================
Validates that the repository possesses real, executable training capabilities:
- Forward/backward pass produces valid loss and gradients
- Loss decreases over training iterations
- LoRA adapter checkpoint is saved and reloaded
- Output logits differ when adapter is active vs base
- Deployment manifest and reproducibility audit trail are recorded
"""

import json
import shutil
import pytest
from pathlib import Path
from scripts.training.e2e_training_smoke_test import run_training_smoke_test, compute_file_sha256

def test_training_smoke_test_lifecycle():
    checkpoint_dir = Path("data/training/test_checkpoint")
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir, ignore_errors=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    try:
        record = run_training_smoke_test(
            use_full_model=False,
            epochs=3,
            lr=2e-3,
            checkpoint_dir=checkpoint_dir,
        )

        # 1. Pipeline status
        assert record.status == "COMPLETED"
        assert record.duration_seconds > 0.0

        # 2. Loss trajectory
        assert record.starting_loss > 0.0
        assert record.ending_loss > 0.0
        assert record.starting_loss > record.ending_loss, "Training must demonstrate loss reduction"
        assert record.loss_reduction_pct > 0.0

        # 3. Checkpoint artifacts
        assert checkpoint_dir.exists()
        adapter_weights = checkpoint_dir / "adapter_model.safetensors"
        adapter_config = checkpoint_dir / "adapter_config.json"
        assert adapter_weights.exists() or (checkpoint_dir / "adapter_model.bin").exists()
        assert adapter_config.exists()

        # 4. Evaluation & Inference delta
        assert record.eval_loss > 0.0
        assert record.output_differs is True, "Fine-tuned adapter must produce measurably different output from base"

        # 5. Deployment manifest
        manifest_path = checkpoint_dir / "deployment_manifest.json"
        assert manifest_path.exists()
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["run_id"] == record.run_id
        assert manifest["verified"] is True
        assert manifest["adapter_type"] == "LoRA"
    finally:
        shutil.rmtree(checkpoint_dir, ignore_errors=True)

def test_reproducibility_audit_log_format():
    log_file = Path("logs/training_runs.jsonl")
    assert log_file.exists()
    with open(log_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) > 0
    latest = lines[-1]
    assert "run_id" in latest
    assert "dataset_hash" in latest
    assert "starting_loss" in latest
    assert "ending_loss" in latest
    assert "loss_reduction_pct" in latest
    assert "hardware" in latest
    assert latest["hardware"]["cpu_cores"] is not None
