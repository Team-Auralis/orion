"""ORION git-history credential scrub (R-08).

Builds a replacements file from the known-leaked literals and runs
`git filter-repo --replace-text` to rewrite all history.

SAFETY:
- History rewrite is destructive and changes every commit hash.
- ALL writers must be quiesced (no parallel actors/agents committing),
  and the rewritten branch must be force-pushed in coordination with
  every collaborator re-cloning or rebasing.
- The script refuses to run unless the working tree is clean and
  --execute is passed. Without --execute it only prints the plan.

Requires: pip install git-filter-repo
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Demo-token names are assembled from parts so no leaked literal sits in the
# tree; real leaked tokens go in ORION_SCRUB_TOKENS (comma-separated).
_DEMO_TOKENS = (
    ("operator", "pass"),
    ("citizen", "pass"),
    ("admin", "_super_secret"),
    ("orion", "_super_secret_password_prod"),
    ("orion", "_super_secret"),  # partial historical variants
)


def _leaked_tokens() -> list[str]:
    env_tokens = os.environ.get("ORION_SCRUB_TOKENS", "")
    if env_tokens.strip():
        return [t.strip() for t in env_tokens.split(",") if t.strip()]
    return [left + right for left, right in _DEMO_TOKENS]


LEAKED = _leaked_tokens()

REPLACEMENTS_HEADER = """# git filter-repo replace-text rules
# Each leaked literal becomes ***REMOVED***
"""


def sh(*args, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, cwd=cwd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--execute", action="store_true", help="Actually rewrite history (destructive)."
    )
    args = ap.parse_args()

    dirty = sh("git", "status", "--porcelain").stdout.strip()
    if dirty:
        print("REFUSING: working tree is not clean. Commit or stash first.")
        print(dirty)
        sys.exit(1)

    if sh("git", "filter-repo", "--version").returncode != 0:
        print("git-filter-repo is not installed. Run: pip install git-filter-repo")
        sys.exit(1)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(REPLACEMENTS_HEADER)
        for secret in LEAKED:
            tf.write(f"{secret}==>***REMOVED***\n")
        rules_path = tf.name

    count = int(sh("git", "rev-list", "--count", "HEAD").stdout.strip() or 0)
    print(f"Plan: rewrite {count} commits replacing {len(LEAKED)} literals.")
    print(f"Rules file: {rules_path}")

    if not args.execute:
        print("Dry-run only. Re-run with --execute when ALL writers are quiesced")
        print("and you are prepared to force-push with coordinated re-clones.")
        sys.exit(0)

    result = sh("git", "filter-repo", "--replace-text", rules_path, "--force")
    print(result.stdout)
    print(result.stderr)
    if result.returncode != 0:
        sys.exit(result.returncode)

    print("\nHistory rewritten. Next steps:")
    print("  1. Re-add origin if filter-repo removed it:")
    print("     git remote add origin https://github.com/Team-Auralis/orion.git")
    print("  2. Force-push with lease:  git push --force-with-lease origin main")
    print("  3. All collaborators must re-clone; old clones keep leaked data.")
    print("  4. Rotate any credentials that were pushed externally regardless.")


if __name__ == "__main__":
    main()
