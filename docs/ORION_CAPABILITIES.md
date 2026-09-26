# ORION Capabilities (laptop-trainable stack)

Everything below runs on the development laptop (CPU-only, ~8 GB RAM). Status
labels follow the repository's honesty discipline: **VERIFIED** (mechanism
proven end-to-end with real output), **UNPROVEN** (built but not proven to
produce fluent results), **BLOCKED** (requires hardware we do not have).

## 1. Context window extension (YaRN) — `scripts/training/extend_context.py`
ORION 100M was trained with `max_position_embeddings=512`. This applies YaRN
rope scaling (factor 8 => max_pos 4096), runs a short LoRA continued-pretrain
pass on long packed windows, and produces a standalone merged model
(`models/comp001/100m-context8k-merged`) with the scaling baked into
`config.json`.

- **VERIFIED:** the model loads and generates at 2K/4K prompt lengths with no
  indexing errors; RoPE scaling is correctly persisted and round-trips.
- **UNPROVEN:** needle-in-a-haystack retrieval at 2K/4K is `False` at all
  depths. The 100M was never trained to do retrieval; the short pass moved loss
  only ~0.6% (noise). This is a mechanics flag, not a capability claim.

## 2. Teacher distillation — `scripts/teacher/`
`generate_curriculum.py` pulls live Q&A from the local Ollama model
(`qwen2.5:3b`) into `data/training/teacher_curriculum.jsonl` (20 rows, temp 0.3,
all answers verified correct). `distill_train.py` LoRA-SFTs ORION 100M on the
teacher's answers.

- **VERIFIED:** loss 6.33 -> 6.14 (−3.06%) on 64 train rows; eval loss 5.58;
  adapter logit delta `True` (per-token mean 5e-4). End-to-end pipeline works
  and is audited in `logs/training_runs.jsonl`.
- **UNPROVEN:** generated answers are not yet fluent Q/A. A 100M model
  recovering from 0.9%-of-corpus training needs far more curriculum than 64
  examples; the recipe is the point, not yet the outcome.

## 3. Vision (read images) — `orion_runner/vision.py`
ORION is a text model. `describe(image)` routes an image through
Florence-2-base (0.23B, CPU) and returns a caption ORION can reason over. This
is an honest pipeline — the vision encoder and ORION are separate; ORION reads
the description.

- **VERIFIED:** captioned a real test image: `three primary colors`.

## 4. Image generation — `orion_runner/gen.py`
`generate(prompt, out)` runs `segmind/tiny-sd` (distilled SD, ~1 GB, CPU) at
512x512, 8 steps.

- **VERIFIED:** generated a real 512x512 RGB PNG from
  `"a small cute robot waving hello, flat vector style"` (258 KB) in a few
  minutes on CPU.
- Note: CPU here means minutes per image and serviceable-not-photorealistic
  output. No GPU exists on this box.

## 5. Voice / TTS — `orion_runner/voice.py`, `scripts/orion_speak.py`
`speak(text)` uses Microsoft Edge neural voices via `edge-tts` (natural, needs
internet) with a Windows SAPI fallback (offline, zero deps). `orion_speak.py`
is the CLI wrapper.

- **VERIFIED:** produced a real audio file from
  `"Hello, I am ORION. Voice online."` — 25 KB, playable.

## 6. Low-memory inference — `orion_runner/airllm_bridge.py` (airllm 4.0.0)
Layer-wise inference: airllm streams one layer at a time from disk, so peak
RAM stays flat (~386 MB measured) at the cost of disk I/O per token. The
bridge adds an honest `disk_gate()` that refuses any model that cannot fit
free disk minus a 1.5 GB margin BEFORE any download, plus an opt-in
`teacher_answer()` backend (the default teacher remains Ollama qwen2.5:3b).

- **VERIFIED:** real CPU generation on Qwen2.5-0.5B-Instruct — 16 tokens in
  108.5 s, peak RSS flat at 386 MB:
  `'Hello, I am ORION. I have been created by the Orion Project as a virtual
  assistant that helps people find'`
- **BLOCKED (by disk, not RAM):** Qwen2.5-7B (~15.2 GB) cannot fit the 8.6 GB
  free on D:; measured by `scripts/tools/probe_airllm.py`. 3B (~6.2 GB) is
  MARGINAL (0.9 GB headroom after margin) and already runs faster via Ollama.
  airllm buys model size at the cost of latency — CPU layer streaming is
  tens of seconds per token, not a speedup over Ollama.
- Pinned `airllm==4.0.0` in `requirements-airllm.txt` (no torch/transformers
  downgrade verified via `pip install --dry-run`).

## 7. Architecture diagrams — archify skill (vendored) + generated ORION map
The `archify` agent skill (MIT) is vendored at `.agents/skills/archify/`
(project-local; node-based, zero-dependency renderers; `skills-lock.json`
records the source hash). It turns a typed JSON IR into an explorable,
self-contained HTML diagram (inline SVG, dark/light themes, trace motion).

- **VERIFIED:** `docs/ORION_ARCHITECTURE.html` (813 KB) generated from
  `docs/ORION_ARCHITECTURE.source.json`; 9/9 quality checks, 0 errors,
  0 warnings; delivers a SHA-256 receipt on every run (artifact
  `9423ccf0...`). Primary path is grounded in real code: Haven UI →
  Keycloak token → `POST :8001/v1/incidents` → NATS `incident.created`
  (durable `sentience_ai`) → ai_sentinel → Ollama / fallback engine.
- Reproducible: `node .agents/skills/archify/bin/archify.mjs deliver
  architecture docs/ORION_ARCHITECTURE.source.json
  docs/ORION_ARCHITECTURE.html --quality showcase --json`

## 8. Screen vision + confirmed actions — `orion_runner/screen.py`, `scripts/orion_see.py`, `scripts/orion_act.py`

ORION can "see your screen" through the same honest bridge as section 3: a
screenshot is captured with PIL `ImageGrab` and captioned by Florence-2-base
(CPU, ~0.23B), so ORION works from the *description*, never from raw pixels.
Actions are a **whitelist only**, and every action asks `confirm? [y/N]`
before executing; ORION never derives an action from text found on screen.

- `python scripts/orion_see.py` — live capture + caption
  (VERIFIED: desktop captioned in real time; shots in `data/screenshots/`).
- `python scripts/orion_act.py` — confirm-first loop: `open <app|url|file>`
  via `os.startfile` (zero deps), plus `type <text>` / `key <name>` /
  `click` when the optional `pyautogui` package is installed. Every attempt
  is logged to `logs/orion_actions.jsonl` (confirmed / aborted / error).
- **VERIFIED:** `open notepad` confirmed → Notepad launched, screen
  re-captured + re-described; an aborted run recorded `"confirmed": false`.
- **Not (yet):** full autonomous UI-driving by ORION itself — the 100M
  model's instruction-following is UNPROVEN, so choosing the action stays
  with the user; this module is the safe, honest bridge.
- **Small vision-action SFT (experiment, honest negative):** a 192-row
  synthetic run teaching ORION to pick a whitelist verb from
  `caption + user request` converged (loss 7.27 → 4.00, run
  `teach-distill-b63388c3`) but generation does not yet emit whitelisted
  verbs on held-out rows (0/10 greedy and sampled) — recorded in
  `logs/training_runs.jsonl`; the model latched onto the `A:` format
  scaffolding instead of the action mapping.

## How the pieces fit
```
Image ──► vision.py (Florence-2) ──► caption ──► ORION (100M)
Text  ──► gen.py (tiny-sd) ──► PNG
Teacher (Ollama qwen2.5:3b) ──► curriculum ──► distill_train.py ──► ORION LoRA
Bigger teacher (airllm bridge) ──► layer-streamed from disk (gate: free disk)
Text  ──► voice.py (edge-tts/SAPI) ──► audio
Context: 512 ─► YaRN ─► 4096 (extend_context.py)
Repo  ──► archify skill ──► docs/ORION_ARCHITECTURE.html (interactive map)
```

## Reproducibility
- Teacher curriculum: `python scripts/teacher/generate_curriculum.py`
- Distill: `python scripts/teacher/distill_train.py`
- Context extend: `python scripts/training/extend_context.py`
- Vision self-check: `python -m orion_runner.vision`
- Generation self-check: `python -m orion_runner.gen`
- Voice: `python scripts/orion_speak.py "Hello I am ORION" --play`
- Low-memory inference probe: `python scripts/tools/probe_airllm.py`
- Low-memory inference self-check: `python -m orion_runner.airllm_bridge`
- Archify diagram: `node .agents/skills/archify/bin/archify.mjs deliver
  architecture docs/ORION_ARCHITECTURE.source.json
  docs/ORION_ARCHITECTURE.html --quality showcase --json`