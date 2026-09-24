# ORION Knowledge Graph

> *Static knowledge graph representation - interactive graph view available in Obsidian. Not natively animated, but nodes/links are fully navigable.*

## God Nodes (Key Concepts)

| Node | Category | Description |
|------|----------|-------------|
| `110M Model` | Model | 110,918,656 params, 11 layers, hidden 768, vocab 10240, untied lm_head; checkpoint-1919 is true latest (export stale at 1869) |
| `Forensic Audit` | Audit | F1-F7 complete: identity VERIFIED, learning CONFIRMED, provenance PARTIALLY_SUPPORTED, eval at/below chance, 2 harness defects found |
| `HellaSwag` | Benchmark | 0.210 acc vs 0.25 chance; ORION set 0.025 vs 0.063 chance; char-frequency baseline beats model |
| `Integrity Controls` | Controls | 4PASS/2FAIL: C4 layout-sensitive ppl, C5 silent corruption under weights_only+mmap; 0 memorization |
| `Quantization` | Profiling | f16/q8_0 RUNNABLE via BitNet llama-cli; q4_0 also RUNNABLE; Q4_K_M BLOCKED (no llama-quantize); quant loss in noise (SNR q8 45.15dB, q4 21.05dB) |
| `Stress Test` | Reliability | Bit-exact crash-resume (pre-kill loss == post-resume, delta 0.0); leak slopes negative; 2 defects: (1) --model-size 10m unrunnable with real vocab, (2) non-atomic checkpoint save leaves unreadable tail |
| `Ledger` | Provenance | 3 invocations in training_runs.jsonl; cumulative 586,027 tokens = 0.918% corpus; double-count hazard (naive 867,840 wrong by +48%); best ckpt by val loss = 623 (7.6228) |

## Key Links (Edges)

- `110M Model` → `Forensic Audit` : model identity and learning proof were audited
- `Forensic Audit` → `Integrity Controls` : 2 genuine harness defects discovered during stress testing
- `Forensic Audit` → `Quantization` : GGUF runnable formats + Q4_K_M blockage confirmed
- `Forensic Audit` → `Stress Test` : crash-resume bit-exact; 2 harness defects documented
- `Forensic Audit` → `Ledger` : budget fraction, third-run discovery, hash mismatch
- `Integrity Controls` → `Quantization` : C5 silent-corruption finding (mid-file byte flip loads silently)
- `Eval Results` → `Quantization` : char-frequency baseline beats model; all MC at/below chance
- `Stress Test` → `Ledger` : training harness uses same checkpoint IoU pattern as forensic ledger

## Community Structure (Simplified)

- **Model** (110M, architecture, weights) 
- **Forensic** (audit, provenance, integrity, stresses)
- **Benchmarks** (HellaSwag, ARC, WinoGrande, ORION set, ppl)
- **Profiling** (format runnability, quant retention, BitNet ref)
- **Integrity** (controls, memorization, generations)

## Obsidian Graph View Notes

- Create backlink/outgoing-link panes to traverse between these nodes
- Use `[[110M Model]]`, `[[Forensic Audit]]`, etc. as wikilinks
- The graph view (graph.json configured) will show community-colored nodes
- **Animation**: Static only - Obsidian graph view has no native animation. Interactive: drag, zoom, click-to-expand. Community detection runs once; nodes reposition on each enter-key refresh.

## Suggested Questions (for graph navigation)

1. **How does the model identity connect to the eval results?** → Path: `110M Model` → `Forensic Audit` → `HellaSwag` → shows all MC results at/below chance
2. **What do the integrity control failures reveal about checkpoint handling?** → Path: `Integrity Controls` → `Stress Test` → documents non-atomic save and silent corruption
3. **How does the ledger budget fraction relate to the eval performance?** → Path: `Forensic Audit` → `Ledger` → shows 0.918% corpus → eval at/below chance (consistent with under-training)

--- 

*Last updated: 2026-09-24*

*Generated from forensic phases F1-F7. See individual forensic write-ups for detailed per-phase evidence. The graph above is a static summary - for dynamic navigation, use Obsidian's graph view with the above wikilinks.*