# ORION: Model Architecture, Target 27B Pipeline & Verification

> **Active Production Model:** `qwen2:0.5b` (Ollama 4-bit / 352 MB)  
> **Physical Baseline Model on Disk:** `merged.f16.gguf` (948 MB, Qwen2.5-0.5B fine-tuned)  
> **Target Research Architecture:** `Qwen/Qwen3.8-27B` (`Qwen3_5ForConditionalGeneration`) — **UNINSTALLED (0/18 shards on disk)**  
> **Repository:** `Team-Auralis/orion`  
> **Verification Date:** September 13, 2026

---

## 1. Executive Status & Model Disambiguation

To eliminate all ambiguity across the project, the models are categorized as follows:

| Category | Model Identifier | Physical State | Runtime Role |
|---|---|---|---|
| **Production Model** | `qwen2:0.5b` | Installed in Ollama (352 MB) | Serves live triage in `services/ai_sentinel/` |
| **Local Baseline GGUF** | `merged.f16.gguf` | Present on disk (948 MB) | Local fine-tuned baseline artifact |
| **Target Research Model** | `Qwen3.8-27B` | 0/18 shards present (Git LFS stubs only) | Target architecture for future scaling |
| **Fallback Engine** | `deterministic_regex_v1` | Compiled in Python | Engaged if Ollama times out or goes offline |

---

## 2. Hardware Constraints & Storage Reality

| Dimension | Raw 16-Bit Target (BF16) | 4-Bit Quantized Target (Q4_K_M) | Host Machine Reality |
|---|---|---|---|
| **Storage Requirement** | **55.6 GB** (18 shards) | **~15.5 GB** | Drive D: **26.24 GB free** |
| **GPU VRAM** | ~60 GB (A100/H100) | ~14–16 GB | NVIDIA RTX 3050 Laptop (**4.0 GB VRAM**) |
| **System RAM** | 64+ GB | 16–32 GB | **7.74 GB RAM** (~500 MB free) |

### Physical Storage Boundary:
- The Hugging Face repository `D:\Qwen3.8-27B` tracks 18 `.safetensors` files totaling **55.6 GB**.
- Pulling raw 55.6 GB shards onto Drive D (26.24 GB free) will cause a **Disk Full crash** at ~25 GB.
- **Physical Feasibility Rule:** The 27B model can only run locally if a **pre-quantized 4-bit GGUF (~15.5 GB)** is procured, or if training/inference is dispatched to cloud GPU instances via `soup plan` / `soup apply`.

---

## 3. Training & Adaptation Specification (Target)

The training harness is configured to target Qwen 27B via 4-bit QLoRA:

- **Target Base:** `D:/Qwen3.8-27B` (or `Qwen/Qwen3.5-27B` / `Qwen/Qwen3.8-27B`)
- **Quantization:** `4bit` (NF4 via layer streaming)
- **LoRA Hyperparameters:**
  - Rank ($r$): 16
  - Alpha ($\alpha$): 32
  - Target Modules: Attention & MLP projections
- **Layer Streaming:** `stream_layers: true` (evaluates transformer blocks sequentially to prevent out-of-memory crashes on consumer hardware)
- **Execution Guard:** `scripts/train_orion.py` strictly prevents starting training if weight shards are missing.

Configuration file: `scripts/soup.yaml`

---

## 4. Multi-Domain Training Dataset

The dataset in `scripts/data.jsonl` provides instruction-tuning data for ORION's cognitive domains:
1. **AURA Triage:** Incident classification, hazard containment.
2. **OMNIS World Model:** Causal DAG evaluation, contradictory sensor detection.
3. **NEXUS Arbitration:** Multi-agent constraint reconciliation.
4. **FORGE Discovery:** Simulation-based hypothesis generation.
5. **ASCEND Planning:** Decadal transition milestones.
6. **CIC Intent Conservation:** Audit logging and intent drift detection.
7. **VEIL Governance:** Zero-trust actuation and geofence enforcement.

Recompile dataset at any time:
```powershell
python scripts/build_aura_dataset.py
```

---

## 5. Benchmark Integrity & Policy Notice

> [!IMPORTANT]
> **ORION RESEARCH POLICY: NO BENCHMARK FABRICATION OR MODEL-CARD INFERENCE.**
>
> 1. Standard open benchmarks (MMLU, GSM8K, HumanEval, IFEval) were **NOT** executed by this project on any 27B model.
> 2. Literature values from external model cards must **never** be cited as ORION system performance.
> 3. The only benchmarks run on ORION are the simulation-based **ACI-001 through ACI-008** test suites.
> 4. The 27B model has **never** been evaluated on the ACI benchmark suite.

---

## 6. Execution Commands

### Diagnostic Plan (Soup Pre-flight):
```powershell
python scripts/train_orion.py --mode plan
```

### Forensic Pipeline Verification:
```powershell
python scripts/verify_27b_readiness.py
```

### Baseline Ollama Registration:
```powershell
ollama create orion-baseline -f Modelfile
```

### Target 27B Ollama Registration (After procuring GGUF):
```powershell
# Requires ./models/qwen27b.Q4_K_M.gguf (~15.5 GB) on disk
ollama create orion-27b -f Modelfile.27b
```
