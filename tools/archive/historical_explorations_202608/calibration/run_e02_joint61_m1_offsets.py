"""Build, verify, and run E02 joint calibration with documented autumn offsets."""

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
DESIGN = ROOT / "configs" / "runs" / "eggplant_e02_joint61_25sp_25fa_autumn_offsets_v3_20260729.json"
POLICY = ROOT / "configs" / "runs" / "e02_55_fit_first_observation_policy_v1.csv"
CHPDT_LOG_POLICY = ROOT / "configs" / "runs" / "e02_55_fit_first_observation_policy_chpdt_log_v1.csv"
SELECTIVE_CHPDT_CHTD_POLICY = ROOT / "configs" / "runs" / "e02_selective_chpdt_chtd_log_v1.csv"
HARVEST_PROCESS_LOG_POLICY = ROOT / "configs" / "runs" / "e02_55_fit_first_observation_policy_harvest_process_log_v1.csv"
BOUNDS_ID = "eggplant_e02_joint61_m1_offsets_v3_20260729"
INPUT_DIR = ROOT / "data" / "user" / "experiments" / "xxql2501_actual_trial_calibration_v5_adap21_moisturefix_page25_20260729"
OFFSET_NAMES = {
    "DLFMAX_AUT", "DSLAVR_AUT", "DXFRT_AUT", "DSFDUR_AUT",
    "DTB1_AUT", "DTB2_AUT", "DTB3_AUT",
}
IES_STABILITY_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
}


def _run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _apply_stability_profile(run_dir: Path, case: str) -> None:
    pst_path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.pestpp_options.update(IES_STABILITY_PROFILE)
    pst.write(str(pst_path))


def _verify_case(
    run_dir: Path,
    case: str,
    *,
    n_reals: int,
    noptmax: int,
    bounds_id: str = BOUNDS_ID,
) -> dict[str, object]:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    bounds = pd.read_csv(
        ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / f"{bounds_id}.csv",
        encoding="utf-8-sig",
    )
    problems: list[str] = []
    parameter_names = {str(name).upper() for name in pst.parameter_data.index}
    active_bounds = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")]

    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"noptmax must be {noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append(f"ies_num_reals must be {n_reals}")
    if float(pst.pestpp_options.get("ies_bad_phi_sigma", 0.0)) < 1e299:
        problems.append("automatic relative-Phi culling must remain disabled")
    for option, expected in IES_STABILITY_PROFILE.items():
        actual = pst.pestpp_options.get(option)
        if str(actual).strip().lower() != str(expected).strip().lower():
            problems.append(f"IES stability option {option} is not {expected!r}")
    if pst.npar_adj != 61 or len(active_bounds) != 61:
        problems.append(f"expected 61 adjustable terms; PST={pst.npar_adj}, frozen={len(active_bounds)}")
    if not OFFSET_NAMES <= parameter_names:
        problems.append("one or more documented autumn offsets are missing")
    seasonal_group = pst.parameter_data.loc[
        pst.parameter_data.index.astype(str).str.upper().isin(OFFSET_NAMES), "pargp"
    ].astype(str).str.lower()
    if not seasonal_group.eq("seasonal_offset").all():
        problems.append("autumn offsets must use pargp=seasonal_offset")
    if set(registry["season_id"].astype(str)) != {"25SP", "25FA"}:
        problems.append("observation registry must contain 25SP and 25FA only")
    active = registry.loc[registry["weight"] > 0]
    # The repaired 25FA bundle carries three growth dates (8 selected
    # treatments x 3 dates x 4 growth targets), adding 64 active rows to the
    # former 646-row contract.
    if len(active) != 710:
        problems.append(f"expected 710 active observations after 25FA repair, found {len(active)}")
    active_names = active["obsnme"].astype(str).str.upper()
    if any(active_names.str.contains(token).any() for token in ("MDAP", "CHFPW", "PWAD", "PWAI", "HWAM")):
        problems.append("a diagnostic/legacy target entered active Phi")
    if "--design" not in " ".join(pst.model_command):
        problems.append("model command lost the seasonal design")
    if problems:
        raise RuntimeError("E02 joint M1 preflight failed: " + "; ".join(problems))

    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "bounds_id": bounds_id,
        "design": str(DESIGN),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "calibration_seasons": ["25SP", "25FA"],
        "seasonal_offsets": sorted(OFFSET_NAMES),
        "seasonal_interpretation": "25FA effective corrections; not a second genetic parameter set",
        "status": "built",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E02 joint M1 calibration with seven documented autumn offsets")
    parser.add_argument("--run-id", help="Default: timestamped run ID")
    parser.add_argument("--bounds-id", default=BOUNDS_ID)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--n-reals", type=int, default=300)
    parser.add_argument("--noptmax", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260730)
    parser.add_argument("--smoke", action="store_true", help="Use 20 realizations and one update")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--cumulative-log-transform",
        action="store_true",
        help="Use ln(CHPDT+1) for cumulative dry harvest instead of the raw CHPDT scale",
    )
    parser.add_argument(
        "--process-log-transform",
        action="store_true",
        help="Use ln(y+1) for positive LAID/LWAD/SWAD/CHTD trajectories and harvest targets",
    )
    parser.add_argument(
        "--selective-chpdt-chtd-transform",
        action="store_true",
        help="Use CHPDT/HPODW baseline transforms plus selective CHTD log transform",
    )
    args = parser.parse_args(argv)

    if args.n_agents < 1 or args.n_reals < 20 or args.noptmax < 1:
        raise ValueError("require n_agents>=1, n_reals>=20, and noptmax>=1")
    n_reals = 20 if args.smoke else args.n_reals
    noptmax = 1 if args.smoke else args.noptmax
    run_id = args.run_id or f"e02_joint61_m1_offsets_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = ROOT / "workspace" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")

    if args.selective_chpdt_chtd_transform:
        observation_policy = SELECTIVE_CHPDT_CHTD_POLICY
    elif args.process_log_transform:
        observation_policy = HARVEST_PROCESS_LOG_POLICY
    else:
        observation_policy = CHPDT_LOG_POLICY if args.cumulative_log_transform else POLICY
    _run([
        sys.executable,
        str(ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(DESIGN),
        "--input-dir", str(INPUT_DIR),
        "--bounds-id", args.bounds_id,
        "--bounds-crop", "eggplant",
        "--prefix", run_id,
        "--noptmax", str(noptmax),
        "--ies-num-reals", str(n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(INPUT_DIR / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "off",
        "--observation-policy-csv", str(observation_policy),
    ])
    _apply_stability_profile(run_dir, run_id)
    receipt = _verify_case(run_dir, run_id, n_reals=n_reals, noptmax=noptmax, bounds_id=args.bounds_id)
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {receipt_path}")

    if not args.execute:
        return 0
    _run([
        sys.executable,
        str(ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", run_id,
        "--mode", "ies",
        "--n-agents", str(args.n_agents),
        "--wait",
    ])
    status_path = run_dir / "run_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(
            "E02 joint M1 engineering gate failed: "
            + str(status.get("engineering_status_error") or status.get("engineering_status"))
        )
    _run([
        sys.executable,
        "-m", "src.reporting.export_seasonal_parameters",
        "--run-dir", str(run_dir),
        "--prefix", run_id,
        "--design", str(DESIGN),
    ])
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"E02 joint M1 calibration completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
