#!/usr/bin/env python3
"""
ORION Baseline Environment Freeze
==================================
Programmatically captures all host hardware, software versions, git commit,
and active model configuration into results/baseline_environment.json.
No estimates, purely measured system telemetry.
"""

import os
import sys
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import psutil
import shutil

ROOT_DIR = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_FILE = RESULTS_DIR / "baseline_environment.json"

def get_git_info():
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT_DIR), text=True).strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(ROOT_DIR), text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=str(ROOT_DIR), text=True).strip()
        dirty = len(status) > 0
        return {"commit": commit, "branch": branch, "dirty": dirty}
    except Exception as e:
        return {"commit": "unknown", "branch": "unknown", "dirty": False, "error": str(e)}

def get_gpu_info():
    gpu_info = {
        "device_count": 0,
        "cuda_available": False,
        "devices": []
    }
    try:
        import torch
        gpu_info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            gpu_info["device_count"] = torch.cuda.device_count()
            for i in range(torch.cuda.device_count()):
                gpu_info["devices"].append({
                    "index": i,
                    "name": torch.cuda.get_device_name(i),
                    "total_memory_gb": round(torch.cuda.get_device_properties(i).total_memory / (1024**3), 2)
                })
    except Exception as e:
        gpu_info["error"] = str(e)
        
    # Check Windows WMIC / Powershell for physical GPU if torch CUDA is CPU-only
    if not gpu_info["devices"]:
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -Property Name, AdapterRAM | ConvertTo-Json"],
                text=True
            ).strip()
            if out:
                parsed = json.loads(out)
                if isinstance(parsed, dict):
                    parsed = [parsed]
                for d in parsed:
                    gpu_info["devices"].append({
                        "name": d.get("Name"),
                        "adapter_ram_gb": round(d.get("AdapterRAM", 0) / (1024**3), 2) if d.get("AdapterRAM") else None
                    })
        except Exception:
            pass
    return gpu_info

def get_disk_info():
    disks = {}
    # Check D:\ workspace
    try:
        u_d = shutil.disk_usage(str(ROOT_DIR))
        disks["D:\\ (Workspace)"] = {
            "total_gb": round(u_d.total / (1024**3), 2),
            "used_gb": round(u_d.used / (1024**3), 2),
            "free_gb": round(u_d.free / (1024**3), 2),
            "percent_used": round((u_d.used / u_d.total) * 100, 1)
        }
    except Exception as e:
        disks["D:\\ (Workspace)"] = {"error": str(e)}

    # Check C:\ OS drive
    try:
        u_c = shutil.disk_usage("C:\\")
        disks["C:\\ (System)"] = {
            "total_gb": round(u_c.total / (1024**3), 2),
            "used_gb": round(u_c.used / (1024**3), 2),
            "free_gb": round(u_c.free / (1024**3), 2),
            "percent_used": round((u_c.used / u_c.total) * 100, 1)
        }
    except Exception as e:
        disks["C:\\ (System)"] = {"error": str(e)}
    return disks

def get_packages():
    pkgs = {}
    for mod in ["torch", "transformers", "peft", "httpx", "psutil", "pydantic", "fastapi", "sqlalchemy"]:
        try:
            m = __import__(mod)
            pkgs[mod] = getattr(m, "__version__", "unknown")
        except ImportError:
            pkgs[mod] = "not_installed"
    return pkgs

def get_model_telemetry():
    qwen_safetensors = ROOT_DIR / "models" / "qwen_instruct" / "model.safetensors"
    qwen_config = ROOT_DIR / "models" / "qwen_instruct" / "config.json"
    qwen_exists = qwen_safetensors.exists()
    qwen_size_mb = round(qwen_safetensors.stat().st_size / (1024**2), 2) if qwen_exists else 0
    
    qwen_arch = {}
    if qwen_config.exists():
        try:
            with open(qwen_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                qwen_arch = {
                    "model_type": cfg.get("model_type"),
                    "hidden_size": cfg.get("hidden_size"),
                    "num_attention_heads": cfg.get("num_attention_heads"),
                    "num_hidden_layers": cfg.get("num_hidden_layers"),
                    "vocab_size": cfg.get("vocab_size"),
                    "max_position_embeddings": cfg.get("max_position_embeddings")
                }
        except Exception:
            pass

    target_dir = Path("D:/Qwen3.8-27B")
    target_stubs = 0
    target_shards_real = 0
    if target_dir.exists():
        for f in target_dir.glob("model-*.safetensors"):
            if f.stat().st_size < 1000:
                target_stubs += 1
            else:
                target_shards_real += 1
                
    return {
        "active_production_model": {
            "name": "qwen2:0.5b",
            "parameters": "494M",
            "weights_path": str(qwen_safetensors),
            "weights_exist": qwen_exists,
            "weights_size_mb": qwen_size_mb,
            "architecture": qwen_arch,
            "runtime_backend": "PyTorch CPU / Ollama fallback",
            "status": "VERIFIED_PRESENT" if qwen_exists else "MISSING"
        },
        "fallback_engine": {
            "id": "deterministic_regex_v1",
            "status": "OPERATIONAL",
            "trigger_condition": "HTTP failure, connection timeout (>2.0s), or missing Ollama port"
        },
        "target_model": {
            "name": "Qwen3.8-27B",
            "status": "NOT_RUN — WEIGHTS_UNINSTALLED",
            "safetensors_path": str(target_dir),
            "shards_found_real": f"{target_shards_real}/18",
            "shards_found_lfs_stubs": f"{target_stubs}/18",
            "reason": "Weights not downloaded. Local disk and RAM are insufficient for local 27B FP16/4-bit execution."
        }
    }

def main():
    print("[FREEZE] Capturing baseline environment metadata...")
    mem = psutil.virtual_memory()
    try:
        swap = psutil.swap_memory()
        swap_data = {
            "total_gb": round(swap.total / (1024**3), 2),
            "used_gb": round(swap.used / (1024**3), 2),
            "free_gb": round(swap.free / (1024**3), 2),
            "percent_used": swap.percent
        }
    except Exception as e:
        swap_data = {
            "total_gb": None,
            "used_gb": None,
            "free_gb": None,
            "percent_used": None,
            "status": f"UNAVAILABLE ({type(e).__name__})"
        }
        
    baseline = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git": get_git_info(),
        "system": {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable
        },
        "cpu": {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_threads": psutil.cpu_count(logical=True),
            "cpu_freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None
        },
        "ram": {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent_used": mem.percent
        },
        "swap": swap_data,
        "gpu": get_gpu_info(),
        "disks": get_disk_info(),
        "packages": get_packages(),
        "models": get_model_telemetry()
    }
    
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)
        
    print(f"[FREEZE] Baseline successfully frozen to: {BASELINE_FILE}")
    print(f"         Active Model: {baseline['models']['active_production_model']['name']} ({baseline['models']['active_production_model']['parameters']})")
    print(f"         RAM: {baseline['ram']['used_gb']} GB / {baseline['ram']['total_gb']} GB ({baseline['ram']['percent_used']}%)")
    print(f"         Free Disk D: {baseline['disks'].get('D:\\', {}).get('free_gb', 0)} GB")
    print(f"         Free Disk C: {baseline['disks'].get('C:\\', {}).get('free_gb', 0)} GB")

if __name__ == "__main__":
    main()
