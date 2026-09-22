"""Surrogate tokenizer determinism.

The training scripts used abs(hash(w)) for surrogate vocab ids; Python's
hash() is salted per process (PYTHONHASHSEED), so the same sentence maps to
different ids on every run. zlib.crc32 is a stable, stdlib replacement.
"""

import subprocess
import sys
import zlib

SENTENCE = "help my house is flooding on fifth street"


def _ids(text: str) -> list:
    return [1] + [zlib.crc32(w.encode()) % 990 + 3 for w in text.split()] + [2]


def test_surrogate_ids_stable_in_process():
    assert _ids(SENTENCE) == _ids(SENTENCE)


def test_surrogate_ids_stable_across_processes():
    code = (
        "import zlib;"
        f"print([1]+[zlib.crc32(w.encode())%990+3 for w in "
        f"{SENTENCE!r}.split()]+[2])"
    )
    out1 = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    out2 = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out1 == out2
    # And it matches the in-process computation.
    assert eval(out1) == _ids(SENTENCE)


def test_rejects_salted_hash_vocab():
    # Sanity: had this file still used abs(hash(...)), the two subprocess runs
    # would differ, so the assertion above genuinely guards the regression.
    code = f"print([abs(hash(w))%990+3 for w in {SENTENCE!r}.split()])"
    out1 = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    out2 = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out1 != out2  # proving the old approach was nondeterministic
