# BitNet b1.58-2B-4T — Windows install & run path (reference arm, Task 7)

> **Status on this box: EXECUTED + VERIFIED (2026-09-24).** The reference path
> below is what actually ran end-to-end on this laptop, with measured numbers.
> Single source of truth for the numbers: the `bitnet-2b4t-reference` ledger
> row and `scripts/reference/run_ref_measured.py`.

## What the reference arm proved
`microsoft/BitNet-b1.58-2B-4T-gguf/ggml-model-i2_s.gguf` (2.4B params, ternary
1.58-bit I2_S) runs on this 7.7 GB RAM CPU-only laptop via the official
bitnet.cpp runtime (llama.cpp fork `b1-390c307`):

| metric | value |
|--------|-------|
| model file | 1,187,801,280 B = 1132.8 MB |
| peak RSS (sampled) | **1238 MB** |
| generation speed | **13.4 t/s** (6 threads; runs sampled 10.5–13.4 t/s) |
| prompt speed | 72.4 t/s |
| eval latency (16 tokens) | ~1194 ms |
| exit code | 0 |
| outside-the-box floor | measured 1238 MB < 3 GB guard |

The Task-6 estimate (1075 MB resident) was **within ~15% of the measured
1238 MB** — the estimate was sound.

## 1. Get bitnet.cpp (Windows) — what actually worked

1. NOT prebuilt: **`https://api.github.com/repos/microsoft/BitNet/releases/latest`
   returns 404 — the repo ships NO GitHub releases**, so "download a prebuilt
   Windows zip" is not an option for this repo.
2. Build/reuse from source with **MinGW** (Visual Studio NOT required):

```bat
git clone --depth 1 https://github.com/microsoft/BitNet.git third_party\BitNet
cd third_party\BitNet
cmake -S . -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build build --target llama-cli -j 2
REM binary lands at: build\bin\llama-cli.exe   (15.5 MB)
```

- Toolchain used here: WinLibs mingw64 gcc/g++ (UCRT POSIX), CMake 4.3.3
  (`C:\Program Files\CMake`), generator `MinGW Makefiles`, `-j 2` to keep the
  build inside this box's RAM. Full build ≈ 10 min on 6 cores, ~110 MB of build
  output (only the `llama-cli` target was needed; `cmake --build build -j`
  builds all examples incl. llama-server).
- On this box the target was already built by the Task-6 cycle from the same
  checkout (commit `0b341e5`, llm submodule `390c307`); T7 verified it with
  `cmake --build build --target llama-cli` (exit 0) before use.

> The inference binary is **`llama-cli.exe`**, not `run.exe`: in the current
> unified repo the CLI ships as llama.cpp's `llama-cli`. `run_inference.py`
> wraps it (`build/bin/Release/llama-cli.exe`).
> `scripts/reference/bitnet_readiness.py` now recognizes
> `third_party/BitNet/build/bin/llama-cli.exe` as the runtime.

## 2. Get the model weights — what actually worked

Pre-converted GGUF from the hub (`i1_s` does NOT exist on this repo — the file
actually shipped is `i2_s`, which is what the I2_S kernels run):

This box used a plain streaming HTTP GET of
`https://huggingface.co/microsoft/BitNet-b1.58-2B-4T-gguf/resolve/main/ggml-model-i2_s.gguf`
→ `models\bitnet-b1.58-2B-4T\ggml-model-i2_s.gguf`.
Download took ~6 min at ~3.1 MB/s; byte count verified against the HF API
(1,187,801,280 B, exact match).

## 3. Inference — what actually ran

```bat
third_party\BitNet\build\bin\llama-cli.exe -m models\bitnet-b1.58-2B-4T\ggml-model-i2_s.gguf ^
    -p "Daniel is a" -n 16 -t 6 -ngl 0 -c 512 --temp 0.8 --no-display-prompt --single-turn
```

Generation snippet (16 tokens, seed-dependent):

    the name of the person you want to know is Daniel and the name of the

Measured wrapper (samples peak RSS, parses tok/s, writes the ledger row):

```bat
python scripts\reference\run_ref_measured.py -p "Daniel is a" -n 16 -t 6
python scripts\reference\run_ref_measured.py --self-test   REM parser check, no run
```

`--single-turn` is required so the CLI exits after generation instead of
dropping into the REPL. This fork reports speed as
`[ Prompt: 72.4 t/s | Generation: 13.4 t/s ]` instead of the classic
`llama_print_timings` block; the wrapper parses both.

## 4. Honesty box
| Step | Reality |
|------|---------|
| Disk floor | The brief's ~8 GB floor was ALREADY violated at start (D: free = 4.75 GB); the task completed at ~4.74 GB free. Model 1.13 GB + clone/build ~0.4 GB fit; nothing was evicted. Cannot show "final > 8 GB" truthfully. |
| tot speeds | 10.5 / 12.0 / 13.4 t/s across three runs — CPU/RAM contention on this box; ledger stores the last (13.4). |
| No GPU | `-ngl 0`, CPU-only, as required. "no usable GPU" warning is expected. |
| RAM contention | 393–1772 MB available during the session (other processes); the reference peaked at 1238 MB and completed. Instantaneous readinness verdicts fluctuated NEEDS_RUNTIME → NO_HEADROOM despite the run succeeding. |