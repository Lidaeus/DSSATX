"""Run the water-nitrogen stress four-corner calibration with Sobol initial ensemble.

Two-season (25SP + 26SP) four-corner design:
  W3xN0, W3xN3, W1xN0, W1xN3 (4 treatments per season = 8 runs/realization).

Uses a Sobol sequence for the initial parameter ensemble (better uniform
coverage than LHS for high-dimensional spaces), built on the e02 nochtd
posterior bounds + 9 new water/nitrogen stress parameters.

Usage::

    # Smoke (10 realizations, 1 iteration)
    python tools/calibration/run_e02_wnstress_fourcorner.py --smoke --execute

    # Formal (200 realizations, 5 iterations)
    python tools/calibration/run_e02_wnstress_fourcorner.py --execute
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv

DESIGN = ROOT / "configs/runs/eggplant_e02_wnstress_fourcorner_design_v1_20260801.json"
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_nochtd_v1.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_n_response_group_policy_harvestdry250_v2.csv"
BOUNDS_ID_DEFAULT = "eggplant_e02_wnstress_fourcorner_v1_20260801"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"


def run(cmd: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def apply_sobol_ensemble(run_dir: Path, case: str, *, n_reals: int, seed: int) -> None:
    """Generate a Sobol initial ensemble and write it into the PST."""
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    par_df = pst.parameter_data.copy()
    bounds_df = pd.DataFrame({
        "name": par_df["parnme"],
        "init": pd.to_numeric(par_df["parval1"], errors="coerce"),
        "lower": pd.to_numeric(par_df["parlbnd"], errors="coerce"),
        "upper": pd.to_numeric(par_df["parubnd"], errors="coerce"),
        "status": ["fixed" if str(v).strip().lower() == "fixed" else "active"
                    for v in par_df["partrans"]],
    })
    active_df = generate_lhs_ensemble(
        n_reals=n_reals, bounds_df=bounds_df, seed=seed,
        method="sobol", include_base=False,
    )
    ensemble_df = pd.DataFrame({"real_name": active_df["real_name"]})
    active_cols = set(active_df.columns) - {"real_name"}
    for row in bounds_df.itertuples(index=False):
        name = str(row.name)
        if name in active_cols:
            ensemble_df[name] = active_df[name]
        else:
            ensemble_df[name] = float(row.init)
    ensemble_path = run_dir / f"{case}.0.par.csv"
    write_ensemble_csv(ensemble_df, ensemble_path)
    pst.pestpp_options["ies_parameter_ensemble"] = ensemble_path.name
    pst.write(str(run_dir / f"{case}.pst"))
    print(f"Sobol ensemble: {n_reals} realizations, {len(active_cols)} active params -> {ensemble_path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="E02 water/N stress four-corner calibration")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260801)
    parser.add_argument("--bounds-id", default=BOUNDS_ID_DEFAULT)
    parser.add_argument("--design", type=Path, default=DESIGN,
                        help="Multiseason design JSON (defaults to the actual-IC four-corner design)")
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR,
                        help="Primary input bundle directory used by build_pest")
    parser.add_argument("--observation-policy-csv", type=Path, default=POLICY,
                        help="Observation policy CSV; design-level group policy remains authoritative")
    parser.add_argument("--smoke", action="store_true", help="Quick 10x1 smoke test")
    parser.add_argument("--execute", action="store_true", help="Launch PEST++ after build")
    args = parser.parse_args()

    if args.smoke:
        args.n_reals = 10
        args.noptmax = 1

    run_id = args.run_id or (
        f"e02_wnstress_fourcorner_{'smoke' if args.smoke else 'formal'}_"
        f"{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    run_dir = ROOT / "workspace/runs" / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)

    build_cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(args.design),
        "--input-dir", str(args.input_dir),
        "--bounds-id", args.bounds_id,
        "--bounds-crop", "eggplant",
        "--prefix", run_id,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(args.input_dir / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "off",
        "--observation-policy-csv", str(args.observation_policy_csv),
    ]
    run(build_cmd)
    apply_sobol_ensemble(run_dir, run_id, n_reals=args.n_reals, seed=args.random_seed)

    if not args.execute:
        print(f"Build complete (no --execute). PST at: {run_dir}/{run_id}.pst")
        return 0

    run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", run_id,
        "--mode", "ies",
        "--n-agents", str(args.n_agents),
        "--wait",
    ])
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    eng = status.get("engineering_status", "unknown")
    print(f"Engineering status: {eng}")
    if eng != "engineering_validated":
        print(f"  error: {status.get('engineering_status_error', '?')}")
        return 1
    print(f"Engineering validation PASSED: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
