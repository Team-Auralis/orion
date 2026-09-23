# ORION — Economic Agent Backend

ORION is an autonomous agent that **earns, spends and accounts for money** —
responsibly. It discovers opportunities, scores them against a pure-numeric
risk model, routes risky actions through an approval queue, and books every
move into an append-only integer-paise ledger with hard guardrails.

> **Default mode is `dry_run`**: ORION watches and plans but never moves real
> money. All spend endpoints return `SIMULATED` and every approval
> auto-resolves with `decision: dry_run_auto_approve`. See
> [Autonomy modes](#autonomy-modes).

---

## Quick start

```bash
# 1. Install (Python 3.11+)
pip install -e .

# 2. Verify the environment
python -m orion.cli doctor

# 3. Run the full offline mock loop (discovers + scores + proposes a spend)
python -m orion.cli dry-run

# 4. Run the HTTP API + dashboard
python -m orion.main            # API on http://127.0.0.1:8765

# 5. In another terminal — the dashboard (Vite dev server, proxy → :8765)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

No LLM, no browser, no network required: the default connector (`mock`) and
default browser driver (`mock`) are deterministic offline fixtures. ORION runs
fine with Ollama absent — the model status just reads `DEGRADED`.

### Windows PowerShell equivalents

```powershell
pip install -e .
python -m orion.cli doctor
python -m orion.cli dry-run
python -m orion.main            # API on http://127.0.0.1:8765
Set-Location frontend; npm install; npm run dev
```

---

## What ORION is

- **Economic engine** — opportunity discovery → numeric scoring → policy
  gating → approval → ledger-verified execution. Observability the whole way.
- **Money can't lie** — every cent is an integer-paise `LedgerEntry`; the
  balance is *replayed* from the log on every read, and
  `ledger.assert_invariant()` fails the moment the log doesn't balance.
- **Verified-revenue rule** — revenue only counts (and only frees cash) when
  a verification method **and** confidence ≥ 0.9 arrive
  (`payout-confirmed`, 0.95, …). Unverified income stays `ESTIMATED` /
  `PENDING` and is never spendable.
- **Safety-first by construction** — kill switch → risk matrix → budget
  guardrails → approval queue. Approvals can *permit*; they can never
  override a hard BLOCKED.

## Architecture

```
config/*.yaml            risk matrix, guardrails, scoring weights, connectors,
                         scheduler cadence, API binding, CORS origins
orion/
  config.py              typed config (env overrides: ORION_DATA_DIR,
                         ORION_AUTONOMY_MODE; force-reloadable for tests)
  db.py                  SQLAlchemy engine + schema bootstrap (idempotent)
  models.py              ORM rows: LedgerEntry, Opportunity, Strategy,
                         StrategyRun, ApprovalRequest, Experiment, Job, Memory
  ledger.py              append-only integer-paise ledger; replay + invariant
  discovery.py           connectors → DISCOVERED opportunity rows (dedupe)
  scoring.py             numeric 0..100 scoring, suspicious-offer detection
  safety.py              risk matrix + budget engine + approval queue
  security.py            kill switch (DB-backed), approval boundary merging
  policy.py              BudgetPolicy — single/daily/total-loss guardrails
  strategy.py            strategy lifecycle + evidence ranking
  experiments.py         experiment tracking
  jobs.py                persistent job queue (QUEUED→RUNNING→SUCCESS/FAILED)
  memory.py, events.py   memory store + activity event log
  browser.py             mock/playwright driver (default: mock)
  router.py              LLM router (Ollama optional, DEGRADED without it)
  api.py                 FastAPI HTTP API (all dashboard endpoints)
  main.py                uvicorn entrypoint
  cli.py                 `python -m orion.cli` commands
tests/                   204 tests, all offline (fresh SQLite per test)
frontend/                React + TypeScript + Tailwind dark dashboard
data/                    runtime: orion.db + logs (gitignored)
```

### Data flow

```
connector scan ──► DISCOVERED ──► score ──► SCORED ──► approve ──► PENDING
                                                          │ (human / dry-run)
SUSPICIOUS ──► REJECTED (never PENDING)                    ▼
                                   executed ⇒ ledger.spend() / record_revenue()
                                             │               │
                                             ▼               ▼
                                   guardrails + kill switch   verified-revenue check
                                             │               │
                                             └──► append-only LedgerEntry log
```

---

## Testing

```bash
# Everything (204 tests, ~0s–35s, no network, no Ollama)
python -m pytest tests -q

# Just the offline end-to-end lifecycle (seed → discover → score → strategy
# → approval → spend → verified revenue → kill switch → restart persistence)
python -m pytest tests/test_e2e_mock.py -q

# Anything, with temp data dirs guaranteed
```

Every test uses its own SQLite DB in a pytest `tmp_path` via
`ORION_DATA_DIR` → `_reset_engine()` → `init_db()` — the real `data/` DB is
never touched.

---

## Command line

`python -m orion.cli <command>`

| Command | What it does |
|---|---|
| `start` | boot the job worker + scheduler loop, run until Ctrl+C/`stop` |
| `stop` | signal a running `orion start` to exit |
| `status` | mode, model health, kill switch, DB health, capital |
| `doctor` | environment diagnostics (PASS/WARN/FAIL) |
| `dry-run` | run the whole mock loop and print a summary |
| `opportunities [--limit N]` | list discovered opportunities |
| `strategies` | list strategies with evidence summary |
| `experiments` | list experiments |
| `ledger` | balance summary + recent ledger entries |
| `approve <id>` / `reject <id>` | decide a pending approval request |
| `confirm-payout --amount 300.00 --source <platform> --evidence <ref>` | record a human-confirmed VERIFIED payout from evidence |
| `kill` | engage the global kill switch (blocks ALL financial endpoints) |
| `logs [--lines N]` | tail `data/logs/orion.log` |

Exit codes: `0` success, `1` user error, `2` runtime error.

---

## HTTP API (127.0.0.1:8765)

All money moves through the same integer-paise types; every money field has a
parallel `*_formatted` ₹ string — display those, never re-derive client-side.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | mode, kill switch, model health, db health, uptime, autonomy map |
| GET | `/api/health` | per-check health map |
| GET/POST | `/api/ledger` | balance summary + entries (PATCH-less; POST spends below) |
| POST | `/api/ledger/spend` | record an expense → policy + approval → SIMULATED in dry_run |
| POST | `/api/ledger/revenue` | record revenue with verification method + confidence |
| POST | `/api/ledger/confirm-payout` | record a human-confirmed VERIFIED payout from `evidence_ref` (sanctioned income path) |
| GET/POST | `/api/opportunities` | list (filter `?status=&limit=`) / manually submit for decision |
| POST | `/api/opportunities/scan` | run connectors → `{created, scored, total}` |
| GET/POST | `/api/strategies` | list with performance / propose |
| GET/POST | `/api/experiments` | list / start an experiment |
| GET | `/api/approvals?status=pending` | approval queue |
| POST | `/api/approvals/{id}/approve` · `/reject` | decide an approval |
| GET/POST | `/api/jobs` | job queue |
| POST | `/api/kill` · `/api/kill/lift` | global kill switch |
| GET | `/api/memory` | memory store |
| GET | `/api/activity` | SSE live event stream |
| GET | `/api/activity/recent` | recent events (poll fallback) |

CORS is open to `http://localhost:5173` and `http://127.0.0.1:5173` (the Vite
dev server). The Vite proxy forwards `/api/*` to `localhost:8765` — override
with `ORION_API_TARGET` if your API lives elsewhere.

---

## Autonomy modes

| Mode | Behavior |
|---|---|
| `dry_run` | observe + plan only. Spends are SIMULATED, approvals auto-approve with `dry_run_auto_approve`, no real side effects |
| `manual` | all risky actions wait in the approval queue for a human |
| `assisted` | agent can act but stops for approvals on L2+; **approvals are real** — spend only after human approve, income verified via `confirm-payout` evidence (see [Going live](#going-live-assisted-mode)) |
| `autonomous` | agent executes within policy guardrails without human steps |

Set via `ORION_AUTONOMY_MODE` (env) or `config/default.yaml` →
`autonomy.default_mode`.

---

## Going live (assisted mode)

`dry_run` stays the default until you opt in — nothing changes unless you set
`ORION_AUTONOMY_MODE=assisted`:

```bash
export ORION_AUTONOMY_MODE=assisted   # PowerShell: $env:ORION_AUTONOMY_MODE="assisted"
python -m orion.cli status            # mode: assisted
```

What changes: approvals stop auto-approving. A spend now creates a **PENDING**
approval and moves no money until a human approves. The real loop is:

1. Spend is proposed → an approval request sits PENDING.
2. You execute the real-world purchase (ORION never does this for you).
3. `orion approve <id>` — the ledger SPEND is written now, and exactly once:
   an approval is consumed by its first spend (a second approve is refused).
4. When the platform pays out, record the real income with evidence:
   `orion confirm-payout --amount 300.00 --source upwork --evidence <payout-id>`
   (or `POST /api/ledger/confirm-payout`). Revenue only becomes VERIFIED
   (spendable) when a non-empty `evidence_ref` — CSV path, transaction id,
   payout record id — is supplied. No evidence, no verified revenue.

### Gumroad (Milestone B)

Platform policy for Gumroad is recorded in `config/platforms.yaml`
(`research_policy: api_only`, official REST API v2 only) and the credential
vault CLI is ready:

```bash
python -m orion.cli vault health                    # backend + writable check
python -m orion.cli vault set gumroad_token         # then paste the token (hidden stdin)
python -m orion.cli vault list                      # names only (masked values)
python -m orion.cli vault get gumroad_token         # mask only — never the raw token
python -m orion.cli vault delete gumroad_token
```

- **Get a token**: Gumroad dashboard → Settings → Advanced → API (generate a
  personal access token with the `edit_products` / `view_sales` / `account`
  scopes). Store it as `gumroad_token` with the `vault set` command above,
  pasting the value on stdin so it never lands in shell history.
- **Never scrape gumroad.com** — their ToS clause 14(e) bans automated
  crawling, so the browser allowlist excludes it and all Gumroad data comes
  from the official API only.
- **Publishing requires a connected payment method on the account** — this is
  the "real money" moment: payout **receiving**, never a deposit. Gumroad
  lists prices in USD; ORION ledgers stay in INR via `confirm-payout` FX at
  receiving time.

---

## Financial safety model

1. **Kill switch** — engage instantly (`POST /api/kill` or `orion.cli kill`);
   every financial endpoint returns `403 blocked_by_policy` with reason
   `"kill switch active"` until lifted. Persisted in the DB.
2. **Risk matrix** (`config/policies.yaml`) — action class → risk level
   (L0…L4) → AUTO/APPROVAL/BLOCKED. `spend` = L2/APPROVAL, `create_account` =
   L4/BLOCKED. Unknown action classes get a conservative L2 default.
3. **Budget guardrails** (`config/default.yaml` →
   `risk_guardrails`): `max_single_spend` (₹20), `max_daily_spend` (₹50),
   `max_total_loss` (₹200), no borrowing/leverage/gambling. `ledger.spend()`
   raises if any would break. Budget denial is a hard BLOCKED — an approval
   can never override it.
4. **Approval queue** — everything L2+ needs an approval record; dry-run
   auto-approves, TTL expiry re-requires approval.
5. **Append-only ledger + invariant** — balances are replayed from the log;
   the invariant is re-checked after every write.

## Configuration

Everything lives in `config/*.yaml` (valid UTF-8 — ₹ renders fine in a UTF-8
terminal):

- `config/default.yaml` — capital, target, guardrails, autonomy mode, paths,
  scheduler, job limits, scoring weights, connectors, API binding. **Only**
  `paths.data_dir` (`ORION_DATA_DIR`) and `autonomy.default_mode`
  (`ORION_AUTONOMY_MODE`) are env-overridable.
- `config/policies.yaml` — risk levels, action→level map, browser driver,
  approval TTL.
- `config/model_roles.yaml` — LLM role prompts (unused without Ollama).

`.env.example` documents the four env variables actually read:
`ORION_DATA_DIR`, `ORION_ENV`, `ORION_FORCE_NO_OLLAMA`,
`ORION_AUTONOMY_MODE`. **The browser backend is not an env var** — set
`browser.driver` in `config/policies.yaml`.

### Ollama (optional)

```bash
ollama pull qwen2.5:7b      # any OpenAI-compatible endpoint works
```

Without a model ORION stays fully functional in `DEGRADED` — scoring is
always pure numeric, never an LLM. Force-disable the model with
`ORION_FORCE_NO_OLLAMA=true`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard shows "cannot reach /api" | Start the API (`python -m orion.main`); check `ORION_API_TARGET` |
| `connection refused` to Ollama | Install / start Ollama, or set `ORION_FORCE_NO_OLLAMA=true` |
| ₹ shows as `???` in the terminal | Windows console codepage; run in a UTF-8 terminal (`chcp 65001`) — the files are valid UTF-8 |
| Scores look off | Tune `config/default.yaml` `scoring:` weights (sum stays 100) |
| Want real data, not fixtures | Enable a real connector (`real_marketplace` is NOT IMPLEMENTED by design — enabling raises loudly) |
| Reset your play data | Delete `data/` (next boot reseeds capital + fresh DB) |

## License / status

Prototype — dry-run by default, mock connectors, no real money movement.