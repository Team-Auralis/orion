#!/usr/bin/env python3
"""Build the real ORION pre-training corpus from legally-open text sources.

Downloads a curated open-text mixture (streaming via `datasets`), filters and
near-exact-dedups it, and writes top-level `.jsonl` shards under
`data/training/corpus/` in the exact format `orion_corpus.py` consumes:
one `{"text": "<doc>"}` object per line. Split is encoded in the file name
(`train-`/`val-`/`test-` prefixes) because `resolve_corpus()` only scans the
top level of the corpus dir (it does not recurse).

Legality & honesty
------------------
- Only open/legally-usable sources: wikitext-103 (CC BY-SA 3.0 + GFDL per the
  dataset card), FineWeb-Edu sample-10BT (ODC-By), The Pile uncopyrighted
  subset (documented US-public-domain works). Licenses are read live from the
  HF dataset card metadata when possible and recorded per shard in the
  manifest.
- NO corpus inflation: the builder only slices real source rows and removes
  duplicates/short/binary rows. It never duplicates, templates, or
  synthesizes text to hit a token budget. If the sources yield below the
  target after dedup, the run reports the honest measured numbers and stops.
- Contamination: none of the sources contain eval items (HellaSwag / ARC-Easy
  are not part of wikitext, FineWeb-Edu, or The Pile uncopyrighted). Use
  `check_leak()` to assert isolation against the built shards (Phase T5).

Disk safety
-----------
`ensure_disk()` aborts before a download stage when free space on the repo
drive is below the floor (8 GB) or below the planned requirement. The
transient HF cache is redirected under `data/training/corpus/.cache-build/`
(counted against the same budget) and removed after the build.

Usage:
    python scripts/training/corpus_builder.py --target-tokens 60_000_000
    python scripts/training/corpus_builder.py --target-tokens 60_000_000 --dry-run
    python scripts/training/corpus_builder.py --top-up --target-tokens 60_000_000
    python scripts/training/corpus_builder.py --check-leak "some eval sentence"

`--top-up` appends MORE real train rows from the same sources (resuming where
the previous build stopped, per manifest) to grow the measured train-token
count. It never deletes existing shards, forces every new row into `train-*`
(so val/test stay frozen), and near-exact dedups every new row against ALL
existing corpus text (train + val + test) so no duplicated content or
test/val contamination can enter. The top-up budget is computed from the real
BPE tokenizer's measured bytes/token on the current train shards, so
`--target-tokens` means the TOTAL corpus train-token target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "data" / "training" / "corpus"
BUILD_CACHE = CORPUS_DIR / ".cache-build"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"

DISK_FLOOR_GB = 8.0
PEAK_CACHE_GB = (
    3.0  # conservative peak transient disk (parquet/zips staged + final shards)
)
MIN_DOC_CHARS = 200
MAX_DOC_CHARS = 512_000  # oversized docs are chunked at paragraph boundaries (faithful, no text added)
# Calibrated against the PROJECT tokenizer (models/tokenizer_bpe, byte-level BPE,
# vocab 10_240): a 3 MB wiki-103 sample encodes at 2.02 chars/token. Keep 2.1 as a
# conservative proxy (fineweb text and tokenizer retrains may differ slightly).
# This replaces the generic 4 chars/token rule of thumb: a 10k-vocab byte-level BPE
# is ~2x more token-dense than a 50k-vocab tokenizer on English.
CHARS_PER_TOKEN = 2.1
BUDGET_SAFETY = (
    1.15  # headroom so the REAL count stays >= target after dedup/filter variance
)
BUFFER_SHARDS_BYTES = 32 * 1024 * 1024
# Content-hash split buckets: 0.5% test, 0.5% val, 99% train (deterministic per doc).
SPLIT_BUCKETS = (("test", 5), ("val", 10), ("train", 1_000))

SOURCES = [
    {
        "name": "wikitext",
        "abbr": "wiki",
        "repo_id": "wikitext",
        "config": "wikitext-103-raw-v1",
        "split": "train",
        "text_key": "text",
        "doc_url": "https://huggingface.co/datasets/wikitext",
        "documented_size": "train split ~516 MB / ~103M tokens; we slice",
        "license_fallback": "cc-by-sa-3.0, gfdl",
        "license_note": "Wikipedia featured/good articles; card records CC BY-SA 3.0 + GFDL",
        "mix_fraction": 0.55,
    },
    {
        "name": "fineweb-edu",
        "abbr": "fw",
        "repo_id": "HuggingFaceFW/fineweb-edu",
        "config": "sample-10BT",
        "split": "train",
        "text_key": "text",
        "doc_url": "https://huggingface.co/datasets/HuggingFaceFW/fineweb-edu",
        "documented_size": "sample-10BT config (~10B tokens); we take a small slice",
        "license_fallback": "odc-by",
        "license_note": "Open Data Commons Attribution License 1.0 (card-recorded)",
        "mix_fraction": 0.45,
    },
    {
        "name": "pile-uncopyrighted",
        "abbr": "pile",
        "repo_id": "monology/pile-uncopyrighted",
        "config": None,
        "split": "text",
        "text_key": "text",
        "doc_url": "https://huggingface.co/datasets/monology/pile-uncopyrighted",
        "documented_size": "The Pile uncopyrighted subset (~27 GB repo); take a slice",
        "license_fallback": "other (documented: US-public-domain works)",
        "license_note": "Card license field is 'other'; repo documents these works as uncopyrighted",
        "mix_fraction": 0.45,
    },
]

_WS_RE = re.compile(r"\s+")


# --- disk safety ------------------------------------------------------------


def free_disk_gb() -> float:
    return shutil.disk_usage(str(REPO_ROOT)).free / (1024**3)


def log_disk(stage: str) -> float:
    free = free_disk_gb()
    print(f"[corpus] disk after {stage}: {free:.2f} GB free")
    return free


def ensure_disk(stage: str, required_gb: float = 0.0) -> float:
    """Abort before a stage if free space is below the floor or the requirement."""
    free = free_disk_gb()
    need = max(DISK_FLOOR_GB, required_gb)
    if free < need:
        print(
            f"[corpus][ABORT] {stage}: free disk {free:.2f} GB < required "
            f"{need:.2f} GB (floor {DISK_FLOOR_GB:.1f} GB + headroom). Stopping cleanly."
        )
        sys.exit(2)
    print(
        f"[corpus] disk before {stage}: {free:.2f} GB free (floor {DISK_FLOOR_GB:.1f} GB)"
    )
    return free


def _stage_cache_env() -> None:
    """Redirect all HF/datasets caches under the corpus dir so transient data
    stays on the repo drive (counted in the disk budget) and is cleaned after."""
    BUILD_CACHE.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(BUILD_CACHE)
    os.environ["HF_HUB_CACHE"] = str(BUILD_CACHE / "hub")
    os.environ["HF_DATASETS_CACHE"] = str(BUILD_CACHE / "datasets")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def _cleanup_cache() -> None:
    if BUILD_CACHE.exists():
        size = sum(p.stat().st_size for p in BUILD_CACHE.rglob("*") if p.is_file())
        shutil.rmtree(BUILD_CACHE, ignore_errors=True)
        print(
            f"[corpus] cleaned transient HF cache {BUILD_CACHE.name} "
            f"({size / 1024**2:.1f} MB freed)"
        )


# --- licenses (live from dataset card, fallback to documented) --------------


def dataset_license(repo_id: str, fallback: str) -> tuple[str, str]:
    """Return (license_string, provenance). Tries the HF dataset card metadata."""
    try:
        from huggingface_hub import HfApi

        card_data = HfApi().dataset_info(repo_id, files_metadata=False).cardData or {}
        lic = card_data.get("license") or card_data.get("licenses") or fallback
        if isinstance(lic, list):
            lic = ", ".join(lic)
        return str(lic), "dataset card cardData.license"
    except Exception as exc:  # offline / API hiccup: documented license
        return fallback, f"documented (card lookup failed: {exc})"


# --- text cleaning / filtering ----------------------------------------------


def normalize_key(text: str) -> str:
    """Near-exact dedup key: whitespace-collapsed, lowercase full doc."""
    return _WS_RE.sub(" ", text).strip().lower()


def filter_reason(text: str) -> str | None:
    """Return 'short' / 'binary' when the doc should be dropped, else None."""
    t = text.strip()
    if len(t) < MIN_DOC_CHARS:
        return "short"
    n = len(t)
    weird = sum(1 for c in t if (ord(c) < 32 and c not in "\t\n\r") or c == "\ufffd")
    if weird / max(n, 1) > 0.005:
        return "binary"
    return None


def chunk_doc(text: str, cap: int = MAX_DOC_CHARS) -> list[str]:
    """Split oversized docs at paragraph boundaries (no text added or removed)."""
    if len(text) <= cap:
        return [text]
    pieces, cur = [], []
    cur_len = 0
    for para in text.split("\n\n"):
        if cur_len + len(para) > cap and cur:
            pieces.append("\n\n".join(cur))
            cur, cur_len = [], 0
        cur.append(para)
        cur_len += len(para) + 2
    if cur:
        pieces.append("\n\n".join(cur))
    return pieces


def split_bucket(key: str) -> str:
    """Deterministic content-hash split: 0.5% test / 0.5% val / 99% train."""
    r = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % 1_000
    for name, bound in SPLIT_BUCKETS:
        if r < bound:
            return name
    return "train"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


# --- streaming sources -------------------------------------------------------


def iter_source_rows(spec: dict):
    """Yield (row_idx, text) streaming from the source dataset (lazy import).

    The iterator is dropped + gc'd before returning so pyarrow's parquet
    generator finalizes while the interpreter is alive - abandoning it causes
    a teardown crash at process exit on Windows.
    """
    import gc

    from datasets import load_dataset

    args: tuple = (spec["repo_id"],)
    if spec.get("config"):
        args = (spec["repo_id"], spec["config"])
    ds = load_dataset(*args, split=spec["split"], streaming=True)
    try:
        for idx, row in enumerate(ds):
            text = row.get(spec["text_key"]) or row.get("content")
            if not isinstance(text, str):
                continue
            yield idx, text
    finally:
        try:
            del ds
        except Exception:
            pass
        gc.collect()


# --- shard writing -----------------------------------------------------------


class ShardWriter:
    """Buffered top-level jsonl shard writer: {split}-{abbr}-part-NNNNN.jsonl.

    Records a base manifest entry (path/split/rows/bytes/sha256) per flushed
    shard; source provenance is attached by the caller. `start_parts` seeds
    the next part index per (split, abbr) so a top-up run continues numbering
    where the previous build stopped instead of overwriting existing shards.
    """

    def __init__(self, corpus_dir: Path, start_parts: dict | None = None):
        self.corpus_dir = corpus_dir
        self.parts: dict[tuple[str, str], int] = dict(start_parts or {})
        self.bufs: dict[tuple[str, str], list[str]] = {}
        self.buf_bytes: dict[tuple[str, str], int] = {}
        self.entries: list[dict] = []

    def add(self, split: str, abbr: str, json_line: str) -> None:
        k = (split, abbr)
        if k not in self.bufs:
            self.bufs[k] = []
            self.buf_bytes[k] = 0
        if k not in self.parts:
            self.parts[k] = 0
        self.bufs[k].append(json_line)
        self.buf_bytes[k] += len(json_line.encode("utf-8"))
        if self.buf_bytes[k] >= BUFFER_SHARDS_BYTES:
            self.flush(k)

    def flush(self, k: tuple[str, str]) -> None:
        if not self.bufs.get(k):
            return
        split, abbr = k
        name = f"{split}-{abbr}-part-{self.parts[k]:05d}.jsonl"
        path = self.corpus_dir / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        data = "\n".join(self.bufs[k]) + "\n"
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)  # atomic: the resolver never sees a partial shard
        self.entries.append(
            {
                "path": name,
                "split": split,
                "rows": len(self.bufs[k]),
                "bytes": len(data.encode("utf-8")),
                "sha256": sha256_bytes(data.encode("utf-8")),
            }
        )
        self.bufs[k], self.buf_bytes[k] = [], 0
        self.parts[k] += 1
        print(
            f"[corpus] wrote {name} ({self.entries[-1]['rows']:,} rows, "
            f"{self.entries[-1]['bytes'] / 1024**2:.1f} MB)"
        )

    def flush_all(self) -> None:
        for k in list(self.bufs):
            self.flush(k)


# --- contamination check -----------------------------------------------------


def check_leak(manifest: dict, eval_text: str, ngram_tokens: int = 13) -> list[dict]:
    """Grep eval text (or its first `ngram_tokens`-token ngram) against every
    corpus shard listed in the manifest. Returns hit records; empty list = clean.

    Used by Phase T5 to assert eval isolation (e.g. HellaSwag / ARC-Easy items
    must not appear in the training corpus).
    """
    norm = normalize_key(eval_text)
    tokens = norm.split()
    ngram = " ".join(tokens[:ngram_tokens]) if tokens else norm
    hits = []
    for sh in manifest.get("shards", []):
        path = CORPUS_DIR / sh["path"]
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    doc = json.loads(line).get("text", "")
                except json.JSONDecodeError:
                    continue
                key = normalize_key(doc)
                ratio = 0.0
                if len(norm) >= 200 and norm in key:
                    ratio = len(norm) / max(len(key), 1)
                elif ngram in key:
                    ratio = len(ngram) / max(len(key), 1)
                if ratio > 0.0:
                    hits.append(
                        {
                            "shard": sh["path"],
                            "line": line_no,
                            "match": "full-text" if ratio > 0.9 else "ngram-prefix",
                            "matched_ratio": round(ratio, 4),
                        }
                    )
    return hits


# --- build -------------------------------------------------------------------


def _slice_budgets(target_tokens: int, source_specs: list[dict]) -> tuple[int, dict]:
    total_budget = int(target_tokens * CHARS_PER_TOKEN * BUDGET_SAFETY)
    fraction = sum(s["mix_fraction"] for s in source_specs)
    caps = {
        s["name"]: int(total_budget * s["mix_fraction"] / fraction)
        for s in source_specs
    }
    return total_budget, caps


def build(target_tokens: int, source_names: list[str]) -> dict:
    start_free = free_disk_gb()
    _stage_cache_env()
    ensure_disk("download stage", PEAK_CACHE_GB)

    selected = []
    for name in source_names:
        spec = next((s for s in SOURCES if s["name"] == name), None)
        if not spec:
            print(
                f"[corpus][ABORT] unknown source '{name}'. "
                f"Known: {[s['name'] for s in SOURCES]}."
            )
            sys.exit(2)
        selected.append(spec)
    total_budget, caps = _slice_budgets(target_tokens, selected)

    print(
        f"[corpus] target=~{target_tokens:,} tokens | budget={total_budget:,} raw bytes "
        f"(chars/token heuristic {CHARS_PER_TOKEN}) | sources={[s['name'] for s in selected]}"
    )

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove shards from any previous build so the manifest always matches the
    # files on disk (part-pattern only; README.md / smoke shard are untouched).
    stale = list(CORPUS_DIR.glob("*-part-*.jsonl"))
    for p in stale:
        p.unlink()
    if stale:
        print(
            f"[corpus] removed {len(stale)} stale shard file(s) from a previous build"
        )
    writer = ShardWriter(CORPUS_DIR)
    dedup_keys: set[str] = set()
    summary = []
    stats = {
        "pulled": 0,
        "short": 0,
        "binary": 0,
        "duplicate": 0,
        "kept": 0,
        "bytes_kept": 0,
        "words_kept": 0,
    }
    split_counts = {"train": 0, "val": 0, "test": 0}

    for spec in selected:
        lic, lic_src = dataset_license(spec["repo_id"], spec["license_fallback"])
        cap = caps[spec["name"]]
        src_stats = {k: 0 for k in stats}
        first_row = last_row = None
        src_bytes = 0
        shard_start = len(writer.entries)
        try:
            for row_idx, text in iter_source_rows(spec):
                stats["pulled"] += 1
                src_stats["pulled"] += 1
                if first_row is None:
                    first_row = row_idx
                last_row = row_idx
                reason = filter_reason(text)
                if reason == "short":
                    stats["short"] += 1
                    src_stats["short"] += 1
                    continue
                if reason == "binary":
                    stats["binary"] += 1
                    src_stats["binary"] += 1
                    continue
                for piece in chunk_doc(text):
                    key = normalize_key(piece)
                    if key in dedup_keys:
                        stats["duplicate"] += 1
                        src_stats["duplicate"] += 1
                        continue
                    dedup_keys.add(key)
                    split = split_bucket(key)
                    line = json.dumps({"text": piece}, ensure_ascii=False)
                    writer.add(split, spec["abbr"], line)
                    nbytes = len(line.encode("utf-8"))
                    stats["kept"] += 1
                    stats["bytes_kept"] += nbytes
                    stats["words_kept"] += len(piece.split())
                    src_stats["kept"] += 1
                    src_stats["bytes_kept"] += nbytes
                    split_counts[split] += 1
                    src_bytes += nbytes
                if src_bytes >= cap:
                    print(
                        f"[corpus] {spec['name']}: slice budget reached "
                        f"({src_bytes / 1024**2:.1f} MB of {cap / 1024**2:.1f} MB)"
                    )
                    break
                if stats["bytes_kept"] >= total_budget:
                    break
        except Exception as exc:
            print(f"[corpus][WARN] source '{spec['name']}' failed mid-stream: {exc!r}")
        writer.flush_all()

        # Attach provenance to the shards flushed for this source.
        for entry in writer.entries[shard_start:]:
            entry.update(
                {
                    "source_dataset": spec["repo_id"],
                    "source_config": spec["config"] or "(default)",
                    "source_split": spec["split"],
                    "slice": (
                        f"streaming slice rows {first_row}..{last_row} of the source split; "
                        "near-exact dedup + min-length/binary filters applied globally"
                    ),
                    "transformation": (
                        "none (exact source text); oversized docs chunked at "
                        "paragraph boundaries without adding/removing text"
                    ),
                    "license": lic,
                    "license_source": lic_src,
                    "license_note": spec["license_note"],
                    "download_url": spec["doc_url"],
                }
            )
        summary.append(
            {
                "source": spec["name"],
                "repo": spec["repo_id"],
                "config": spec["config"] or "(default)",
                "split": spec["split"],
                "license": lic,
                "rows_pulled": src_stats["pulled"],
                "rows_kept": src_stats["kept"],
                "bytes_kept": src_stats["bytes_kept"],
                "doc_url": spec["doc_url"],
            }
        )
        log_disk(f"source {spec['name']}")
        if stats["bytes_kept"] >= total_budget:
            print("[corpus] global text budget reached; stopping further sources")
            break

    dup_pct = 100.0 * stats["duplicate"] / max(stats["pulled"], 1)
    kept_pct = 100.0 * stats["kept"] / max(stats["pulled"], 1)

    print(
        f"[corpus] pulled={stats['pulled']:,} kept={stats['kept']:,} "
        f"({kept_pct:.1f}%) | dropped: short={stats['short']:,} "
        f"binary={stats['binary']:,} duplicate={stats['duplicate']:,} "
        f"({dup_pct:.2f}%)"
    )

    if stats["kept"] == 0:
        _cleanup_cache()
        print(
            "[corpus][ABORT] no rows kept after filtering/dedup. No corpus written - "
            "stopping at measured numbers rather than fabricating."
        )
        sys.exit(3)

    manifest = {
        "builder": "scripts/training/corpus_builder.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": _git_commit(),
        "target_tokens": target_tokens,
        "chars_per_token_heuristic": CHARS_PER_TOKEN,
        "budget_bytes": total_budget,
        "total_texts": stats["kept"],
        "total_bytes": stats["bytes_kept"],
        "rough_word_count": stats["words_kept"],
        "estimated_bpe_tokens": int(stats["bytes_kept"] / CHARS_PER_TOKEN),
        "token_count_note": (
            "HEURISTIC estimate: bytes / {:.1f} chars-per-token, calibrated against the "
            "project byte-level BPE tokenizer (models/tokenizer_bpe, vocab 10_240): "
            "2.02 chars/token measured on a 3 MB wiki-103 sample; 2.1 used as buffer. "
            "REAL token count is measured by scripts/training/bpe_tokenizer.py over "
            "resolve_corpus(). Pass/fail uses the real count."
        ).format(CHARS_PER_TOKEN),
        "dedup": {
            "method": "near-exact (whitespace-normalized, lowercase, full-doc SHA-256 set)",
            "pulled": stats["pulled"],
            "duplicate_dropped": stats["duplicate"],
            "duplicate_pct": round(dup_pct, 2),
        },
        "filters": {
            "min_doc_chars": MIN_DOC_CHARS,
            "max_doc_chars_chunked": MAX_DOC_CHARS,
            "short_dropped": stats["short"],
            "binary_dropped": stats["binary"],
        },
        "split_counts": split_counts,
        "holdout_compliance": {
            "note": (
                "No eval-style data is ingested. HellaSwag and ARC-Easy items are not part of "
                "wikitext-103, FineWeb-Edu, or The Pile uncopyrighted. Use check_leak(manifest, "
                "eval_text) to assert per-item isolation before eval (Phase T5)."
            )
        },
        "shards": writer.entries,
        "sources": summary,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[corpus] wrote manifest.json ({len(writer.entries)} shard entries)")

    _cleanup_cache()
    end_free = log_disk("build complete")
    print(
        f"[corpus] FREE DISK before={start_free:.2f} GB -> after={end_free:.2f} GB "
        f"(spent {start_free - end_free:.2f} GB)"
    )

    print("\n[corpus] summary:")
    print(f"  {'source':<22} {'pulled':>9} {'kept':>9} {'MB written':>11}  license")
    for s in summary:
        print(
            f"  {s['source']:<22} {s['rows_pulled']:>9,} {s['rows_kept']:>9,} "
            f"{s['bytes_kept'] / 1024**2:>10.1f}  {s['license']}"
        )
    return manifest


# --- top-up ------------------------------------------------------------------
# Top-up grows ONLY the train shards with more REAL rows from the same legal
# sources, resuming where the previous build stopped. Honesty rules are the
# same as the base build: no duplication/templating/synthesis - every new row
# is real source text that near-exact-dedup against the whole existing corpus.


_SLICE_RE = re.compile(r"rows (\d+)\.\.(\d+)")


def _last_consumed_row(manifest: dict, source_name: str) -> int:
    """Highest source row idx the previous build already consumed (resume)."""
    repo_id = next(
        (s["repo_id"] for s in SOURCES if s["name"] == source_name), source_name
    )
    last = -1
    for sh in manifest.get("shards", []):
        if sh.get("source_dataset") != repo_id:
            continue
        if "last_source_row" in sh:
            last = max(last, int(sh["last_source_row"]))
        m = _SLICE_RE.search(sh.get("slice", ""))
        if m:
            last = max(last, int(m.group(2)))
    for s in manifest.get("top_up", {}).get("sources", []):
        if s.get("source") == source_name and "last_row" in s:
            last = max(last, int(s["last_row"]))
    return last


def _existing_parts(corpus_dir: Path) -> dict[tuple[str, str], int]:
    """Highest existing part index per (split, abbr) from on-disk shards."""
    parts: dict[tuple[str, str], int] = {}
    for p in corpus_dir.glob("*-part-*.jsonl"):
        head, num = p.name[: -len(".jsonl")].rsplit("-part-", 1)
        split, abbr = head.split("-", 1)
        idx = int(num)
        parts[(split, abbr)] = max(parts.get((split, abbr), -1), idx)
    return parts


def _load_existing_dedup_keys(corpus_dir: Path) -> tuple[set[str], int]:
    """(normalized-key set, doc count) over EVERY existing shard (train/val/
    test) - the cross-shard dedup seed. Rows equal to any existing text are
    dropped, which also enforces the test/val contamination check."""
    keys: set[str] = set()
    n = 0
    for p in sorted(corpus_dir.glob("*-part-*.jsonl")):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line).get("text", "")
                except json.JSONDecodeError:
                    continue
                if not isinstance(doc, str) or not doc:
                    continue
                keys.add(normalize_key(doc))
                n += 1
    return keys, n


def _measure_train_tokens() -> tuple[int, int]:
    """(train_tokens, train_bytes) with the real 10,240 BPE over train shards.

    The gate measures with this same tokenizer, so the top-up budget MUST use
    the same ruler. Abort when the tokenizer is missing rather than guess.
    """
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))
    try:
        import orion_corpus
    except Exception as exc:  # pragma: no cover - environment failure
        print(f"[corpus][ABORT] cannot import orion_corpus for budgeting: {exc!r}")
        sys.exit(2)
    files, source, is_real = orion_corpus.resolve_corpus(CORPUS_DIR)
    if source != "corpus-shards":
        print("[corpus][ABORT] no real corpus shards found - nothing to top up.")
        sys.exit(2)
    if not orion_corpus.BPE_TOKENIZER_JSON.exists():
        print(
            f"[corpus][ABORT] real BPE tokenizer missing "
            f"({orion_corpus.BPE_TOKENIZER_JSON}) - cannot budget honestly. "
            "Train it first with scripts/training/bpe_tokenizer.py."
        )
        sys.exit(2)
    tok = orion_corpus.load_bpe_tokenizer()
    train = orion_corpus.train_shards(files)
    tokens, _ = orion_corpus.count_corpus_tokens(tok, train)
    tbytes = sum(p.stat().st_size for p in train)
    return tokens, tbytes


def top_up(target_tokens: int, source_names: list[str]) -> dict:
    """Append more real train rows from the same sources toward a TOTAL
    train-token target; never deletes existing shards. Returns the manifest."""
    start_free = free_disk_gb()
    if not MANIFEST_PATH.exists():
        print("[corpus][ABORT] no manifest.json - run the base build first.")
        sys.exit(2)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    selected = []
    for name in source_names:
        spec = next((s for s in SOURCES if s["name"] == name), None)
        if not spec:
            print(
                f"[corpus][ABORT] unknown source '{name}'. "
                f"Known: {[s['name'] for s in SOURCES]}."
            )
            sys.exit(2)
        selected.append(spec)

    _stage_cache_env()
    ensure_disk("download stage", PEAK_CACHE_GB)

    cur_tokens, cur_train_bytes = _measure_train_tokens()
    if cur_tokens >= target_tokens:
        print(
            f"[corpus] already at {cur_tokens:,} train tokens >= target "
            f"{target_tokens:,}; nothing to top up."
        )
        _cleanup_cache()
        return manifest
    observed = cur_train_bytes / max(cur_tokens, 1)
    add_tokens = target_tokens - cur_tokens
    add_bytes = int(add_tokens * observed * BUDGET_SAFETY)
    print(
        f"[corpus] TOP-UP total target={target_tokens:,} train tokens | "
        f"current={cur_tokens:,} | additional={add_tokens:,} tokens "
        f"(measured {observed:.3f} bytes/token on current train shards)"
    )
    print(
        f"[corpus] top-up budget = {add_bytes:,} bytes "
        f"({add_bytes / 1024**2:.0f} MB of NEW real text; "
        f"safety {BUDGET_SAFETY:.2f}x)"
    )

    fraction = sum(s["mix_fraction"] for s in selected)
    caps = {s["name"]: int(add_bytes * s["mix_fraction"] / fraction) for s in selected}

    dedup_keys, existing_docs = _load_existing_dedup_keys(CORPUS_DIR)
    print(
        f"[corpus] cross-shard dedup seeded with {existing_docs:,} existing "
        "docs (train+val+test) - repeats and val/test overlaps are dropped"
    )

    start_parts = {
        (split, abbr): idx + 1
        for (split, abbr), idx in _existing_parts(CORPUS_DIR).items()
    }
    writer = ShardWriter(CORPUS_DIR, start_parts=start_parts)

    stats = {
        "pulled": 0,
        "short": 0,
        "binary": 0,
        "dup_existing": 0,
        "dup_new": 0,
        "kept": 0,
        "bytes_kept": 0,
        "words_kept": 0,
    }
    top_ups = []
    new_keys: set[str] = set()

    for spec in selected:
        resume_after = _last_consumed_row(manifest, spec["name"])
        lic, lic_src = dataset_license(spec["repo_id"], spec["license_fallback"])
        cap = caps[spec["name"]]
        src_stats = {k: 0 for k in stats}
        first_new = last_new = None
        src_bytes = 0
        shard_start = len(writer.entries)
        print(
            f"[corpus] {spec['name']}: resuming after source row {resume_after:,} "
            f"| cap {cap / 1024**2:.1f} MB of new text"
        )
        try:
            for row_idx, text in iter_source_rows(spec):
                if row_idx <= resume_after:
                    continue
                stats["pulled"] += 1
                src_stats["pulled"] += 1
                if first_new is None:
                    first_new = row_idx
                last_new = row_idx
                reason = filter_reason(text)
                if reason == "short":
                    stats["short"] += 1
                    src_stats["short"] += 1
                    continue
                if reason == "binary":
                    stats["binary"] += 1
                    src_stats["binary"] += 1
                    continue
                for piece in chunk_doc(text):
                    key = normalize_key(piece)
                    if key in dedup_keys:
                        if key in new_keys:
                            stats["dup_new"] += 1
                            src_stats["dup_new"] += 1
                        else:
                            stats["dup_existing"] += 1
                            src_stats["dup_existing"] += 1
                        continue
                    dedup_keys.add(key)
                    new_keys.add(key)
                    # Top-up grows ONLY train; val/test stay frozen.
                    split = "train"
                    line = json.dumps({"text": piece}, ensure_ascii=False)
                    writer.add(split, spec["abbr"], line)
                    nbytes = len(line.encode("utf-8"))
                    stats["kept"] += 1
                    stats["bytes_kept"] += nbytes
                    stats["words_kept"] += len(piece.split())
                    src_stats["kept"] += 1
                    src_stats["bytes_kept"] += nbytes
                    src_bytes += nbytes
                if src_bytes >= cap:
                    print(
                        f"[corpus] {spec['name']}: top-up cap reached "
                        f"({src_bytes / 1024**2:.1f} MB of {cap / 1024**2:.1f} MB)"
                    )
                    break
                if stats["bytes_kept"] >= add_bytes:
                    break
        except Exception as exc:
            print(f"[corpus][WARN] source '{spec['name']}' failed mid-stream: {exc!r}")
        writer.flush_all()

        for entry in writer.entries[shard_start:]:
            entry.update(
                {
                    "source_dataset": spec["repo_id"],
                    "source_config": spec["config"] or "(default)",
                    "source_split": spec["split"],
                    "slice": (
                        f"TOP-UP streaming slice rows {first_new}..{last_new} of the "
                        "source split (resumed after the base build); near-exact dedup "
                        "vs ALL existing corpus shards (train/val/test) applied"
                    ),
                    "last_source_row": last_new,
                    "top_up": True,
                    "transformation": (
                        "none (exact source text); oversized docs chunked at "
                        "paragraph boundaries without adding/removing text"
                    ),
                    "license": lic,
                    "license_source": lic_src,
                    "license_note": spec["license_note"],
                    "download_url": spec["doc_url"],
                }
            )
        top_ups.append(
            {
                "source": spec["name"],
                "repo": spec["repo_id"],
                "config": spec["config"] or "(default)",
                "split": spec["split"],
                "license": lic,
                "resumed_after_row": resume_after,
                "last_row": last_new,
                "rows_pulled": src_stats["pulled"],
                "rows_kept": src_stats["kept"],
                "rows_skipped_existing_dup": src_stats["dup_existing"],
                "rows_skipped_new_dup": src_stats["dup_new"],
                "short_dropped": src_stats["short"],
                "binary_dropped": src_stats["binary"],
                "bytes_kept": src_stats["bytes_kept"],
                "doc_url": spec["doc_url"],
            }
        )
        log_disk(f"source {spec['name']}")
        if stats["bytes_kept"] >= add_bytes:
            print("[corpus] top-up text budget reached; stopping further sources")
            break

    if stats["kept"] == 0:
        _cleanup_cache()
        print(
            "[corpus][ABORT] top-up kept 0 rows after cross-shard dedup - no "
            "new real text was available past the resume point. Reporting "
            "measured numbers, nothing fabricated."
        )
        sys.exit(3)

    # Refresh every shard entry (old + new) from disk so manifest rows/bytes/
    # sha256 are exactly truthful (previous build entries were stale).
    manifest["shards"] = manifest["shards"] + writer.entries
    for sh in manifest["shards"]:
        p = CORPUS_DIR / sh["path"]
        if not p.exists():
            continue
        data = p.read_bytes()
        sh["rows"] = data.count(b"\n")
        sh["bytes"] = len(data)
        sh["sha256"] = sha256_bytes(data)
    manifest["total_texts"] = sum(sh["rows"] for sh in manifest["shards"])
    manifest["total_bytes"] = sum(sh["bytes"] for sh in manifest["shards"])
    manifest["split_counts"] = {}
    for sh in manifest["shards"]:
        manifest["split_counts"][sh["split"]] = (
            manifest["split_counts"].get(sh["split"], 0) + sh["rows"]
        )
    train_bytes = sum(
        sh["bytes"] for sh in manifest["shards"] if sh["split"] == "train"
    )
    manifest["rough_word_count"] += stats["words_kept"]
    manifest["estimated_bpe_tokens"] = int(train_bytes / CHARS_PER_TOKEN)
    manifest["token_count_note"] = (
        "HEURISTIC estimate only (train bytes / 2.1 chars-per-token). The "
        "REAL train-only token count is measured by "
        "scripts/training/bpe_tokenizer.py --gate-only; pass/fail uses the "
        "real count."
    )
    manifest["top_up"] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_tokens_total": target_tokens,
        "current_train_tokens": cur_tokens,
        "observed_bytes_per_token": round(observed, 4),
        "additional_tokens_target": add_tokens,
        "additional_bytes_budget": add_bytes,
        "dedup": {
            "method": (
                "near-exact cross-shard (whitespace-normalized, lowercase "
                "full-doc set) against every existing shard incl. val/test"
            ),
            "existing_docs_seeded": existing_docs,
            "dup_existing_dropped": stats["dup_existing"],
            "dup_new_dropped": stats["dup_new"],
        },
        "filters": {
            "min_doc_chars": MIN_DOC_CHARS,
            "short_dropped": stats["short"],
            "binary_dropped": stats["binary"],
        },
        "split_policy": (
            "Top-up rows are all written to train-* shards; existing val/test "
            "shards are untouched, and rows whose text matches an existing "
            "val/test doc are dropped (contamination check)."
        ),
        "sources": top_ups,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[corpus] wrote manifest.json ({len(manifest['shards'])} shard entries)")

    _cleanup_cache()
    end_free = log_disk("build complete")
    print(
        f"[corpus] FREE DISK before={start_free:.2f} GB -> after={end_free:.2f} GB "
        f"(spent {start_free - end_free:.2f} GB)"
    )

    print("\n[corpus] top-up summary:")
    print(
        f"  {'source':<22} {'pulled':>9} {'kept':>9} {'x-dedup':>8} "
        f"{'new-dup':>8} {'MB added':>9}"
    )
    for t in top_ups:
        print(
            f"  {t['source']:<22} {t['rows_pulled']:>9,} {t['rows_kept']:>9,} "
            f"{t['rows_skipped_existing_dup']:>8,} {t['rows_skipped_new_dup']:>8,} "
            f"{t['bytes_kept'] / 1024**2:>8.1f}"
        )
    print(
        f"[corpus] NOTE: run 'python scripts/training/bpe_tokenizer.py "
        "--corpus data/training/corpus --gate-only' to record the real "
        "train-only token count and verdict."
    )
    return manifest


# --- dry run ----------------------------------------------------------------


def dry_run(target_tokens: int, source_names: list[str]) -> None:
    selected = [s for s in SOURCES if s["name"] in source_names]
    total_budget, caps = _slice_budgets(target_tokens, selected)
    free = free_disk_gb()
    estimate_shards = max(1, total_budget // BUFFER_SHARDS_BYTES)
    est_mb = total_budget / 1024**2
    print("[corpus] DRY RUN (no downloads)")
    print(f"  target tokens : {target_tokens:,}")
    print(
        f"  budget bytes  : {total_budget:,} "
        f"({est_mb:.0f} MB raw text @ {CHARS_PER_TOKEN} chars/token heuristic)"
    )
    print(
        f"  expected out  : ~{est_mb:.0f} MB of jsonl -> ~{estimate_shards} shards "
        f"(32 MB each) + manifest.json"
    )
    print("  planned sources:")
    for s in SOURCES:
        if s["name"] not in source_names:
            continue
        lic, lic_src = dataset_license(s["repo_id"], s["license_fallback"])
        print(
            f"    - {s['name']:<22} {s['repo_id']}/{s['config'] or '(default)'} "
            f"[{s['split']}]  slice up to {caps[s['name']] / 1024**2:.0f} MB  "
            f"license={lic}  ({lic_src})"
        )
        print(f"      documented: {s['documented_size']} | {s['license_note']}")
    print(
        f"  disk          : free now {free:.2f} GB | floor {DISK_FLOOR_GB:.1f} GB | "
        f"peak transient estimate {PEAK_CACHE_GB:.1f} GB (cache staged under "
        f"corpus/.cache-build/, removed after build)"
    )
    verdict = (
        "OK - proceed"
        if free >= max(DISK_FLOOR_GB, PEAK_CACHE_GB)
        else "ABORT - not enough disk"
    )
    print(f"  verdict       : {verdict}")


# --- CLI ---------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the real ORION pre-training corpus")
    ap.add_argument(
        "--target-tokens",
        type=int,
        default=60_000_000,
        help="token budget to aim for (50-150M envelope; real count measured later)",
    )
    ap.add_argument(
        "--sources",
        type=str,
        default="wikitext,fineweb-edu",
        help="comma-separated source names: wikitext, fineweb-edu, pile-uncopyrighted",
    )
    ap.add_argument(
        "--top-up",
        action="store_true",
        help=(
            "append more REAL train rows from the same sources toward the "
            "--target-tokens total; never deletes existing shards"
        ),
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="print the plan, do not download"
    )
    ap.add_argument(
        "--check-leak",
        type=str,
        metavar="TEXT",
        help="grep this eval text against the manifest shards (contamination check)",
    )
    args = ap.parse_args()

    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]

    if args.dry_run:
        dry_run(args.target_tokens, source_names)
        return 0

    if args.top_up:
        top_up(args.target_tokens, source_names)
        return 0

    if args.check_leak:
        if not MANIFEST_PATH.exists():
            print("[corpus][ABORT] no manifest.json - build the corpus first.")
            return 2
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        hits = check_leak(manifest, args.check_leak)
        if hits:
            print(f"[corpus] LEAK DETECTED: {len(hits)} hit(s)")
            for h in hits[:20]:
                print(f"    {h}")
        else:
            print("[corpus] no leak hits - corpus is clean for this eval text")
        return 0

    build(args.target_tokens, source_names)
    return 0


if __name__ == "__main__":
    sys.exit(main())
