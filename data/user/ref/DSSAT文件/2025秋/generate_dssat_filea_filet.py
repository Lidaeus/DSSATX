#!/usr/bin/env python3
"""Compatibility entry point for regenerating corrected 2025 fall files."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate_dssat_all_seasons import main  # noqa: E402


if __name__ == "__main__":
    if "--season" not in sys.argv:
        sys.argv[1:1] = ["--season", "2025fall"]
    main()
