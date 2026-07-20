from __future__ import annotations

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def main():
    # 1. Clean root-level temp files
    root_files = [
        "DSSBatch.v48",
        "ERROR.OUT",
        "LUN.LST",
        "WARNING.OUT",
        "run.log",
    ]
    for filename in root_files:
        p = PROJECT_ROOT / filename
        if p.exists():
            print(f"Deleting root file: {p.name}")
            try:
                p.unlink()
            except Exception as e:
                print(f"Failed to delete {p.name}: {e}")

    # 2. Clean workspace/runs/ temporary files starting with "_"
    runs_dir = PROJECT_ROOT / "workspace" / "runs"
    if runs_dir.exists():
        for item in runs_dir.iterdir():
            if item.name.startswith("_"):
                print(f"Deleting workspace/runs item: {item.name}")
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as e:
                    print(f"Failed to delete {item.name}: {e}")

    print("Cleanup completed successfully!")

if __name__ == "__main__":
    main()
