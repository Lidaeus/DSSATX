"""Run the matched 25SP/25FA single-season T10 diagnostic calibrations.

This is intentionally a comparator, not a replacement for multi-season
calibration.  Each case uses the same T10-M0 frozen bounds, 200-member prior,
four IES updates, observation policy, direct CHFPW/CHPDT targets, and numerical
IES profile.  The only intended difference is the season's observed data and
its documented treatment set.
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
POLICY = ROOT / "configs" / "runs" / "assumption_based_sigma_v4.csv"
BOUNDS_ID = "eggplant_t10_m0_v1_20260722"
CASES = {
    "25SP": ROOT / "configs" / "runs" / "eggplant_t10_diagnostic_25sp_v1.json",
    "25FA": ROOT / "configs" / "runs" / "eggplant_t10_diagnostic_25fa_v1.json",
}

# Shared numerical profile prevents the aggressive default trial updates from
# becoming the sole reason that one season loses more realizations than another.
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
    path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(path))
    pst.pestpp_options.update(IES_STABILITY_PROFILE)
    pst.write(str(path))


def _verify_case(
    run_dir: Path, case: str, season: str, n_reals: int, noptmax: int
) -> dict[str, object]:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    bounds = pd.read_csv(
        ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / f"{BOUNDS_ID}.csv",
        encoding="utf-8-sig",
    )
    transforms = json.loads((run_dir / f"{case}.observation_transforms.json").read_text(encoding="utf-8"))
    active = pst.observation_data.loc[pst.observation_data["weight"] > 0, "obsnme"].astype(str).str.upper()
    problems: list[str] = []
    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"NOPTMAX must be {noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append("IES realization count does not match launch request")
    if float(pst.pestpp_options.get("ies_bad_phi_sigma", 0.0)) < 1e299:
        problems.append("automatic relative-Phi culling must be disabled")
    if set(registry["season_id"].astype(str)) != {season}:
        problems.append(f"observation registry must contain only {season}")
    if active.str.contains("PWAD|PWAI|HWAM").any():
        problems.append("legacy PWAD/PWAI/HWAM entered the active objective")
    for token in ("CHFPW", "CHPDT"):
        if not active.str.contains(token).any():
            problems.append(f"{token} has no active direct-harvest observations")
    harvest = transforms.get("files", {}).get("PestHarvest.OUT", {})
    for token in ("CHFPWS", "CHPDTS"):
        if harvest.get(token) != {"transform": "log", "offset": 1.0, "reference": 1.0}:
            problems.append(f"{token} must use ln(y+1)")
    expected_active = int(bounds["status"].astype(str).str.lower().eq("active").sum())
    if pst.npar_adj != expected_active:
        problems.append(f"expected {expected_active} adjustable parameters, got {pst.npar_adj}")
    if any(str(name).upper().endswith("_AUT") for name in pst.parameter_data.index):
        problems.append("single-season diagnostic must not contain autumn offset parameters")
    for key, value in IES_STABILITY_PROFILE.items():
        if str(pst.pestpp_options.get(key)).strip().lower() != str(value).strip().lower():
            problems.append(f"IES stability option {key} differs from comparator profile")
    if problems:
        raise RuntimeError("single-season diagnostic preflight failed: " + "; ".join(problems))
    return {
        "status": "built",
        "diagnostic_only": True,
        "season": season,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "bounds_id": BOUNDS_ID,
        "objective": "direct CHFPW+CHPDT; ln(y+1) once; no PWAD/PWAI/HWAM",
        "interpretation": "compare single-season conditional posteriors; do not report either as a final cultivar parameter set",
    }


def _build_and_run(
    *, season: str, run_id: str, n_reals: int, noptmax: int,
    n_agents: int, seed: int, build_only: bool,
) -> Path:
    design = CASES[season]
    run_dir = ROOT / "workspace" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    batch = ROOT / "data" / "user" / "experiments" / (
        "xxql2501_20260716" if season == "25SP" else "xxql2502_actual_trial_calibration_v1_20260721"
    ) / "DSSBatch.v48"
    _run([
        sys.executable, str(ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(design),
        "--input-dir", str(batch.parent), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", run_id, "--noptmax", str(noptmax), "--ies-num-reals", str(n_reals),
        "--random-seed", str(seed), "--bad-phi-sigma", "1e300",
        "--batch", str(batch), "--harvest-var", "CHPDT", "--include-n-uptake",
        "--out-dir", str(run_dir), "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
    ])
    _apply_stability_profile(run_dir, run_id)
    receipt = _verify_case(run_dir, run_id, season, n_reals, noptmax)
    receipt.update({"run_id": run_id, "run_dir": str(run_dir), "design": str(design), "random_seed": seed})
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {receipt_path}")
    if build_only:
        return run_dir
    _run([
        sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(run_dir), "--case", run_id, "--mode", "ies",
        "--n-agents", str(n_agents), "--wait",
    ])
    status_path = run_dir / "run_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(
            f"{season} diagnostic engineering gate failed: "
            + str(status.get("engineering_status_error") or status.get("engineering_status"))
        )
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{season} diagnostic calibration completed: {run_dir}")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Matched 25SP/25FA single-season T10 diagnostics")
    parser.add_argument("--season", choices=["25SP", "25FA", "both"], default="both")
    parser.add_argument("--run-prefix", default=None)
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=4, choices=[1, 4])
    parser.add_argument("--random-seed", type=int, default=20260723)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument(
        "--smoke", action="store_true",
        help="run a 20-member, one-update interface smoke; formal defaults remain 200 members/four updates",
    )
    args = parser.parse_args(argv)
    if args.smoke:
        args.n_reals = 20
        args.noptmax = 1
    if args.n_agents < 1 or args.n_reals < 20:
        raise ValueError("require n_agents>=1 and n_reals>=20")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.run_prefix or f"eggplant_t10_single_season_diag_{stamp}"
    seasons = [args.season] if args.season != "both" else ["25SP", "25FA"]
    for season in seasons:
        # Deliberately sequential: two 8-agent managers would compete for the
        # same local DSSAT installation and make seasonal failure rates unequal.
        _build_and_run(
            season=season,
            run_id=f"{prefix}_{season.lower()}",
            n_reals=args.n_reals,
            noptmax=args.noptmax,
            n_agents=args.n_agents,
            seed=args.random_seed,
            build_only=args.build_only,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
