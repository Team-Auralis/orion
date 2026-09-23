"""
CIC Layer 1: Deterministic Provenance & Cryptographic Integrity
=============================================================
Provides tamper-evident SHA-256 hash chaining of intent specifications.
Every modification to civilizational intent creates an immutable link
in the provenance ledger.
"""

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

GENESIS_PREV_HASH = "0" * 64


@dataclass
class IntentBlock:
    version: int
    timestamp: str
    author: str
    rationale: str
    intent_payload: Dict[str, Any]
    prev_hash: str
    block_hash: str = ""

    def calculate_hash(self) -> str:
        data = {
            "version": self.version,
            "timestamp": self.timestamp,
            "author": self.author,
            "rationale": self.rationale,
            "intent_payload": self.intent_payload,
            "prev_hash": self.prev_hash,
        }
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IntentProvenanceChain:
    """Manages an immutable, append-only cryptographic chain of intent versions."""

    def __init__(self):
        self.chain: List[IntentBlock] = []

    def append(self, version: int, author: str, rationale: str, intent_payload: Dict[str, Any]) -> IntentBlock:
        prev_hash = self.chain[-1].block_hash if self.chain else GENESIS_PREV_HASH
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        block = IntentBlock(
            version=version,
            timestamp=timestamp,
            author=author,
            rationale=rationale,
            intent_payload=intent_payload,
            prev_hash=prev_hash,
        )
        block.block_hash = block.calculate_hash()
        self.chain.append(block)
        return block

    def verify_integrity(self) -> tuple[bool, str]:
        """
        Verify the entire chain from genesis:
        1. Every block's hash matches its content.
        2. Every block's prev_hash matches the previous block's hash.
        """
        if not self.chain:
            return True, "Chain is empty"

        for i, block in enumerate(self.chain):
            expected_hash = block.calculate_hash()
            if block.block_hash != expected_hash:
                return False, f"Tamper detected at version {block.version}: hash mismatch"

            if i == 0:
                if block.prev_hash != GENESIS_PREV_HASH:
                    return False, f"Genesis block prev_hash invalid: {block.prev_hash}"
            else:
                prev_block = self.chain[i - 1]
                if block.prev_hash != prev_block.block_hash:
                    return False, f"Broken link between version {prev_block.version} and {block.version}"

        return True, "Chain integrity verified"

    def to_list(self) -> List[Dict[str, Any]]:
        return [asdict(b) for b in self.chain]
