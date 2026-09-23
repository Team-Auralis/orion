# BitNet b1.58-2B-4T — Windows install & run path (reference arm, Task 6)

> **Status on this box: NEEDS_RUNTIME — documented only, not executed.**
> Nothing below has been run here. Two things deliberately stand between this
> laptop and a running BitNet 2.4B: (1) the **bitnet.cpp runtime** (ternarized
> I1_S kernels, a llama.cpp fork) is not built or on PATH, and (2) fetching
> the model itself is a **~2 GB download** from the Hugging Face hub, which is
> out of budget on this offline-friendly task. This doc is the concrete path
> so the T7 report can cite exact commands.

## Why the target is realistic
`microsoft/BitNet-b1.58-2B-4T` is a 2.4B-param model with **native ternary
(+-1/0) 1.58-bit weights** — the non-embedding footprint is ~0.4 GB at 1 bit,
and a full inference resident estimate is **~0.9-1.2 GB**, comfortably under
the 3 GB guard. bitnet.cpp is CPU-first (no CUDA needed), so a 7.7 GB RAM
CPU-only laptop can host it — once the runtime exists.

## 1. Get bitnet.cpp (Windows)

Pick ONE path:

### 1a. Prebuilt release (easiest, no toolchain)
1. Go to <https://github.com/microsoft/BitNet/releases>.
2. Look for a Windows asset (the project ships prebuilt binaries in releases;
   naming has varied — if no Windows asset exists, fall through to 1b).
3. Unzip to e.g. `D:\orion\third_party\bitnet.cpp`, then
   `set PATH=D:\orion\third_party\bitnet.cpp\build\bin\Release;%PATH%`
   (or wherever `run.exe` / `llama-b1.58-run.exe` lands).

### 1b. Build from source (needs a Windows toolchain)
Prerequisites: Visual Studio 2022 with the "Desktop development with C++"
workload + CMake >= 3.24 (or Git Bash + make + MinGW).

```bat
git clone https://github.com/microsoft/BitNet.git third_party\bitnet.cpp
cd third_party\bitnet.cpp
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j
REM binary lands at: build\bin\Release\run.exe
```

## 2. Get the model weights (~2 GB — the big download, NOT performed here)

### 2a. Convert from the Hugging Face hub
```bat
REM 1. pull the hub repo (large; uses git-lfs or hf transfers)
git lfs install
git clone https://huggingface.co/microsoft/BitNet-b1.58-2B-4T models\bitnet-b1.58-2B-4T
REM    (or: huggingface-cli download microsoft/BitNet-b1.58-2B-4T --local-dir models\bitnet-b1.58-2B-4T)

REM 2. convert to the I1_S "1.58-bit" GGUF (script lives in the bitnet.cpp repo)
cd third_party\bitnet.cpp
python utils\convert_hf_to_gguf.py --outtype i1_s --model-name ../../../models/bitnet-b1.58-2B-4T
REM produces: models\i1_s\ggml-model-i1_s.gguf
```

### 2b. Pre-converted GGUF (skip the convert step)
The community hosts pre-converted GGUF, e.g.
`microsoft/BitNet-b1.58-2B-4T-gguf`. The readiness harness's `--fetch`
metadata probe confirmed live on 2026-09-23: the repo exists and carries
**`ggml-model-i2_s.gguf`** (i2_s, not i1_s — the actual shipped pre-converted
file). Download just that one file (~0.9-1.2 GB) instead of the whole HF
repo, then point step 3 at it.

## 3. Inference (one command)
```bat
build\bin\Release\run.exe -m models\i1_s\ggml-model-i1_s.gguf -p "Daniel is a" -n 128 -t 6
```
(If you used the 2b pre-converted file, point `-m` at `ggml-model-i2_s.gguf`
instead — that is the filename the hub actually ships.)
`-t 6` matches this box's 6 physical cores. Expect **single-digit to low
double-digit tok/s** on 2.4B ternary weights — the point of the reference arm.

## 4. Honesty box — what was NOT done and why
| Step | Why skipped here |
|------|------------------|
| Building bitnet.cpp | Needs Visual Studio/CMake toolchain + a build; task forbids installs. |
| HF hub fetch (~2 GB) | Offline-friendly budget; a fetch here would blow the task budget. |
| Conversion to I1_S | Needs the hub weights first. |
| Quality probe / tok/s measurement | Needs the runtime + weights; recorded as `NOT_MEASURED_NEEDS_RUNTIME`. |

When the runtime + weights exist, re-run
`python scripts/reference/bitnet_readiness.py` — the binary check flips to
PRESENT and, if headroom holds, the verdict becomes RUNNABLE. Then
`scripts/reference/bitnet_vs_comp001.py` picks the BitNet row up as measured.