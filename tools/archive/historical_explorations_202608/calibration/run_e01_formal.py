"""Run all E01 sub-domain pre-calibration runs.

E01 is the sub-domain, single-season pre-calibration (matrix §3 E01).  Each
sub-trial identifies a feasible initialization region for one season x domain,
producing an auditable bounds proposal — not a final cultivar parameter set.

Sub-trials (run sequentially — two 8-agent managers compete for the same
local DSSAT installation):

  E01-P  25SP pheno-only        (PDAT/ADAT/MDAT(PODD proxy); HDAT excluded)
  E01-O  25SP organ-only        (120 obs, LAID/LWAD/SWAD)
  E01-O  25FA organ-only        (72 obs,  LAID/LWAD/SWAD)
  E01-Y  25SP yield full-domain (224 obs, all process + CHPDT)
  E01-Y  25FA yield full-domain (96 obs,  all process + CHPDT)
  E01-Y-strict 25SP CHPDT-only  (88 obs,  CHPDT only)
  E01-Y-strict 25FA CHPDT-only  (24 obs,  CHPDT only)

25FA pheno is skipped (matrix §3: 25FA lacks valid ADAP observations).

Smoke (20 reals / 1 update) has been verified end-to-end for all three
policies.  This script runs the formal 200x4 configuration.

Usage::

    python tools/calibration/run_e01_formal.py                    # all sub-trials
    python tools/calibration/run_e01_formal.py --only yield_strict # subset
    python tools/calibration/run_e01_formal.py --build-only        # build without IES
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.experiment_runner import prepare_experiment_run, run_build, run_execute

SPECS_DIR = PROJECT_ROOT / "configs" / "experiments" / "specs"

# Sub-trials in execution order (smallest/fastest first).  Each is a
# single-season, single-domain pre-calibration.
SUB_TRIALS: list[tuple[str, str, str]] = [
    # (label, spec_filename, run_suffix)
    ("E01-P 25SP phenology",        "E01_pre_calibration_25sp_pheno.json",     "pheno_25sp"),
    ("E01-O 25SP organ",            "E01_pre_calibration_25sp_organ.json",        "organ_25sp"),
    ("E01-O 25FA organ",            "E01_pre_calibration_25fa_organ.json",        "organ_25fa"),
    ("E01-Y 25SP yield full",       "E01_pre_calibration_25sp_yield.json",        "yield_full_25sp"),
    ("E01-Y 25FA yield full",       "E01_pre_calibration_25fa_yield.json",        "yield_full_25fa"),
    ("E01-Y-strict 25SP CHPDT",     "E01_pre_calibration_25sp_yield_strict.json", "yield_strict_25sp"),
    ("E01-Y-strict 25FA CHPDT",     "E01_pre_calibration_25fa_yield_strict.json", "yield_strict_25fa"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run all E01 sub-domain pre-calibration formal runs (200x4)."
    )
    parser.add_argument("--run-prefix", default=None, help="Run ID prefix (default: timestamped)")
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--ies-num-reals", type=int, default=None,
                        help="Override ensemble size without editing source specs")
    parser.add_argument("--noptmax", type=int, default=None,
                        help="Override number of IES updates without editing source specs")
    parser.add_argument("--build-only", action="store_true", help="Build PSTs without launching IES")
    parser.add_argument(
        "--only", nargs="+", default=None,
        help="Subset of run_suffixes to run (e.g. pheno_25sp organ_25sp)",
    )
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.run_prefix or f"e01_formal_{stamp}"
    work_root = PROJECT_ROOT / "workspace" / "runs"

    trials = SUB_TRIALS
    if args.only:
        wanted = set(args.only)
        trials = [t for t in SUB_TRIALS if t[2] in wanted]
        if not trials:
            print(f"No matching sub-trials for --only {args.only}", file=sys.stderr)
            return 2

    results: list[tuple[str, str, str]] = []  # (label, run_id, status)
    for label, spec_file, suffix in trials:
        spec_path = SPECS_DIR / spec_file
        run_id = f"{prefix}_{suffix}"
        run_dir = work_root / run_id
        print(f"\n{'='*70}\n{label}\n  spec: {spec_path.name}\n  run_dir: {run_dir}\n{'='*70}")
        if run_dir.exists():
            print(f"  SKIP: run dir already exists (refusing to overwrite): {run_dir}")
            results.append((label, run_id, "skipped_exists"))
            continue
        try:
            result = prepare_experiment_run(
                spec_path,
                run_dir,
                ies_num_reals=args.ies_num_reals,
                noptmax=args.noptmax,
            )
            run_build(result.spec, run_dir, prefix=run_id)
            if args.build_only:
                print(f"  [BUILD-ONLY] PST generated, not executing IES.")
                results.append((label, run_id, "built"))
                continue
            run_execute(result.spec, run_dir, prefix=run_id, n_agents=args.n_agents)
            import json
            status_path = run_dir / "run_status.json"
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
            eng = status.get("engineering_status", "unknown")
            print(f"  engineering_status: {eng}")
            results.append((label, run_id, eng))
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            results.append((label, run_id, f"failed: {exc}"))

    print(f"\n{'='*70}\nE01 formal run summary\n{'='*70}")
    for label, run_id, status in results:
        print(f"  {label:30s} {run_id:45s} {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
