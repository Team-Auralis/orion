#!/usr/bin/env python3
"""Project the graft repo graph into the Obsidian vault.

RULE (see AGENTS.md): generated vault notes are marker-guarded and owned by
`scripts/vault/build_vault.py`. This module is the *content producer* for the
graft-backed notes; `build_vault.py` owns when they get written.

What it reads (repo truth, no network, no API key):
  - `graft/**.md`             one wiring card per indexed source file
  - `graft/INDEX.md`          the index card
  - `graphify-out/graph.json` community graph (may be absent -> notes degrade)

What it emits (returned as strings; build_vault.py writes them):
  - one compact scope note per top-level dir under `graft/`
  - `02 - Architecture/Repo Graph (graft).md`  (repo-graph overview)
  - `11 - Experiments/Knowledge Graph (graphify).md` (community-graph summary)

Design decision (docs/plans/graft-graphify-vault-merge.md #1): do NOT dump 318
cards as 318 vault notes - that is graph noise. One note per top-level scope
lists the cards and links to the real `graft/<file>.md` on disk, which is where
the `file:line` spans actually live.

Design decision (#2): edges live only in graft's `.graph` DB, not in these
files, so every scope note documents the query path (`graft callers <symbol>`)
instead of pretending to mirror edges it cannot see.

    python scripts/vault/export_graft.py          # dry run: print stats only
    python scripts/vault/export_graft.py --stats
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAFT = REPO_ROOT / "graft"
GRAPHIFY_OUT = REPO_ROOT / "graphify-out"

# Backlink skeleton required by AGENTS.md ("Backlinks" bullet).
BACKLINKS = [
    "[[ORION]]",
    "[[ORION Capabilities]]",
    "[[ORION Training Ledger]]",
    "[[ORION Screen-Vision & Actions]]",
    "[[00 - Home]]",
    "[[00 - Knowledge Graph]]",
]

# Scope slug -> (vault folder, human title, one-line what-it-is)
SCOPE_META: dict[str, tuple[str, str, str]] = {
    "scripts": (
        "02 - Architecture",
        "Repo Graph scope - scripts",
        "CLI + experiment drivers: ACI experiments, AURA, training, deploy, chaos.",
    ),
    "orion_money": (
        "02 - Architecture",
        "Repo Graph scope - orion_money",
        "Largest indexed scope; money/finance services and their tests.",
    ),
    "services": (
        "02 - Architecture",
        "Repo Graph scope - services",
        "Per-module service implementations (AEGIS, AI Sentinel, NEXUS, ...).",
    ),
    "tests": (
        "02 - Architecture",
        "Repo Graph scope - tests",
        "Test suite cards - the assertions that hold the services honest.",
    ),
    "new-ui": (
        "02 - Architecture",
        "Repo Graph scope - new-ui",
        "Frontend/UI surface cards.",
    ),
    "modules": (
        "03 - Modules",
        "Repo Graph scope - modules",
        "Module-level logic behind the services (AURA, OMNIS, NEXUS, ...).",
    ),
    "apps": (
        "02 - Architecture",
        "Repo Graph scope - apps",
        "Application entrypoints that wire modules + services together.",
    ),
    "alembic": (
        "06 - Infrastructure",
        "Repo Graph scope - alembic",
        "Database migration revisions.",
    ),
    "orion_runner": (
        "11 - Experiments",
        "Repo Graph scope - orion_runner",
        "The live screen-vision + whitelisted-action runtime (see/do).",
    ),
    "data": (
        "11 - Experiments",
        "Repo Graph scope - data",
        "Data/artifact directory cards.",
    ),
    "experiments": (
        "11 - Experiments",
        "Repo Graph scope - experiments",
        "Experiment drivers and their result wiring.",
    ),
    "papers": (
        "11 - Experiments",
        "Repo Graph scope - papers",
        "Reference papers vendored into the repo.",
    ),
    "forge": (
        "03 - Modules",
        "Repo Graph scope - forge",
        "FORGE scientific-engine cards.",
    ),
}

ROOT_SCOPE = (
    "02 - Architecture",
    "Repo Graph scope - repo root",
    "Loose root-level scratch/patch/fix cards (one-off .md notes, not source).",
)

SYMBOL_RE = re.compile(
    r"^-\s+(?P<name>.+?)\s+·\s+(?P<kind>function|method|class|module|constant)\s+·\s+L(?P<start>\d+)(?:-L(?P<end>\d+))?"
)
REPORT_HEADER_RE = re.compile(
    r"^#\s*Graph Report\s*-\s*(?P<scope>.+?)\s*\((?P<date>\d{4}-\d{2}-\d{2})\)"
)
REPORT_SUMMARY_RE = re.compile(r"^-\s*(?P<body>\d+\s+nodes.*)$")
COMMUNITY_HEAD_RE = re.compile(
    r'^###\s+Community\s+(?P<cid>\d+)\s*-\s*"(?P<label>[^"]+)"'
)


# ---------------------------------------------------------------- graft read


def graft_cards() -> list[dict]:
    """Every per-file card under graft/, excluding INDEX.md and dotfiles."""
    if not GRAFT.is_dir():
        return []
    cards = []
    for path in sorted(GRAFT.rglob("*.md")):
        rel = path.relative_to(GRAFT)
        if rel.name == "INDEX.md" or rel.parts[0].startswith("."):
            continue
        cards.append(
            {
                "rel": rel.as_posix(),
                "scope": rel.parts[0] if len(rel.parts) > 1 else "",
                "name": rel.stem,
                "symbols": 0,
                "span_lines": 0,
            }
        )
    return cards


def read_card_symbols(card: dict) -> dict:
    """Count extracted symbols + covered lines in one card."""
    path = GRAFT / card["rel"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return card
    spans: list[tuple[int, int]] = []
    for line in text.splitlines():
        m = SYMBOL_RE.match(line)
        if not m:
            continue
        card["symbols"] += 1
        start = int(m.group("start"))
        end = int(m.group("end") or start)
        spans.append((start, end))
    if spans:
        card["span_lines"] = sum(e - s + 1 for s, e in spans)
    return card


def group_by_scope(cards: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for card in cards:
        grouped.setdefault(card["scope"], []).append(card)
    return grouped


def top_files(cards: list[dict], n: int = 5) -> list[dict]:
    """Hubs within a scope = cards with the most extracted symbols."""
    return sorted(cards, key=lambda c: (-c["symbols"], c["rel"]))[:n]


# ---------------------------------------------------------------- rendering


def card_link(card: dict) -> str:
    """Markdown link to the real graft card on disk (relative from repo root)."""
    return f"[`{card['rel']}`](graft/{card['rel']})"


def scope_note(scope: str, cards: list[dict], ts: str) -> str:
    folder, title, blurb = (
        SCOPE_META.get(
            scope,
            ("02 - Architecture", f"Repo Graph scope - {scope}", "Indexed cards."),
        )
        if scope
        else ROOT_SCOPE
    )
    rel_base = f"../../{folder}/{title}.md"
    total_sym = sum(c["symbols"] for c in cards)
    total_span = sum(c["span_lines"] for c in cards)

    hub_rows = (
        "\n".join(
            f"| `{c['rel']}` | {c['symbols']} | {c['span_lines']} | {card_link(c)} |"
            for c in top_files(cards)
        )
        or "| _(no symbols extracted)_ | - | - | - |"
    )

    rest = [
        c for c in sorted(cards, key=lambda c: c["rel"]) if c not in top_files(cards)
    ]
    listed = (
        "\n".join(f"- {card_link(c)}" for c in rest)
        or "- _(none - every card above is a hub)_"
    )

    return f"""# {title}

#architecture #graph

> *Auto-generated by `scripts/vault/build_vault.py` via
> `scripts/vault/export_graft.py` - edit the exporter, not this file.*
> *Last sync: {ts}*

{blurb}

**Hubs** (most symbols) · **{len(cards)}** cards · **{total_sym}** symbols · **{total_span}** covered lines

## How the edges work

Cards carry `file:line` spans; **edges are not in these files**. They live in
graft's graph DB, queryable from the repo root:

```bash
graft ask "how does X work" --source     # locate + explain, code inlined
graft skeleton <file>                    # one file's API in ~200 tokens
graft callers <symbol>                   # who calls it (default --direction in)
graft callers <symbol> --direction out   # what it calls
graft callers <symbol> --depth 2         # blast radius before a rename
graft grep "<literal>"                   # exhaustive hits, grouped by symbol
graft map                                # dir clusters, hubs, hotspots
```

Obsidian cannot render a call graph, so this note records the query path rather
than a lossy copy of the edges.

## Hubs

| card | symbols | lines | file |
|---|---|---|---|
{hub_rows}

## All cards in this scope

{listed}

## Backlinks / Related

- [[Repo Graph (graft)]] - the whole repo graph, scope by scope
- [[Knowledge Graph (graphify)]] - the other graph: communities, not calls
{chr(10).join("- " + b for b in BACKLINKS)}
- Overview card: [graft/INDEX.md](graft/INDEX.md)
- {len(cards)} card(s) mirrored from `graft/{scope + "/" if scope else ""}` (link base: {rel_base})
"""


def repo_graph_note(scopes: dict[str, list[dict]], total_cards: int, ts: str) -> str:
    total_sym = sum(c["symbols"] for cards in scopes.values() for c in cards)
    total_span = sum(c["span_lines"] for cards in scopes.values() for c in cards)
    with_sym = sum(1 for cards in scopes.values() for c in cards if c["symbols"])

    rows = []
    for scope in sorted(scopes, key=lambda s: (-len(scopes[s]), s)):
        cards = scopes[scope]
        sym = sum(c["symbols"] for c in cards)
        span = sum(c["span_lines"] for c in cards)
        label = scope or "_(repo root)_"
        if scope:
            folder, title, _ = SCOPE_META.get(
                scope, ("02 - Architecture", f"Repo Graph scope - {scope}", "")
            )
            note_link = f"[[Repo Graph scope - {scope}]]"
            _ = folder, title
        else:
            note_link = "[[Repo Graph scope - repo root]]"
        rows.append(f"| `{label}` | {len(cards)} | {sym} | {span} | {note_link} |")

    top_global = sorted(
        (c for cards in scopes.values() for c in cards),
        key=lambda c: (-c["symbols"], c["rel"]),
    )[:12]

    hub_rows = "\n".join(
        f"| `{c['rel']}` | {c['symbols']} | {c['span_lines']} | {card_link(c)} |"
        for c in top_global
    )

    return f"""# Repo Graph (graft)

#architecture #graph

> *Auto-generated by `scripts/vault/build_vault.py` via
> `scripts/vault/export_graft.py` - edit the exporter, not this file.*
> *Last sync: {ts}*

`graft/` is this repo's context graph: one small markdown card per indexed
source file, each naming the exact `file:line` spans it covers. This note is the
**browsable index** into it - one note per top-level scope, not 300+ loose
notes (see `docs/plans/graft-graphify-vault-merge.md`, decision #1).

**{total_cards}** cards · **{len(scopes)}** scopes · **{total_sym}** symbols ·
**{total_span}** covered lines · **{with_sym}** cards carry extracted symbols.

## Nodes by scope

| scope | cards | symbols | lines | note |
|---|---|---|---|---|
{chr(10).join(rows)}

## Top hubs repo-wide

| card | symbols | lines | file |
|---|---|---|---|
{hub_rows}

## How to query the edges

Edges (who calls what) exist **only** in graft's graph DB - not in the markdown
cards, so this vault deliberately does not mirror them. From the repo root:

```bash
graft map                                   # orientation: clusters, hubs, hotspots
graft ask "<question>" --source             # ranked nodes + code inlined
graft skeleton <file>                       # a file's API, ~200 tokens
graft callers <symbol> --depth 2            # blast radius before a rename
graft grep "<literal>"                      # exhaustive, grouped by enclosing symbol
graft build                                 # refresh after big code changes ($0, no API key)
```

AGENTS.md injects the same six commands into every agent's context; the
[index card](graft/INDEX.md) says the same in prose.

## Related graphs

- [[Knowledge Graph (graphify)]] - community graph over `scripts/training`,
  built from the same repo but a different question: "what clusters together?"
  instead of "who calls whom?"
- [[ORION Screen-Vision & Actions]] - what the `orion_runner` scope implements

## Backlinks / Related

{chr(10).join("- " + b for b in BACKLINKS)}
- Source: `graft/` ({total_cards} cards) · index: [graft/INDEX.md](graft/INDEX.md)
"""


# ---------------------------------------------------------------- graphify


def report_age_days(date_str: str) -> int | None:
    """Days between the graphify report's own date and now (None if unparseable).

    Driven off the report header, never a hardcoded threshold, so the freshness
    label keeps telling the truth as the repo ages.
    """
    try:
        stamp = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0, (datetime.now(timezone.utc).date() - stamp.date()).days)


def graphify_state() -> dict:
    """Read graphify-out/ defensively. Absent files degrade, never crash."""
    state: dict = {
        "present": False,
        "scope": "(unknown)",
        "date": "(unknown)",
        "nodes": 0,
        "edges": 0,
        "communities": 0,
        "labels": {},
        "community_sizes": {},
        "files": 0,
        "words": 0,
        "god_nodes": [],
        "surprises": [],
        "isolated": None,
        "corpus_warning": "",
        "extraction_line": "",
        "token_line": "",
    }
    report = GRAPHIFY_OUT / "GRAPH_REPORT.md"
    if not report.exists():
        return state

    text = report.read_text(encoding="utf-8", errors="replace")
    state["present"] = True

    head = REPORT_HEADER_RE.search(text)
    if head:
        state["scope"] = head.group("scope").strip()
        state["date"] = head.group("date")

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("- Large corpus") or line.startswith("- Corpus is"):
            state["corpus_warning"] = line.lstrip("- ").strip()
        m = REPORT_SUMMARY_RE.match(line)
        if m:
            body = m.group("body")
            nums = re.match(
                r"(\d+)\s+nodes\s*·\s*(\d+)\s+edges\s*·\s*(\d+)\s+communities", body
            )
            if nums:
                state["nodes"] = int(nums.group(1))
                state["edges"] = int(nums.group(2))
                state["communities"] = int(nums.group(3))
        if "isolated node(s)" in line:
            m2 = re.search(r"(\d+)\s+isolated node", line)
            if m2:
                state["isolated"] = int(m2.group(1))

    # "Extraction:" and "Token cost:" are separate bullets inside ## Summary.
    try:
        si = next(i for i, ln in enumerate(lines) if ln.startswith("## Summary"))
    except StopIteration:
        si = -1
    if si >= 0:
        for line in lines[si + 1 :]:
            if line.startswith("## "):
                break
            s = line.strip()
            if s.startswith("- Extraction:"):
                state["extraction_line"] = s.lstrip("- ").strip()
            elif s.startswith("- Token cost:"):
                state["token_line"] = s.lstrip("- ").strip()

    # God nodes section
    try:
        gi = next(i for i, ln in enumerate(lines) if ln.startswith("## God Nodes"))
    except StopIteration:
        gi = -1
    if gi >= 0:
        for line in lines[gi + 1 :]:
            m = re.match(
                r"^\d+\.\s+`(?P<label>[^`]+)`\s*-\s*(?P<deg>\d+)\s+edges", line
            )
            if m:
                state["god_nodes"].append((m.group("label"), int(m.group("deg"))))
            elif line.startswith("## "):
                break

    # Surprising connections
    try:
        si = next(
            i
            for i, ln in enumerate(lines)
            if ln.startswith("## Surprising Connections")
        )
    except StopIteration:
        si = -1
    if si >= 0:
        for line in lines[si + 1 :]:
            m = re.match(
                r"^-\s+`(?P<src>[^`]+)`\s*--(?P<rel>\w+)-->\s*`(?P<dst>[^`]+)`\s*\[(?P<conf>\w+)\]",
                line,
            )
            if m:
                state["surprises"].append(
                    (m.group("src"), m.group("rel"), m.group("dst"), m.group("conf"))
                )
            elif line.startswith("## "):
                break

    for line in lines:
        m = COMMUNITY_HEAD_RE.match(line)
        if m:
            state["labels"][int(m.group("cid"))] = m.group("label")

    # graph.json: authoritative per-community membership
    gj = GRAPHIFY_OUT / "graph.json"
    if gj.exists():
        try:
            data = json.loads(gj.read_text(encoding="utf-8"))
            sizes: dict[int, int] = {}
            for node in data.get("nodes", []):
                cid = node.get("community")
                if cid is not None:
                    sizes[int(cid)] = sizes.get(int(cid), 0) + 1
            state["community_sizes"] = sizes
            state["nodes"] = state["nodes"] or len(data.get("nodes", []))
            state["edges"] = state["edges"] or len(
                data.get("links", data.get("edges", []))
            )
        except (json.JSONDecodeError, OSError):
            pass

    # labels sidecar (kept on disk by the graphify refresh so this note is stable)
    lj = GRAPHIFY_OUT / ".graphify_labels.json"
    if lj.exists():
        try:
            raw = json.loads(lj.read_text(encoding="utf-8"))
            state["labels"] = {int(k): v for k, v in raw.items()}
        except (json.JSONDecodeError, OSError):
            pass

    # detect sidecar: exact scope file list + word count
    dj = GRAPHIFY_OUT / ".graphify_detect.json"
    if dj.exists():
        try:
            det = json.loads(dj.read_text(encoding="utf-8"))
            state["files"] = int(det.get("total_files", 0) or 0)
            state["words"] = int(det.get("total_words", 0) or 0)
            if not head:
                files = [f for fs in det.get("files", {}).values() for f in fs]
                if files:
                    state["scope"] = Path(files[0]).parent.as_posix()
        except (json.JSONDecodeError, OSError):
            pass

    return state


def graphify_note(g: dict, ts: str) -> str:
    if not g["present"]:
        return f"""# Knowledge Graph (graphify)

#experiment #graph

> *Auto-generated by `scripts/vault/build_vault.py` via
> `scripts/vault/export_graft.py` - edit the exporter, not this file.*
> *Last sync: {ts}*

**BLOCKED:** no `graphify-out/GRAPH_REPORT.md` on disk, so there is no community
graph to summarise. Re-run `/graphify scripts/training` to rebuild it.

## Backlinks / Related

- [[Repo Graph (graft)]]
{chr(10).join("- " + b for b in BACKLINKS)}
"""

    scope = g["scope"]
    date = g["date"]
    age = report_age_days(date)
    if age is None:
        fresh_word = "date unparseable, treat as stale"
    elif age <= 1:
        fresh_word = "**fresh**, rebuilt today"
    elif age <= 30:
        fresh_word = f"**{age} days old**, re-run to refresh"
    else:
        fresh_word = f"**STALE, {age} days old** - re-run before trusting it"

    comm_rows = []
    for cid in sorted(g["labels"]):
        label = g["labels"][cid]
        size = g["community_sizes"].get(cid)
        comm_rows.append(
            f"| {cid} | [[_COMMUNITY_{label}\\|{label}]] | {size if size is not None else '-'} |"
        )
    if not comm_rows:
        comm_rows.append("| - | _(no labelled communities in report)_ | - |")

    god_rows = (
        "\n".join(f"| `{label}` | {deg} |" for label, deg in g["god_nodes"][:10])
        or "| _(none reported)_ | - |"
    )

    surprise_rows = (
        "\n".join(
            f"| `{src}` | {rel} | `{dst}` | {conf} |"
            for src, rel, dst, conf in g["surprises"][:6]
        )
        or "| _(none reported)_ | - | - | - |"
    )

    honesty = (
        f"**Scope:** `{scope}` · **{g['files']}** files · ~{g['words']:,} words\n"
        f"- **Report date:** {date} - {fresh_word}"
    )
    if g["isolated"] is not None:
        honesty += f"\n- **Isolated nodes:** {g['isolated']} (≤1 connection - the honest weak spots)"

    return f"""# Knowledge Graph (graphify)

#experiment #graph

> *Auto-generated by `scripts/vault/build_vault.py` via
> `scripts/vault/export_graft.py` - edit the exporter, not this file.*
> *Last sync: {ts}*

The **community** graph, as opposed to [[Repo Graph (graft)]]'s **call** graph.
graphify clusters the corpus and asks "what belongs together?", naming
communities; it does not answer "who calls whom?".

{honesty}
- **Counts:** {g["nodes"]} nodes · {g["edges"]} edges · {g["communities"]} communities
- **Extraction:** {g["extraction_line"] or "_(not stated in report)_"}
- **Token cost:** {g["token_line"] or "_(not stated in report)_"}
- **Corpus note (verbatim from report):** {g["corpus_warning"] or "_(none)_"}

## Communities

| # | community | nodes |
|---|---|---|
{chr(10).join(comm_rows)}

The `[[_COMMUNITY_...]]` wikilinks above mirror the ones the report emits; the
canonical ones live in `graphify-out/GRAPH_REPORT.md`, and the interactive view
is [graphify-out/graph.html](graphify-out/graph.html). Node counts come from
`graph.json`, so the thin communities the report omits are still listed here.

## God nodes (most connected)

| node | degree |
|---|---|
{god_rows}

## Surprising connections (from the report)

| from | relation | to | confidence |
|---|---|---|---|
{surprise_rows}

## Scope honesty

- graphify here covers **only** `{scope}` - a bounded slice of this repo, not the
  whole tree. `graphify-out/` is *not* rebuilt on every commit, so read this note
  as a dated snapshot; [[Repo Graph (graft)]] is the always-current one.
- The predecessor run (2026-09-09, `models/orion_custom_lora`, 531 nodes / 44
  communities) reported 463 isolated nodes - mostly LoRA `adapter_config.json`
  keys rather than ORION structure. It was replaced, not quietly dropped.
- Extraction took graphify's deterministic AST path (code-only corpus), so
  **0 input / 0 output tokens**. Any INFERRED edge comes from graphify's own
  heuristics, not from an LLM reading prose.
- Re-run: `/graphify <path>` (see the `graphify` skill), then
  `python scripts/vault/build_vault.py`.
- Report: [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md) ·
  raw graph: [graphify-out/graph.json](graphify-out/graph.json) ·
  viz: [graphify-out/graph.html](graphify-out/graph.html)

## Backlinks / Related

- [[Repo Graph (graft)]] - the call-graph sibling note
{chr(10).join("- " + b for b in BACKLINKS)}
"""


# ---------------------------------------------------------------- public api


def build_notes() -> dict[Path, str]:
    """All builder-owned notes this exporter produces, keyed by vault path."""
    ts = datetime.now(timezone.utc).isoformat(timespec="minutes")
    cards = [read_card_symbols(c) for c in graft_cards()]
    scopes = group_by_scope(cards)

    notes: dict[Path, str] = {}
    for scope, scope_cards in scopes.items():
        folder, title, _ = (
            SCOPE_META.get(
                scope, ("02 - Architecture", f"Repo Graph scope - {scope}", "")
            )
            if scope
            else ROOT_SCOPE
        )
        notes[REPO_ROOT / "vault" / folder / f"{title}.md"] = scope_note(
            scope, scope_cards, ts
        )

    notes[REPO_ROOT / "vault" / "02 - Architecture" / "Repo Graph (graft).md"] = (
        repo_graph_note(scopes, len(cards), ts)
    )
    notes[
        REPO_ROOT / "vault" / "11 - Experiments" / "Knowledge Graph (graphify).md"
    ] = graphify_note(graphify_state(), ts)
    return notes


def main() -> int:
    cards = [read_card_symbols(c) for c in graft_cards()]
    scopes = group_by_scope(cards)
    g = graphify_state()
    print(f"[graft] {len(cards)} cards across {len(scopes)} scopes")
    for scope in sorted(scopes):
        sym = sum(c["symbols"] for c in scopes[scope])
        print(
            f"  {scope or '(root)':<16} {len(scopes[scope]):>4} cards  {sym:>5} symbols"
        )
    print(
        f"[graphify] present={g['present']} scope={g['scope']} date={g['date']} "
        f"nodes={g['nodes']} edges={g['edges']} communities={g['communities']}"
    )
    print(
        f"[export_graft] {len(build_notes())} notes would be written by build_vault.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
