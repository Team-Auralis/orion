# ORION: Qwen 27B Training, Adaptation & Deployment Guide

> **Architecture:** Qwen 3.8 27B / Qwen 3.5 27B (`Qwen3_5ForConditionalGeneration`)  
> **Subsystem:** SENTIENCE AI / AURA Cognitive Core  
> **Repository:** `Team-Auralis/orion`  
> **Status:** Configured and Verified

---

## 1. Overview & Objective

Project ORION previously utilized a compact 500M parameter model (`Qwen2.5-0.5B`) for emergency triage prototyping. To support civilization-scale coordination, causal world modeling (OMNIS), and multi-agent dispute resolution (NEXUS), the project is upgrading its target reasoning core to **Qwen 27B** (`Qwen3.8-27B`).

---

## 2. Hardware & Storage Physical Reality

| Dimension | Raw 16-Bit Model (BF16) | 4-Bit Quantized (Q4_K_M / NF4) | Host Environment |
|---|---|---|---|
| **Weight File Size** | **55.6 GB** (18 shards) | **~15.5 GB** | Drive D: **26.24 GB free** |
| **VRAM Requirement** | ~60 GB (A100/H100) | ~14–16 GB VRAM / CPU offload | GPU: **4 GB (RTX 3050 Laptop)** |
| **System RAM** | 64+ GB | 16–32 GB | System RAM: **8 GB** |

### Critical Storage Insight:
- The raw HuggingFace repository in `D:\Qwen3.8-27B` tracks 18 `.safetensors` shards totaling **55.6 GB**.
- Because Drive D has **26.24 GB free**, attempting to run an unquantized `git lfs pull` of all 55.6 GB shards will cause a **Disk Full error** (~25 GB in).
- **The Solution:** We train using **4-bit Quantization (NF4/QLoRA)** with layer streaming via `soup`, or deploy a **4-bit GGUF (~15.5 GB)** which fits comfortably inside the 26.24 GB free space.

---

## 3. Training Architecture: QLoRA & Layer Streaming

The project uses `soup-cli` and HuggingFace PEFT to fine-tune a LoRA adapter rather than modifying all 27 billion weights:

- **Base Model:** `D:/Qwen3.8-27B`
- **Quantization:** `4bit` (NF4 via bitsandbytes / layer streaming)
- **LoRA Hyperparameters:**
  - Rank ($r$): 16
  - Alpha ($\alpha$): 32
  - Target Modules: Attention projections (`q_proj`, `k_proj`, `v_proj`, `o_proj`) & MLP (`gate_proj`, `up_proj`, `down_proj`)
- **Memory Optimization:**
  - `stream_layers: true` (evaluates transformer layers sequentially, avoiding resident 27B memory spikes)
  - `gradient_accumulation_steps: 8`
  - `batch_size: 1`

Configuration file: `scripts/soup.yaml`

---

## 4. Multi-Domain Training Dataset

The training dataset in `scripts/data.jsonl` contains instruction-response pairs covering all ORION civilizational domains:

1. **AURA Triage:** Flash flood, hazmat, emergency medical dispatch.
2. **OMNIS World Model:** Causal DAGs, resolving contradictory sensor readings, false transfer rejection.
3. **NEXUS Arbitration:** Multi-agent dispute resolution (Energy vs Healthcare vs Economy).
4. **FORGE Discovery:** Scientific hypothesis generation and simulation-based validation.
5. **ASCEND Planning:** Decadal renewable transition milestones and adaptive replanning.
6. **CIC Intent Conservation:** Auditing unintended algorithmic drift against founding intent vectors.
7. **VEIL Governance:** Zero-trust actuation rejections and geofence boundary enforcement.

Compile the dataset at any time:
```powershell
python scripts/build_aura_dataset.py
```

---

## 5. Execution Commands

### Generate Pre-Flight Training Plan:
```powershell
python scripts/train_orion.py --mode plan
```

### Run Full Verification Suite:
```powershell
python scripts/verify_27b_readiness.py
```

### Execute Training:
```powershell
python scripts/train_orion.py --mode train
```

### Deploy to Ollama:
```powershell
ollama create orion-27b -f Modelfile
ollama run orion-27b
```

---

## 6. Verification Status

All pipeline components have been verified:
- [x] Tokenizer: 248,077 tokens (Qwen3.8 native)
- [x] Dataset: 16 high-density civilizational samples formatted for ChatML
- [x] Soup Config: Validated via `soup plan`
- [x] Modelfile: ChatML `<|im_start|>` template with civilizational system prompt
- [x] Hardware Safeguards: Pre-flight disk space calculation prevents 55.6 GB storage overflow
