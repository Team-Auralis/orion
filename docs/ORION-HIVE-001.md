# ORION-HIVE-001 — Distributed-training prototype benchmark (simulated heterogeneous fleet)

_Generated 2026-09-24T07:34:20Z from `logs/training_runs.jsonl` (+ `logs/comp002_eval_raw.jsonl` for the appendix) by `scripts/report/hive001_report.py`. Regenerable; re-running overwrites this file and appends NO ledger row._

_Disk (report time): 4.64 GB free on the repo drive._ _Ledger evidence: 10 COMPLETED hive rows (100 ledger rows total)._

> **Honesty box:** the MEASUREMENTS below (tok/s, comm overhead, val_loss, failure rate) are **VERIFIED** — reproduced from the ledger by this script and recorded by the harness. The SPEEDUP claim is **UNPROVEN / no-linear-speedup measured here**: at a fixed token budget on this one CPU box, growing the simulated fleet from 1 to 4 devices raised worker-loop tok/s by only +2%/+8% while wall time *increased*. Generalization improvement from distribution is **UNPROVEN at tiny scale**.

## 1. Question

The user's verbatim research question is **not recorded anywhere in-repo** (ledger gap L-03 below); the question reconstructed from the T8 experiment design that this benchmark answers is:

> *Can a small fleet of heterogeneous devices — simulated as one coordinator plus worker processes on a single CPU box, with primary / eval / lightweight role envelopes — jointly train one shared model via token-weighted FedAvg-style aggregation, and does growing the fleet from 1 to 4 devices speed up training at a fixed token budget (or change the final model's val_loss) compared with a single worker?*

## 2. Design summary

- A **heterogeneous envelope fleet** (`hive/`) — each device declares a role (primary_trainer / eval / lightweight) and a CPU-thread budget (3 / 1 / 1); the coordinator capability-probes every worker at registration and dispatches disjoint token shards **proportional to its probed tok/s**.
- The fleet is **simulated on one box** via `multiprocessing` pipes – no real network, no real phones — and trains via **token-weighted FedAvg** with an optional server optimizer (momentum=0.0 in every recorded run = exact token-weighted FedAvg).
- Verified mechanics end-to-end (registration, probe, sync, train, aggregate, checkpoint with resume round-trip, dropout + rejoin), then ran an **equal-token comparison** at 1 / 2 / 4 devices and a 4-device dropout variant.

## 3. Mechanics proof table (each step tied to ledger evidence)

| mechanic | ledger evidence row id | proof / note |
|---|---|---|
| registration | `hive-4w-tiny-8d8d5e2d` | `topology.n_workers=4`, `roles=[primary_trainer, primary_trainer, eval, lightweight]`; every worker registers with its envelope before any round (`[FLEET] registered N devices`). |
| capability probe | `hive-4w-tiny-8d8d5e2d` | role dispatch: each device re-probes its own tok/s at boot and the coordinator uses it for shard shares (`_shares`). Per-device probed tok/s is **not recorded** in the ledger — gap L-01. |
| sync (weight dispatch + return) | `hive-1w-tiny-a8d9578f` | `comm_bytes` 69,365,505 ≈ 6 rounds x full 1.44M-param fp32 state_dict down + delta/weights up; every round starts with a full-model dispatch to each trainer. |
| train | `hive-1w-tiny-a8d9578f` | 349,638 tokens trained in 6 rounds, `ending_loss` 9.0043, `tokens_per_s_loop` 10,809.9. |
| aggregate (token-weighted FedAvg) | `hive-4w-tiny-8d8d5e2d` | 3 trainers produce token-weighted updates merged by `fedavg` (server_momentum=0.0 in params), `val_loss` 9.2231. |
| checkpoint | `hive-1w-tiny-a8d9578f` | `checkpoint_path` `models/hive/hive-1w-tiny-a8d9578f/global-r6.pt`; a checkpoint is saved every round. |
| resume | every hive row (all 10) | `resume_verified=true` in all rows — the in-run round-trip proof (fresh model+solver loads the checkpoint, MSE < 1e-6). A dedicated cross-process `--resume` run id is **not** in the ledger — gap L-02. |
| dropout + rejoin | `hive-4w-tiny-296c53da` | `dropout_every=2`, `failures=3`, `failure_rate=0.1667` (3 of 18 update slots killed), run COMPLETED all 6 rounds, `resume_verified=true` after rejoin. |

## 4. Controlled-work comparison (equal token budget)

Four runs share the identical configured budget — `--tokens 120000 --rounds 6`: one deterministic ~120k-token corpus slice, processed 6 rounds (58,273 usable token positions per round fleet-wide). The three non-dropout runs each trained exactly **349,638 tokens** (ledger `total_tokens_trained`); the dropout run trained **291,226** because 3 of its 18 worker-update slots were killed mid-round.

| config | roles | run_id | rounds | tokens trained | wall s | tok/s (wall) | tok/s (loop) | comm % | comm MB | val_loss | failure rate | speedup (loop vs 1w) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1w | P | `hive-1w-tiny-a8d9578f` | 6 | 349,638 | 41.5 | 8433.7 | 10809.9 | 14.2 | 69.4 MB | 9.0734 | 0.0 | 1.00 (baseline) |
| 2w | P+P | `hive-2w-tiny-1205c281` | 6 | 349,638 | 51.8 | 6744.8 | 11059.6 | 15.8 | 138.7 MB | 9.1958 | 0.0 | 1.02x |
| 4w | P+P+E+L | `hive-4w-tiny-8d8d5e2d` | 6 | 349,638 | 70.9 | 4930.4 | 11631.7 | 16.0 | 242.8 MB | 9.2231 | 0.0 | 1.08x |
| 4w+dropout | P+P+E+L | `hive-4w-tiny-296c53da` | 6 | 291,226 | 95.5 | 3049.3 | 9930.6 | 18.8 | 104.0 MB | 9.2222 | 0.1667 | 0.92x |

Speedup ratios computed by this script from the ledger. **Worker-loop tok/s grows slightly with fleet size** (2w +2%, 4w +8% vs 1w) because each worker's per-round share shrinks. **Wall-clock tok/s falls with fleet size** (1w=1.00x, 2w=0.80x, 4w=0.58x): the coordinator's fleet spawn, aggregation, eval and checkpointing are serial and every device contends for the same 6 cores.

**NO linear speedup observed on this box.** Working hypothesis: thread contention + serialization + aggregation offset the per-worker gains; and at equal tokens, more SGD noise (val_loss 9.0734 -> 9.1958 -> 9.2231 across 1w/2w/4w) hurts generalization. The dropout variant's val_loss 9.2222 was measured at 291,226 tokens (16.7% fewer), not at the 349,638-token budget.

## 5. Overhead analysis

- **Comm bytes (measured, ledger `comm_bytes`)**: 1w 69.4 MB, 2w 138.7 MB, 4w 242.8 MB, 4w+dropout 104.0 MB. Bytes scale ~linearly with (#trainers x rounds x 2 weight transfers) for the 1.44M-param (5.8 MB fp32) tiny model; the eval device adds a one-way weight push per round.
- **Comm overhead % (measured, ledger `comm_overhead_pct`)**: 14.2 / 15.8 / 16.0 / 18.8. This is the share of round-loop wall NOT spent in worker compute — transport, serialization, aggregation, eval, and idle waiting. Even 1 worker shows 14.2% because aggregation + eval + weight pickling run inside the round loop.
- **Serialization (qualitative, from the code path)**: full fp32 state_dict pickled per trainer per round; FedAvg and eval happen in-loop; the coordinator is a single-threaded bottleneck wherever workers must wait on it.
- **Real LAN / Wi-Fi (ESTIMATE, not measured — this run uses in-box pipes)**: a real network would add per-message round-trip latency (Wi-Fi roughly 1–5 ms, LAN sub-ms) and bandwidth limits instead of shared memory. Per round with 5.8 MB x #trainers of weights, Wi-Fi would add on the order of tens of ms per round at this model size — negligible here, but it grows with rounds x model size and dominates at 100M+ scales. Battery/sleep behavior of real phones is outside this box.

## 6. Classification

| claim | class | one-line reason |
|---|---|---|
| hive mechanics (register / probe / sync / train / aggregate / checkpoint / resume / dropout+rejoin) | **VERIFIED** | 10 COMPLETED ledger rows; dropout row records failures=3 and completes after rejoin; resume round-trip verified on all rows (cross-process `--resume` not ledger-recorded — gap L-02). |
| measured throughput at fixed budget | **VERIFIED** | reproducible CLI runs (§9); wall and loop tok/s recorded per row; comm % and val_loss recorded. |
| scaling speedup claim | **UNPROVEN / no-linear-speedup measured here** | loop tok/s +2% (2w) / +8% (4w) at equal tokens; wall tok/s decreases 1.00x -> 0.80x -> 0.58x; nothing near linear. |
| generalization improvement from distribution | **UNPROVEN at tiny scale** | single worker generalizes best at equal tokens (val_loss 9.0734 vs 9.1958 / 9.2231); 349,638 tokens is a trivial budget and each config ran once. |

## 7. Limitations

- **Simulated fleet**: processes on one 6-core / 12-thread CPU box, not real devices; no real network, no Wi-Fi, no battery or phone runtime.
- **Contention**: all roles share the same cores and memory bandwidth; 4w + eval + lightweight oversubscribes the box.
- **Tiny / 10M scale**: comparisons use the 1.44M-param tiny model; the single 10m row (13.6M params, 1 round x 15k tokens) is a mechanics check, not a throughput comparison.
- **Equal-token budget is small**: 349,638 tokens (~0.5% of the 63.8M-token corpus); loss differences of ~0.1 at this budget are not significant.
- **Single round count, no repetition**: 6 rounds only; every config ran once (no seeds swept, no repeated trials), so the val_loss ordering is anecdotal.
- **Dropout run not budget-matched**: it trained 291,226 tokens (3 killed updates), so its val_loss is not directly comparable with the 349,638-token rows.

## 8. Next highest-information experiment

Real 2-laptop LAN run at 10M+ model scale to see whether true distributed (non-contended) compute beats this box's contention; alternative: heterogeneity-as-service run with role-stratified data to test whether capability-proportional dispatch changes the loss trajectory.

## 9. Reproduce commands (exact lines, built from the ledger's recorded params)

Equal-budget comparisons (349,638-token slice):

```text
python -m hive.run --model tiny --workers 1 --rounds 6 --tokens 120000 --scope measured-simulation
python -m hive.run --model tiny --workers 2 --rounds 6 --tokens 120000 --scope measured-simulation
python -m hive.run --model tiny --workers 4 --rounds 6 --tokens 120000 --scope measured-simulation
python -m hive.run --model tiny --workers 4 --rounds 6 --tokens 120000 --dropout-every 2 --scope verified-mechanics
```

Mechanics verification runs (the other unique configs in the ledger):

```text
python -m hive.run --model tiny --workers 2 --rounds 3 --tokens 60000 --dropout-every 2 --scope verified-mechanics
python -m hive.run --model tiny --workers 2 --rounds 2 --tokens 20000 --scope verified-mechanics
python -m hive.run --model tiny --workers 2 --rounds 1 --tokens 60000 --scope verified-mechanics
python -m hive.run --model tiny --workers 2 --rounds 3 --tokens 60000 --scope verified-mechanics
python -m hive.run --model 10m --workers 2 --rounds 1 --tokens 15000 --scope verified-mechanics
```

Params omitted from the lines are the CLI defaults and match every recorded run: seed 42, batch 4, worker-lr 0.005, server-momentum 0.0. The budget is fixed by `--tokens 120000 --rounds 6`: one ~120k-token corpus slice, 349,638 trainable token positions. Then regenerate this report with `python scripts/report/hive001_report.py`.

## 10. Appendix — model / COMP context (from the ledger, for scale)

- **COMP-001 100m-real** (`comp-001-custom-100m-real-0d9808ff`): 110,918,656 params (110.9M), status **PARTIAL_FIRST_PASS**, in-training val ppl 2802.1 (ledger) / T5 held-out ppl 2,652.40; HellaSwag N=100 acc 0.2100 (21/100) vs random 0.2500.
- **BitNet b1.58-2B-4T reference** (`bitnet-ref-31284d32`): status **VERIFIED**, 13.4 tok/s (ledger `tok_per_s`), peak RSS 1238 MB, file 1132.8 MB, i2_s via bitnet.cpp llama-cli (official).
- Why it matters here: the hive comparison runs at tiny/10m scale; 100M-scale federated training is out of budget on this box. The appendix anchors those tiny numbers against the measured single-device reference arms (documents of record: `docs/ORION-COMP-001.md`, `docs/ORION-COMP-002.md`).

## 11. Ledger gaps found (things the report needed but the ledger did not record)

- **L-01** — per-device capability-probe values (each worker's measured tok/s at registration) are not recorded; the ledger only has roles + fleet-level throughput.
- **L-02** — no dedicated cross-process `--resume` ledger row; `resume_verified` on all rows is the in-run checkpoint round-trip proof, and `hive.run` does not record a `resume` param.
- **L-03** — the user's verbatim research question is not stored in-repo; §1 quotes the reconstruction from the T8 experiment design.

(No other required field was missing: topology, model, loop/wall tok/s, comm %, val_loss, failure rate, tokens, rounds, resume_verified, walls and disk free are all present on all 10 hive rows.)
