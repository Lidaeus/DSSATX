"""Pytest configuration for critical_n subproject test suite."""

import sys
from pathlib import Path

# Ensure repo root is always in sys.path during pytest execution
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
