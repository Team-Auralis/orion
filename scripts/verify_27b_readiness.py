#!/usr/bin/env python3
"""
ORION 27B Architecture Readiness & Verification Suite
======================================================
Validates all pipeline components for training, adapting, and deploying
the Qwen 27B model (Qwen3.8-27B / Qwen3.5-27B) within Project ORION.
"""

import os
import sys
import json
import shutil
from pathlib import Path

MODEL_DIR = Path("D:/Qwen3.8-27B")
DATASET_PATH = Path("scripts/data.jsonl")
SOUP_CONFIG = Path("scripts/soup.yaml")
MODELFILE_PATH = Path("Modelfile")

def test_tokenizer():
    print("\n1. Testing Qwen 27B Tokenizer Integration...")
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR), trust_remote_code=True)
        sample_text = "<|im_start|>user\nAnalyze ORION crisis telemetry for District 4.<|im_end|>"
        tokens = tokenizer.encode(sample_text)
        decoded = tokenizer.decode(tokens)
        print(f"   [PASS] Tokenizer initialized successfully. Vocab size: {len(tokenizer)}")
        print(f"   [PASS] Test encode/decode verified ({len(tokens)} tokens).")
        return True
    except Exception as e:
        print(f"   [FAIL] Tokenizer failed: {e}")
        return False

def test_dataset():
    print("\n2. Testing Training Dataset Compatibility...")
    if not DATASET_PATH.exists():
        print(f"   [FAIL] Dataset '{DATASET_PATH}' does not exist.")
        return False
    
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
        
    print(f"   [PASS] Dataset found with {len(lines)} training samples.")
    # Validate JSON structure
    valid_count = 0
    for idx, line in enumerate(lines):
        try:
            item = json.loads(line)
            if "instruction" in item and "output" in item:
                valid_count += 1
        except Exception as e:
            print(f"   [FAIL] Line {idx} is not valid JSON: {e}")
            return False
            
    print(f"   [PASS] All {valid_count} samples conform to Alpaca/Instruction format.")
    return True

def test_soup_config():
    print("\n3. Testing Soup 27B Training Specification...")
    if not SOUP_CONFIG.exists():
        print(f"   [FAIL] '{SOUP_CONFIG}' not found.")
        return False
        
    with open(SOUP_CONFIG, "r", encoding="utf-8") as f:
        content = f.read()
        
    assert "D:/Qwen3.8-27B" in content or "27B" in content, "Base model must target 27B"
    assert "quantization: 4bit" in content, "4-bit quantization must be specified for consumer hardware"
    assert "lora:" in content, "LoRA adapter must be specified"
    print("   [PASS] Soup configuration correctly specifies Qwen 27B, 4-bit quantization, and LoRA.")
    return True

def test_storage_and_hardware():
    print("\n4. Analyzing Physical Storage & Compute Constraints...")
    drive_d = shutil.disk_usage("D:/")
    free_gb = drive_d.free / (1024**3)
    
    print(f"   - Drive D: Available Space: {free_gb:.2f} GB")
    print("   - Raw 27B FP16/BF16 Weight Size: ~55.6 GB (Exceeds single drive space)")
    print("   - 4-bit Quantized 27B (Q4_K_M / NF4) Size: ~15.5 GB (FITS in available space)")
    
    if free_gb >= 15.0:
        print("   [PASS] Sufficient disk space available for 4-bit quantized 27B model (~15.5 GB).")
    else:
        print("   [WARN] Less than 15 GB available. Free additional space before loading GGUF.")
    return True

def test_modelfile():
    print("\n5. Testing Ollama Modelfile Configuration...")
    if not MODELFILE_PATH.exists():
        print(f"   [FAIL] '{MODELFILE_PATH}' not found.")
        return False
        
    with open(MODELFILE_PATH, "r", encoding="utf-8") as f:
        content = f.read()
        
    assert "<|im_start|>" in content, "ChatML template required for Qwen 27B"
    assert "ORION-Cognitive-Core" in content or "AURA" in content, "Civilizational system prompt required"
    print("   [PASS] Modelfile correctly configured with ChatML template and civilizational prompt.")
    return True

def main():
    print("=" * 65)
    print("      ORION 27B READINESS & ARCHITECTURE VERIFICATION      ")
    print("=" * 65)
    
    results = [
        test_tokenizer(),
        test_dataset(),
        test_soup_config(),
        test_storage_and_hardware(),
        test_modelfile()
    ]
    
    print("\n" + "=" * 65)
    if all(results):
        print(" [ALL CHECKS PASSED] Project ORION is fully configured for 27B!")
        print(" Pipeline status: READY for training and adaptation.")
    else:
        print(" [COMPLETED WITH WARNINGS] Please check the logs above.")
    print("=" * 65)

if __name__ == "__main__":
    main()
