# Third-Party Components

## higgsfield

- Repository: https://github.com/higgsfield-ai/higgsfield
- License: Apache-2.0 (see `third_party/higgsfield/LICENSE`, `third_party/higgsfield/NOTICES.md`)
- Vendor: supplied by upstream at commit `d12a36e66024a93d33ec61826a77d5a346c16869` (cloned 2026-09-19)
- Vendored into `third_party/higgsfield/` as a pristine reference snapshot.
- Purpose: the ORION Runner training-experiment framework (`orion_runner/`) is a
  custom reimplementation and adaptation of selected higgsfield design ideas
  (`@experiment`/`@param` decorators, AST-based experiment discovery, organic
  data-loader packing, run/deploy lifecycle). Adapted source files carry a
  NOTICE header attributing higgsfield under the Apache-2.0 license.
- Not used as-is: SSH orchestration, GitHub-Actions/Docker deploy workflows,
  remote node launch, FSDP/ZeRO-3 sharding, model classes (`higgsfield/llama`,
  `higgsfield/mistral`), and the `higgsfield/rl` notebooks were omitted or
  reworked to fit the ORION single-node training/export/deploy stack.