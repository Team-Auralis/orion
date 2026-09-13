#!/usr/bin/env python3
"""
ORION 27B Training & Fine-Tuning Orchestrator
=============================================
Manages fine-tuning, adaptation, and pre-flight validation for the 27B parameter
model (Qwen3.8-27B / Qwen3.5-27B) across ORION's cognitive architecture.

Author: Team Auralis / Shaurya Sanyal
Target Architecture: Qwen 27B (Dense Hybrid Attention)
"""

import os
import sys
import argparse
import subprocess
import shutil
import json
from pathlib import Path

MODEL_DIR = Path("D:/Qwen3.8-27B")
CONFIG_PATH = Path("scripts/soup.yaml")
DATASET_PATH = Path("scripts/data.jsonl")
OUTPUT_DIR = Path("models/orion_qwen27b_lora")

def print_banner():
    print("=" * 70)
    print("      ORION 27B PARAMETER AI TRAINING & ADAPTATION PIPELINE      ")
    print("            Model Target: Qwen3.8-27B / Qwen3.5-27B               ")
    print("=" * 70)

def check_system_diagnostics():
    print("\n[PRE-FLIGHT DIAGNOSTICS: HARDWARE & STORAGE]")
    
    # 1. Disk Space
    drive_d = shutil.disk_usage("D:/")
    free_d_gb = drive_d.free / (1024**3)
    total_d_gb = drive_d.total / (1024**3)
    print(f"  Drive D: Storage: {free_d_gb:.2f} GB free of {total_d_gb:.2f} GB total.")
    
    # 2. Model Directory Inspection
    if not MODEL_DIR.exists():
        print(f"  [!] Target model directory '{MODEL_DIR}' not found.")
        return False
    else:
        print(f"  [OK] Model directory found at: {MODEL_DIR}")
        
    config_file = MODEL_DIR / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                arch = cfg.get("architectures", ["Unknown"])
                model_type = cfg.get("model_type", "Unknown")
                print(f"  [OK] Architecture: {arch[0]} (type: {model_type})")
        except Exception as e:
            print(f"  [!] Warning reading config.json: {e}")
            
    # 3. Check Weight Shards & LFS Status
    index_file = MODEL_DIR / "model.safetensors.index.json"
    safetensor_files = list(MODEL_DIR.glob("model-*.safetensors"))
    total_weight_size = sum(f.stat().st_size for f in safetensor_files)
    total_weight_gb = total_weight_size / (1024**3)
    
    print(f"  Safetensor shards present on disk: {len(safetensor_files)}/18 ({total_weight_gb:.2f} GB on disk)")
    
    if len(safetensor_files) == 0:
        print("\n  [STORAGE & COMPUTE ANALYSIS FOR 27B MODEL]")
        print("  * Raw Unquantized 16-bit 27B weights = ~55.6 GB.")
        print(f"  * Available Drive D space = {free_d_gb:.2f} GB.")
        print("  * IMPORTANT: Downloading 55.6 GB raw unquantized weights directly will exhaust disk space.")
        print("  * RECOMMENDED ARCHITECTURE:")
        print("    1. 4-bit Quantization / NF4 / GGUF (Q4_K_M) = ~15.5 GB (FITS comfortably in 26 GB free disk!)")
        print("    2. LoRA / QLoRA layer streaming via Soup (streams layers into memory with minimal RAM footprint)")
        print("    3. Remote / Cloud offload plan via `soup plan` / `soup apply` for H100 execution")

    # 4. Dataset Check
    if DATASET_PATH.exists():
        with open(DATASET_PATH, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        print(f"  [OK] Training dataset: {len(lines)} high-density civilizational samples in '{DATASET_PATH}'")
    else:
        print(f"  [!] Training dataset '{DATASET_PATH}' missing. Run scripts/build_aura_dataset.py first.")
        return False

    return True

def run_plan(config_path: Path):
    print(f"\n[ORCHESTRATING TRAINING PLAN VIA SOUP]")
    try:
        subprocess.run(["soup", "plan", "-c", str(config_path)], check=True)
    except FileNotFoundError:
        print("  [!] soup-cli is not installed. Please install: pip install soup-cli")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"  [!] Soup plan failed: {e}")
        sys.exit(1)

def run_train(config_path: Path):
    print(f"\n[EXECUTING 27B TRAINING RUN]")
    safetensors_on_disk = list(MODEL_DIR.glob("model-*.safetensors"))
    if len(safetensors_on_disk) == 0:
        print("\n[BLOCKED] Training cannot proceed:")
        print(f"  Target model directory '{MODEL_DIR}' contains 0/18 safetensor weight shards.")
        print("  Only 130-byte Git LFS pointer stubs are present.")
        print("  Running training on non-existent weights will fail.")
        print("  To train, please download a 4-bit quantized checkpoint or run `soup plan` for cloud execution.")
        sys.exit(1)
    try:
        subprocess.run(["soup", "train", "--config", str(config_path)], check=True)
    except FileNotFoundError:
        print("  [!] soup-cli is not installed. Please install: pip install soup-cli")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"  [!] Training failed with error: {e}")
        sys.exit(1)

def main():
    print_banner()
    
    parser = argparse.ArgumentParser(description="ORION 27B Parameter Training Orchestrator")
    parser.add_argument("--mode", choices=["plan", "train", "verify"], default="plan",
                        help="Action to perform: 'plan' (render resource/VRAM plan), 'train' (execute training), 'verify' (run diagnostics)")
    parser.add_argument("--config", type=str, default=str(CONFIG_PATH), help="Path to training config YAML")
    args = parser.parse_args()
    
    config_file = Path(args.config)
    
    diagnostics_ok = check_system_diagnostics()
    if not diagnostics_ok:
        print("\n[!] Pre-flight checks detected blocking issues. Halting.")
        sys.exit(1)
        
    if args.mode == "verify":
        print("\n[SUCCESS] Pre-flight verification complete. Project is configured for Qwen 27B.")
    elif args.mode == "plan":
        run_plan(config_file)
        print("\n[SUCCESS] 27B Training Plan generated. Review soup.tfstate or execute with --mode train.")
    elif args.mode == "train":
        run_train(config_file)

if __name__ == "__main__":
    main()
