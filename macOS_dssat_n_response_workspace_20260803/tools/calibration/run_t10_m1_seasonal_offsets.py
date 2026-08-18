"""Build and launch the approved shared-plus-autumn-offset T10 M1 case."""

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
DESIGN = ROOT / "configs" / "runs" / "eggplant_t10_m1_25sp_25fa_autumn_offsets_v1.json"
POLICY = ROOT / "configs" / "runs" / "assumption_based_sigma_v4.csv"
BOUNDS_ID = "eggplant_t10_m1_autumn_offsets_v1_20260723"
OFFSET_NAMES = {
    "DLFMAX_AUT", "DSLAVR_AUT", "DXFRT_AUT", "DSFDUR_AUT",
    "DTB1_AUT", "DTB2_AUT", "DTB3_AUT",
}

# M1 has 48 adjustable terms and a materially nonlinear DSSAT response.  The
# PEST++ defaults test an aggressive 0.1 x lambda and 0.75 line-search step.
# In the first M1 attempt, those *trial* updates caused native DSSAT crashes
# and PEST++ subsequently dropped their realizations.  Keep the approved
# parameter bounds and scientific objective unchanged; only make the numerical
# update search less aggressive and retain the full Bayesian-form IES update.
M1_IES_STABILITY_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
}


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _apply_stability_profile(run_dir: Path, case: str) -> None:
    """Persist the approved conservative IES numerical profile for M1.

    This is deliberately applied after the general builder has frozen the
    observation-noise and bad-Phi contracts.  It does not alter observations,
    weights, bounds, active parameters, or the seasonal-offset design.
    """
    pst_path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.pestpp_options.update(M1_IES_STABILITY_PROFILE)
    pst.write(str(pst_path))


def _verify_case(run_dir: Path, case: str, n_reals: int) -> dict[str, object]:
    """Reject a case whose scientific contract differs from approved M1."""
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    bounds = pd.read_csv(
        ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / f"{BOUNDS_ID}.csv",
        encoding="utf-8-sig",
    )
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    problems: list[str] = []
    parameter_names = {str(name).upper() for name in pst.parameter_data.index}
    if int(pst.control_data.noptmax) != 4:
        problems.append("T10 M1 requires noptmax=4")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append("IES realization count does not match launch request")
    if float(pst.pestpp_options.get("ies_bad_phi_sigma", 0.0)) < 1e299:
        problems.append("automatic relative-Phi culling must remain disabled")
    for option, expected in M1_IES_STABILITY_PROFILE.items():
        actual = pst.pestpp_options.get(option)
        if str(actual).strip().lower() != str(expected).strip().lower():
            problems.append(f"M1 IES stability option {option} is not {expected!r}")
    if parameter_names & {"PWAD", "PWAI", "HWAM"}:
        problems.append("PWAD, PWAI, and HWAM must not be calibration parameters")
    if not OFFSET_NAMES <= parameter_names:
        problems.append("PST is missing one or more approved autumn offsets")
    seasonal_group = pst.parameter_data.loc[
        pst.parameter_data.index.astype(str).str.upper().isin(OFFSET_NAMES), "pargp"
    ].astype(str).str.lower()
    if not seasonal_group.eq("seasonal_offset").all():
        problems.append("seasonal offsets must be isolated in pargp=seasonal_offset")
    expected_active = int(bounds["status"].astype(str).str.lower().eq("active").sum())
    if pst.npar_adj != expected_active:
        problems.append(f"frozen active parameter count is {expected_active}, PST has {pst.npar_adj}")
    tb = bounds.loc[bounds["name"].astype(str).str.upper().isin({"TB1", "TB2", "TB3"})]
    if len(tb) != 3 or not (tb["lower"].astype(float).eq(6.0) & tb["upper"].astype(float).eq(13.0)).all():
        problems.append("shared TB1/TB2/TB3 bounds must be 6-13 C")
    xfrt = bounds.loc[bounds["name"].astype(str).str.upper().eq("XFRT")]
    if len(xfrt) != 1 or float(xfrt.iloc[0]["upper"]) != 0.98:
        problems.append("XFRT shared upper bound must remain 0.98 for logit projection")
    if set(registry["season_id"].astype(str)) != {"25SP", "25FA"}:
        problems.append("calibration observation registry must contain 25SP and 25FA only")
    active_names = pst.observation_data.loc[pst.observation_data["weight"] > 0, "obsnme"].astype(str).str.upper()
    if any(active_names.str.contains(token).any() for token in ("PWAD", "PWAI", "HWAM")):
        problems.append("legacy harvest targets entered the active observation contract")
    if "--design" not in " ".join(pst.model_command):
        problems.append("PST model command lost the seasonal design")
    if problems:
        raise RuntimeError("T10 M1 formal preflight failed: " + "; ".join(problems))
    return {
        "pst": str(run_dir / f"{case}.pst"),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "n_reals": n_reals,
        "noptmax": 4,
        "calibration_seasons": ["25SP", "25FA"],
        "sealed_validation_season": "26SP",
        "seasonal_parameterization": {
            "reference": "25SP shared parameters",
            "autumn": "25FA = shared + declared offset on native transform scale",
            "offset_names": sorted(OFFSET_NAMES),
        },
        "status": "built",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-command T10 M1 seasonal-offset calibration")
    parser.add_argument("--run-id", help="default: timestamped T10 M1 run ID")
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=4, choices=[4])
    parser.add_argument("--random-seed", type=int, default=20260723)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args(argv)
    if args.n_agents < 1 or args.n_reals < 20:
        raise ValueError("require n_agents>=1 and n_reals>=20")
    run_id = args.run_id or f"eggplant_t10_m1_offsets_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = ROOT / "workspace" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    batch = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716" / "DSSBatch.v48"
    _run([
        sys.executable, str(ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(batch.parent), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", run_id, "--noptmax", "4", "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed), "--bad-phi-sigma", "1e300",
        "--batch", str(batch), "--harvest-var", "CHPDT", "--include-n-uptake",
        "--out-dir", str(run_dir), "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
    ])
    _apply_stability_profile(run_dir, run_id)
    receipt = _verify_case(run_dir, run_id, args.n_reals)
    receipt.update({"run_id": run_id, "run_dir": str(run_dir), "bounds_id": BOUNDS_ID, "design": str(DESIGN)})
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {receipt_path}")
    if args.build_only:
        return 0
    _run([
        sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(run_dir), "--case", run_id, "--mode", "ies",
        "--n-agents", str(args.n_agents), "--wait",
    ])
    status_path = run_dir / "run_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError("T10 M1 engineering gate failed: " + str(status.get("engineering_status_error") or status.get("engineering_status")))
    _run([
        sys.executable, "-m", "src.reporting.export_seasonal_parameters",
        "--run-dir", str(run_dir), "--prefix", run_id, "--design", str(DESIGN),
    ])
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Formal T10 M1 calibration completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
