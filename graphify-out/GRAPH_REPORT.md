# Graph Report - models/orion_custom_lora  (2026-09-09)

## Corpus Check
- Large corpus: 16 files � ~2,426,947 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 531 nodes · 531 edges · 44 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_LoRA Adapter Configuration|LoRA Adapter Configuration]]
- [[_COMMUNITY_Base Adapter Metadata|Base Adapter Metadata]]
- [[_COMMUNITY_Checkpoint Adapter Metadata|Checkpoint Adapter Metadata]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Checkpoint 12 Trainer State|Checkpoint 12 Trainer State]]
- [[_COMMUNITY_Checkpoint 3 Trainer State|Checkpoint 3 Trainer State]]
- [[_COMMUNITY_Tokenizer Configuration|Tokenizer Configuration]]
- [[_COMMUNITY_Base Tokenizer Configuration|Base Tokenizer Configuration]]
- [[_COMMUNITY_Model Card Evidence|Model Card Evidence]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]
- [[_COMMUNITY_Tokenizer Vocabulary|Tokenizer Vocabulary]]

## God Nodes (most connected - your core abstractions)
1. `added_tokens_decoder` - 23 edges
2. `added_tokens_decoder` - 23 edges
3. `orion_custom_lora` - 9 edges
4. `151643` - 7 edges
5. `151644` - 7 edges
6. `151645` - 7 edges
7. `151646` - 7 edges
8. `151647` - 7 edges
9. `151648` - 7 edges
10. `151649` - 7 edges

## Surprising Connections (you probably didn't know these)
- `Checkpoint 12` --references--> `TRL`  [EXTRACTED]
  models/orion_custom_lora/checkpoint-12/README.md → models/orion_custom_lora/README.md
- `Checkpoint 12` --references--> `SFT`  [EXTRACTED]
  models/orion_custom_lora/checkpoint-12/README.md → models/orion_custom_lora/README.md
- `Checkpoint 12` --references--> `Qwen/Qwen2.5-0.5B`  [EXTRACTED]
  models/orion_custom_lora/checkpoint-12/README.md → models/orion_custom_lora/README.md
- `Checkpoint 3` --references--> `Qwen/Qwen2.5-0.5B`  [EXTRACTED]
  models/orion_custom_lora/checkpoint-3/README.md → models/orion_custom_lora/README.md
- `Checkpoint 12` --references--> `LoRA`  [EXTRACTED]
  models/orion_custom_lora/checkpoint-12/README.md → models/orion_custom_lora/README.md

## Communities (44 total, 0 thin omitted)

### Community 0 - "LoRA Adapter Configuration"
Cohesion: 0.05
Nodes (40): alora_invocation_tokens, alpha_pattern, arrow_config, auto_mapping, base_model_name_or_path, bias, corda_config, ensure_weight_tying (+32 more)

### Community 1 - "Base Adapter Metadata"
Cohesion: 0.05
Nodes (40): alora_invocation_tokens, alpha_pattern, arrow_config, auto_mapping, base_model_name_or_path, bias, corda_config, ensure_weight_tying (+32 more)

### Community 2 - "Checkpoint Adapter Metadata"
Cohesion: 0.05
Nodes (40): alora_invocation_tokens, alpha_pattern, arrow_config, auto_mapping, base_model_name_or_path, bias, corda_config, ensure_weight_tying (+32 more)

### Community 3 - "Tokenizer Vocabulary"
Cohesion: 0.06
Nodes (36): content, lstrip, normalized, rstrip, single_word, special, content, lstrip (+28 more)

### Community 4 - "Tokenizer Vocabulary"
Cohesion: 0.06
Nodes (36): content, lstrip, normalized, rstrip, single_word, special, content, lstrip (+28 more)

### Community 5 - "Checkpoint 12 Trainer State"
Cohesion: 0.07
Nodes (28): should_epoch_stop, should_evaluate, should_log, should_save, should_training_stop, best_global_step, best_metric, best_model_checkpoint (+20 more)

### Community 6 - "Checkpoint 3 Trainer State"
Cohesion: 0.07
Nodes (28): should_epoch_stop, should_evaluate, should_log, should_save, should_training_stop, best_global_step, best_metric, best_model_checkpoint (+20 more)

### Community 7 - "Tokenizer Configuration"
Cohesion: 0.14
Nodes (13): add_bos_token, add_prefix_space, additional_special_tokens, bos_token, clean_up_tokenization_spaces, eos_token, errors, extra_special_tokens (+5 more)

### Community 8 - "Base Tokenizer Configuration"
Cohesion: 0.14
Nodes (13): add_bos_token, add_prefix_space, additional_special_tokens, bos_token, clean_up_tokenization_spaces, eos_token, errors, extra_special_tokens (+5 more)

### Community 9 - "Model Card Evidence"
Cohesion: 0.29
Nodes (12): Checkpoint 12, Checkpoint 3, Datasets, LoRA, orion_custom_lora, PEFT, PyTorch, Qwen/Qwen2.5-0.5B (+4 more)

### Community 10 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151649

### Community 11 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151655

### Community 12 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151643

### Community 13 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151644

### Community 14 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151645

### Community 15 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151648

### Community 16 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151651

### Community 17 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151652

### Community 18 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151653

### Community 19 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151656

### Community 20 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151658

### Community 21 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151659

### Community 22 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151660

### Community 23 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151661

### Community 24 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151662

### Community 25 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151663

### Community 26 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151664

### Community 27 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151647

### Community 28 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151648

### Community 29 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151656

### Community 30 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151662

### Community 31 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151644

### Community 32 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151645

### Community 33 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151646

### Community 34 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151649

### Community 35 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151650

### Community 36 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151653

### Community 37 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151654

### Community 38 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151655

### Community 39 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151657

### Community 40 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151659

### Community 41 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151660

### Community 42 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151661

### Community 43 - "Tokenizer Vocabulary"
Cohesion: 0.29
Nodes (7): content, lstrip, normalized, rstrip, single_word, special, 151663

## Knowledge Gaps
- **463 isolated node(s):** `alora_invocation_tokens`, `alpha_pattern`, `arrow_config`, `auto_mapping`, `base_model_name_or_path` (+458 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `added_tokens_decoder` connect `Tokenizer Vocabulary` to `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Base Tokenizer Configuration`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `added_tokens_decoder` connect `Tokenizer Vocabulary` to `Tokenizer Configuration`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`, `Tokenizer Vocabulary`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **What connects `alora_invocation_tokens`, `alpha_pattern`, `arrow_config` to the rest of the system?**
  _463 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `LoRA Adapter Configuration` be split into smaller, more focused modules?**
  _Cohesion score 0.04878048780487805 - nodes in this community are weakly interconnected._
- **Should `Base Adapter Metadata` be split into smaller, more focused modules?**
  _Cohesion score 0.04878048780487805 - nodes in this community are weakly interconnected._
- **Should `Checkpoint Adapter Metadata` be split into smaller, more focused modules?**
  _Cohesion score 0.04878048780487805 - nodes in this community are weakly interconnected._
- **Should `Tokenizer Vocabulary` be split into smaller, more focused modules?**
  _Cohesion score 0.05555555555555555 - nodes in this community are weakly interconnected._