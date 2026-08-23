import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS_API = os.path.join(REPO_ROOT, "apps", "api")

# main.py uses flat imports ("from database import ...") while tests import
# "apps.api.main"; both roots must be importable simultaneously.
for p in (REPO_ROOT, APPS_API):
    if p not in sys.path:
        sys.path.insert(0, p)

# Disable the SlowAPI rate limiter for the whole suite (see main.py IS_TESTING).
os.environ.setdefault("TESTING", "1")
