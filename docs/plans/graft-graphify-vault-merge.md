# Plan: Merge graft + graphify into the Obsidian vault

**Status:** Planned 2026-09-26 22:5x IST (user: build tomorrow, not tonight)
**Owner:** OpenCoder cycle
**Estimate:** ~2–3 h (any block ≥3 h works)
**Goal:** Make `vault/` the single browsable knowledge home — repo graph (graft) and
community graph (graphify) as Obsidian notes with backlinks, auto-refreshed by the
existing `scripts/vault/build_vault.py` + pre-commit hook (no new enforcement work).

## Ground truth (verified 2026-09-26)

| Source | State | Native shape |
|---|---|---|
| `graft/` | 319 per-file markdown cards; **edges only in `.graph` DB** (CLI/MCP), not in files | markdown + queryable graph |
| `graphify-out/` | **Stale 2026-09-09**, scope = `models/orion_custom_lora` only; 531 nodes / 531 edges / 44 communities; report warns 2.4M-word corpora are expensive | `graph.html`, `graph.json`, `GRAPH_REPORT.md` — already emits `[[_COMMUNITY_...]]` wikilinks |
| `vault/` | Home / Knowledge Graph / glossary + builder-owned notes (marker-guarded) | Obsidian wikilinks |

## Design decisions

1. **Do NOT dump 319 graft cards as 319 vault notes** (graph noise). Instead emit
   one compact note per top-level scope dir (list of files/nodes + links to the
   real `graft/<file>.md` cards) + a repo-graph overview note.
2. **Edges stay in graft's DB** — Obsidian can't render call graphs, so each scope
   note documents the query path (`graft callers <symbol>`) instead of trying to
   mirror edges.
3. **Re-run graphify on a bounded, current scope**, not the whole repo: recommend
   `models/comp001`, `orion_runner`, `scripts/training`, `scripts/teacher` (live
   ML/training area). A stale graph labeled honest is acceptable fallback if the
   run is too costly.
4. **New notes are builder-owned** (edit `build_vault.py`, never the generated
   content) with the same backlink skeleton (`[[ORION]]`, `[[ORION Capabilities]]`,
   `[[00 - Home]]`, `[[00 - Knowledge Graph]]`).

## Tasks (ordered, tomorrow)

1. **`scripts/vault/export_graft.py`** — read `graft/` tree, emit scope notes +
   overwrite/extend the repo-graph overview note. Wire into `build_vault.py`.
   *Done when:* idempotent double-run → no diff; scope notes link to real cards.
2. **Refresh graphify** on bounded scope (`docs/graphify.md` or README claims
   replicated). Land output in `graphify-out/`. *Done when:* new
   `GRAPH_REPORT.md` has current date + bounded scope; honest label if skipped.
3. **New vault notes with backlinks:**
   - `02 - Architecture/Repo Graph (graft).md` — nodes by scope, query path, link to `graft/INDEX.md`
   - `11 - Experiments/Knowledge Graph (graphify).md` — node/community summary,
     `[[_COMMUNITY_...]]` hub links, link to `graph.html`; label scope + date
   *Done when:* Obsidian graph view shows both, backlinked both ways.
4. **Extend Knowledge Graph auto-block** — add edges: `ORION` → `Repo Graph (graft)`;
   `Repo Graph` → `Knowledge Graph (graphify)`; refresh glossary if needed.
   *Done when:* `build_vault.py` re-run idempotent; `00 - Knowledge Graph.md`
   shows merged edges.
5. **Commit + push** — hook auto-syncs vault. *Done when:* clean tree,
   `origin/main` updated.

## Out of scope (v2, optional)

- Per-symbol backlinks from source-referencing notes via graft spans.
- Bidirectional Obsidian↔graft sync (graft build on vault edits).

## Honest labels

- ETA is an estimate, not a promise; graphify re-run cost depends on corpus size.
- If graphify re-run exceeds block time, ship the stale graph **labeled as such**
  (+ pointer) — never silently.