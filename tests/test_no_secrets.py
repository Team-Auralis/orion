import re
import subprocess
import pytest

# Credentials that were leaked in earlier commits. None of these may appear
# in the CURRENT tree; history itself is handled by the scrub runbook.
FORBIDDEN_LITERALS = [
    "operatorpass",
    "citizenpass",
    "admin_super_secret",
    "orion_super_secret_password_prod",
]

ALLOWED_PREFIXES = ("tests/",)


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def test_no_leaked_credential_literals_in_tree():
    offenders = []
    for path in _tracked_files():
        if path.startswith(ALLOWED_PREFIXES):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        low = content.lower()
        for literal in FORBIDDEN_LITERALS:
            # Word-boundary match so identifiers like 'citizenPassword'
            # don't trigger a false positive.
            if re.search(rf"(?<![a-z0-9]){re.escape(literal)}(?![a-z0-9])", low):
                offenders.append(f"{path}: {literal}")
    assert offenders == [], f"Leaked credentials present in tracked files: {offenders}"


def test_no_private_keys_tracked():
    tracked = _tracked_files()
    key_files = [f for f in tracked
                 if f.endswith(".key") or f.endswith(".pem")]
    # Certificates (public material) are fine; keys are not.
    private = []
    for f in key_files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            if "PRIVATE KEY" in fh.read():
                private.append(f)
    assert private == [], f"Private key material must not be tracked: {private}"


def test_dashboard_does_not_embed_direct_grant_passwords():
    import os
    import re

    pattern = re.compile(r"append\(\s*[\"']password[\"']\s*,\s*[\"']")
    hits = []
    for root, dirs, files in os_walk_dashboard():
        for name in files:
            if not name.endswith((".tsx", ".ts", ".js")):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8", errors="ignore") as f:
                if pattern.search(f.read()):
                    hits.append(path)
    assert hits == [], "Direct-grant password must come from env, not literals"


def os_walk_dashboard():
    import os

    base = os.path.join("apps", "dashboard", "src")
    if not os.path.isdir(base):
        return []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        yield root, dirs, files
