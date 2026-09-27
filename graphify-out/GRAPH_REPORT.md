# Graph Report - scripts/training  (2026-09-26)

## Corpus Check
- Corpus is ~21,278 words - fits in a single context window. You may not need a graph.

## Summary
- 206 nodes · 348 edges · 12 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Corpus Builder Pipeline|Corpus Builder Pipeline]]
- [[_COMMUNITY_GGUF Conversion & Export Matrix|GGUF Conversion & Export Matrix]]
- [[_COMMUNITY_BPE Corpus & Adequacy Gate|BPE Corpus & Adequacy Gate]]
- [[_COMMUNITY_SFT  DPO Training & Smoke Test|SFT / DPO Training & Smoke Test]]
- [[_COMMUNITY_comp001 Training Run|comp001 Training Run]]
- [[_COMMUNITY_Context Extension (YaRN + LoRA)|Context Extension (YaRN + LoRA)]]
- [[_COMMUNITY_Dataset Assembly|Dataset Assembly]]
- [[_COMMUNITY_Context Extension Verification|Context Extension Verification]]
- [[_COMMUNITY_BPE Tokenizer Training|BPE Tokenizer Training]]

## God Nodes (most connected - your core abstractions)
1. `top_up()` - 21 edges
2. `build()` - 18 edges
3. `main()` - 17 edges
4. `convert()` - 11 edges
5. `main()` - 10 edges
6. `emit_adequacy_gate()` - 10 edges
7. `STReader` - 9 edges
8. `ShardWriter` - 8 edges
9. `TrainingRunRecord` - 8 edges
10. `get_git_commit()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `iter_source_rows()` --calls--> `load_dataset()`  [INFERRED]
  corpus_builder.py → orion_train.py
- `main()` --calls--> `TrainingRunRecord`  [EXTRACTED]
  extend_context.py → e2e_training_smoke_test.py
- `main()` --calls--> `get_git_commit()`  [EXTRACTED]
  extend_context.py → e2e_training_smoke_test.py
- `main()` --calls--> `STReader`  [EXTRACTED]
  export_gguf_matrix.py → convert_hf_to_gguf.py
- `deploy()` --calls--> `convert()`  [EXTRACTED]
  deploy_orion.py → convert_hf_to_gguf.py

## Communities (12 total, 0 thin omitted)

### Community 0 - "Corpus Builder Pipeline"
Cohesion: 0.10
Nodes (39): build(), check_leak(), chunk_doc(), _cleanup_cache(), dataset_license(), dry_run(), ensure_disk(), _existing_parts() (+31 more)

### Community 1 - "GGUF Conversion & Export Matrix"
Cohesion: 0.10
Nodes (25): build_vocab(), convert(), load_json(), _np_roundf(), quant_q4_0_along(), quant_q8_0_along(), llama.cpp roundf semantics (round half away from zero), mirror of gguf.quants., Pack F32 weights into GGML Q8_0 blocks (f16 scale d + 32 x i8, dequant     d*qs (+17 more)

### Community 2 - "BPE Corpus & Adequacy Gate"
Cohesion: 0.09
Nodes (26): BpeCompatTokenizer, corpus_bytes(), corpus_sha256(), count_corpus_tokens(), emit_adequacy_gate(), format_sample(), _git_commit(), iter_texts() (+18 more)

### Community 3 - "SFT / DPO Training & Smoke Test"
Cohesion: 0.14
Nodes (19): compute_file_sha256(), create_sample_dataset(), get_git_commit(), Create a high-density 4-sample emergency triage dataset., run_training_smoke_test(), TrainingRunRecord, load_preferences(), _logprob_loss() (+11 more)

### Community 4 - "comp001 Training Run"
Cohesion: 0.13
Nodes (25): arg_parser(), build_model(), checkpoint_dir(), dir_size(), export_hf(), find_latest_checkpoint(), load_checkpoint(), load_data() (+17 more)

### Community 5 - "Context Extension (YaRN + LoRA)"
Cohesion: 0.23
Nodes (13): apply_yarn(), attach_lora(), build_long_windows(), dataset_hash(), load_base(), main(), niah_probe(), preflight() (+5 more)

### Community 6 - "Dataset Assembly"
Cohesion: 0.36
Nodes (10): build(), build_preferences(), codex_samples(), compute_sha256(), extracted_samples(), _header_doctext(), load_models_sizes(), preference_samples() (+2 more)

### Community 7 - "Context Extension Verification"
Cohesion: 0.43
Nodes (6): load_extended(), long_filler(), main(), probe(), If a merged standalone model dir exists use it; else base + LoRA adapter., Deterministic filler text long enough to reach `tokens_goal` tokens.

### Community 8 - "BPE Tokenizer Training"
Cohesion: 0.60
Nodes (4): main(), HF layout: tokenizer_config.json / special_tokens_map.json / added_tokens.json., train_bpe(), _write_hf_sidecars()

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `iter_source_rows()` connect `Corpus Builder Pipeline` to `SFT / DPO Training & Smoke Test`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `load_dataset()` connect `SFT / DPO Training & Smoke Test` to `Corpus Builder Pipeline`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **What connects `HF layout: tokenizer_config.json / special_tokens_map.json / added_tokens.json.`, `Minimal safetensors reader: header offsets + raw byte reads (numpy).     No tor`, `llama.cpp roundf semantics (round half away from zero), mirror of gguf.quants.` to the rest of the system?**
  _50 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Corpus Builder Pipeline` be split into smaller, more focused modules?**
  _Cohesion score 0.09725158562367865 - nodes in this community are weakly interconnected._
- **Should `GGUF Conversion & Export Matrix` be split into smaller, more focused modules?**
  _Cohesion score 0.10037878787878787 - nodes in this community are weakly interconnected._
- **Should `BPE Corpus & Adequacy Gate` be split into smaller, more focused modules?**
  _Cohesion score 0.09090909090909091 - nodes in this community are weakly interconnected._
- **Should `SFT / DPO Training & Smoke Test` be split into smaller, more focused modules?**
  _Cohesion score 0.13675213675213677 - nodes in this community are weakly interconnected._