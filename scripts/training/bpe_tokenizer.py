#!/usr/bin/env python3
"""Train a real byte-level BPE tokenizer over the resolved ORION corpus.

CPU-only via the installed `tokenizers` package. Saves HF-layout files to
`models/tokenizer_bpe/` (tokenizer.json + tokenizer_config.json +
special_tokens_map.json) so `scripts/training/convert_hf_to_gguf.py` can
consume the vocab later. Ends by emitting the `corpus-adequacy-gate` ledger
row (ADEQUATE vs SMOKE_ONLY) with the real corpus token count.

Usage:
    python scripts/training/bpe_tokenizer.py [--corpus data/training/corpus]
        [--vocab-size 10240] [--output models/tokenizer_bpe] [--gate-only]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

from tokenizers import Tokenizer  # noqa: E402
from tokenizers.decoders import ByteLevel as ByteLevelDecoder  # noqa: E402
from tokenizers.models import BPE  # noqa: E402
from tokenizers.pre_tokenizers import ByteLevel  # noqa: E402
from tokenizers.trainers import BpeTrainer  # noqa: E402

import orion_corpus  # noqa: E402

SPECIAL_TOKENS = ["<pad>", "<bos>", "<eos>", "<unk>"]


def train_bpe(corpus_dir: Path, vocab_size: int, output_dir: Path) -> dict:
    files, source, is_real = orion_corpus.resolve_corpus(corpus_dir)
    n_bytes = orion_corpus.corpus_bytes(files)
    if source != "corpus-shards":
        print(
            f"[bpe] WARNING: no shards in {corpus_dir}; "
            "training on the 9 KB smoke fallback"
        )
    print(
        f"[bpe] corpus source={source} shards={[p.name for p in files]} "
        f"bytes={n_bytes:,}"
    )

    tokenizer = Tokenizer(BPE(unk_token="<unk>"))
    # GPT-2 convention: byte-level BPE prefixes the first word with "\u0120"
    # (space), so encode/decode are exact inverses in the canonical (space-
    # prefixed) text domain.
    tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=True)
    tokenizer.decoder = ByteLevelDecoder()
    trainer = BpeTrainer(
        vocab_size=int(vocab_size),
        special_tokens=SPECIAL_TOKENS,
        min_frequency=1,
        show_progress=True,
    )
    tokenizer.train_from_iterator(orion_corpus.iter_texts(files), trainer=trainer)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(output_dir / "tokenizer.json"))
    _write_hf_sidecars(output_dir, vocab_size)

    # Round-trip byte fidelity check: encode -> decode must reproduce the
    # exact UTF-8 bytes. Byte-level BPE follows the GPT-2 leading-space
    # convention, so the inverse pairs hold in the canonical (space-prefixed)
    # text domain - decode(encode(" " + s)) == " " + s byte-for-byte.
    sample = (
        "AURA runs `orion` on a 7.7 GB laptop!\n"
        "INSTRUCTION: What is 2 + 3 * 4?\nRESPONSE: 14 (multiplication binds first)."
    )
    canonical = sample if sample.startswith(" ") else " " + sample
    enc = tokenizer.encode(canonical)
    dec = tokenizer.decode(enc.ids)
    canonical_bytes = canonical.encode("utf-8")
    assert dec.encode("utf-8") == canonical_bytes, "BPE round-trip byte fidelity failed"
    print(
        f"[bpe] round-trip OK: {len(enc.ids)} tokens -> exact "
        f"{len(canonical_bytes)}-byte canonical form (GPT-2 leading-space convention)"
    )

    total, unique = orion_corpus.count_corpus_tokens(tokenizer, files)
    trained_vocab = tokenizer.get_vocab_size()
    print(
        f"[bpe] trained vocab={trained_vocab:,} | total corpus tokens={total:,} "
        f"| unique tokens seen={unique:,} ({unique / trained_vocab:.2%} coverage)"
    )

    orion_corpus.emit_adequacy_gate(
        corpus_dir, actual_tokens=total, vocab_size=trained_vocab
    )

    print(
        f"[bpe] files -> {output_dir / 'tokenizer.json'}, tokenizer_config.json, "
        f"special_tokens_map.json, added_tokens.json"
    )
    return {
        "vocab_size": trained_vocab,
        "corpus_tokens": total,
        "unique_tokens": unique,
        "shards": [str(p) for p in files],
        "output": str(output_dir),
    }


def _write_hf_sidecars(output_dir: Path, target_vocab: int):
    """HF layout: tokenizer_config.json / special_tokens_map.json / added_tokens.json."""
    vids = {name: i for i, name in enumerate(SPECIAL_TOKENS)}
    config = {
        "bos_token": "<bos>",
        "eos_token": "<eos>",
        "pad_token": "<pad>",
        "unk_token": "<unk>",
        "bos_token_id": vids["<bos>"],
        "eos_token_id": vids["<eos>"],
        "pad_token_id": vids["<pad>"],
        "unk_token_id": vids["<unk>"],
        "add_bos_token": False,
        "add_eos_token": False,
        "model_max_length": 4096,
        "model_type": "orion-bpe",
        "tokenizer_class": "PreTrainedTokenizerFast",
        "trainer": {"vocab_size": target_vocab, "min_frequency": 1, "byte_level": True},
    }
    (output_dir / "tokenizer_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    special = {
        "bos_token": {
            "content": "<bos>",
            "lstrip": False,
            "rstrip": False,
            "single_word": False,
            "normalized": True,
        },
        "eos_token": {
            "content": "<eos>",
            "lstrip": False,
            "rstrip": False,
            "single_word": False,
            "normalized": True,
        },
        "pad_token": {
            "content": "<pad>",
            "lstrip": False,
            "rstrip": False,
            "single_word": False,
            "normalized": True,
        },
        "unk_token": {
            "content": "<unk>",
            "lstrip": False,
            "rstrip": False,
            "single_word": False,
            "normalized": True,
        },
    }
    (output_dir / "special_tokens_map.json").write_text(
        json.dumps(special, indent=2), encoding="utf-8"
    )
    (output_dir / "added_tokens.json").write_text(
        json.dumps({name: idx for name, idx in vids.items()}, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Train BPE tokenizer over the ORION corpus"
    )
    ap.add_argument("--corpus", type=str, default=str(orion_corpus.CORPUS_DIR))
    ap.add_argument("--vocab-size", type=int, default=10_240)
    ap.add_argument("--output", type=str, default=str(orion_corpus.BPE_DIR))
    ap.add_argument(
        "--gate-only",
        action="store_true",
        help="skip training; just (re)emit the corpus-adequacy gate row",
    )
    args = ap.parse_args()

    if args.gate_only:
        orion_corpus.emit_adequacy_gate(Path(args.corpus))
        return 0
    train_bpe(Path(args.corpus), args.vocab_size, Path(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
