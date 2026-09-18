"""One-shot launcher for batch B (rawdiff_terminal mixed config).

Hard-codes the correct SIX_TREATMENT_PREFIX so the environment variable
cannot be accidentally dropped.

Usage (from D:\\Tomato_Cal):
    python tools/calibration/launch_rawdiff_terminal_nresp_wide_20260806.py
"""

import os
import sys
from pathlib import Path

PREFIX = "e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806"
ROOT = Path(r"D:/Tomato_Cal")
RUN_DIR = ROOT / "workspace/runs" / PREFIX


def main() -> int:
    if not RUN_DIR.is_dir():
        print(f"ERROR: target run directory not found: {RUN_DIR}", file=sys.stderr)
        return 1
    pst = RUN_DIR / f"{PREFIX}.pst"
    if not pst.is_file():
        print(f"ERROR: PST not found: {pst}", file=sys.stderr)
        return 1
    rec = RUN_DIR / f"{PREFIX}.rec"
    if rec.is_file():
        print(f"WARNING: {rec.name} already exists — the case may have been run.", file=sys.stderr)
        resp = input("Continue anyway? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return 1

    os.environ["SIX_TREATMENT_PREFIX"] = PREFIX
    print(f"[launch] SIX_TREATMENT_PREFIX={PREFIX}")
    print(f"[launch] RUN_DIR={RUN_DIR}")
    print(f"[launch] delegating to tools/run_custom_nresp_calibration.py ...")
    sys.path.insert(0, str(ROOT / "tools"))
    from run_custom_nresp_calibration import main as runner_main
    return runner_main()


if __name__ == "__main__":
    sys.exit(main())
