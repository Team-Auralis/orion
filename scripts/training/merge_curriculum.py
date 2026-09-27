#!/usr/bin/env python3
"""Merge teacher-curriculum pass files into one deduplicated dataset.

Dedupes by (instruction, response) so repeating a pass with a temperature
that produces identical answers does not add duplicate rows. Also reports
how many rows each input contributed and the final class balance.

    python scripts/training/merge_curriculum.py \
        --base data/training/teacher_curriculum_merged5.jsonl \
        --in data/training/teacher_curriculum_r1.jsonl \
             data/training/teacher_curriculum_r2.jsonl \
             data/training/teacher_curriculum_r3.jsonl \
             data/training/teacher_curriculum_r4.jsonl \
        --out data/training/teacher_curriculum_merged6.jsonl
"""

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_rows(path: Path) -> list[dict]:
    return [
        json.loads(l)
        for l in path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=str, default="")
    ap.add_argument("--in", dest="inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    seen: dict[tuple[str, str], dict] = {}
    sources: dict[str, int] = {}

    def add(rows: list[dict], tag: str) -> None:
        added = 0
        for r in rows:
            key = (r.get("instruction", ""), r.get("response", ""))
            if key in seen:
                continue
            seen[key] = r
            added += 1
        sources[tag] = added

    if args.base:
        base = load_rows(Path(args.base))
        add(base, Path(args.base).name)
    for p in args.inputs:
        add(load_rows(Path(p)), Path(p).name)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in seen.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[MERGE] {len(seen)} unique rows -> {out}")
    for tag, n in sources.items():
        print(f"  + {tag}: {n} new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
