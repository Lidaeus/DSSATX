"""Build, preflight, and launch the approved T10 joint calibration.

T10 is deliberately a small operational wrapper, not another calibration
framework.  It freezes the approved two-season, direct-harvest contract before
PEST++ starts: CHFPW/CHPDT only, one audited log transform, family-season Phi
budgets, no automatic bad-Phi culling, and 200 realizations over four updates.
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
DESIGN = ROOT / "configs" / "runs" / "eggplant_t10_joint_25sp_25fa_v1.json"
POLICY = ROOT / "configs" / "runs" / "assumption_based_sigma_v4.csv"
BOUNDS_ID = "eggplant_t10_m0_v1_20260722"


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _verify_case(run_dir: Path, case: str, n_reals: int) -> dict[str, object]:
    """Reject a build that is not the approved T10 scientific contract."""
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    weights = pd.read_csv(run_dir / f"{case}.weights.audit.csv", encoding="utf-8-sig")
    groups = pd.read_csv(run_dir / f"{case}_group_weight_audit.csv", encoding="utf-8-sig")
    bounds = pd.read_csv(
        ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / f"{BOUNDS_ID}.csv",
        encoding="utf-8-sig",
    )
    transform_path = run_dir / f"{case}.observation_transforms.json"
    problems: list[str] = []
    obs = pst.observation_data.copy()
    names = obs["obsnme"].astype(str).str.upper()
    active = obs.loc[pd.to_numeric(obs["weight"], errors="coerce") > 0].copy()
    active_names = active["obsnme"].astype(str).str.upper()
    if int(pst.control_data.noptmax) != 4:
        problems.append(f"T10 requires NOPTMAX=4, got {pst.control_data.noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != int(n_reals):
        problems.append("IES realization count does not match launch request")
    if float(pst.pestpp_options.get("ies_bad_phi_sigma", 0.0)) < 1e299:
        problems.append("formal T10 must disable automatic relative-Phi culling")
    if len(registry) != len(obs) or set(registry["season_id"]) != {"25SP", "25FA"}:
        problems.append("observation registry must contain both calibration seasons only")
    if names.str.contains("PWAD|PWAI|HWAM").any():
        problems.append("PWAD, PWAI, and HWAM must be absent from the T10 PST")
    for token in ("CHFPW", "CHPDT"):
        if not active_names.str.contains(token).any():
            problems.append(f"{token} has no active direct-harvest observations")
    if names.str.contains("LAIX").any() and active_names.str.contains("LAIX").any():
        problems.append("LAIX must remain diagnostic-only")
    if not transform_path.is_file():
        problems.append("audited observation transform configuration is missing")
    else:
        transform = json.loads(transform_path.read_text(encoding="utf-8"))
        harvest_tokens = transform.get("files", {}).get("PestHarvest.OUT", {})
        for token in ("CHFPWS", "CHPDTS"):
            spec = harvest_tokens.get(token)
            if spec != {"transform": "log", "offset": 1.0, "reference": 1.0}:
                problems.append(f"{token} must use exactly ln((y+1)/1)")
    active_weight_rows = weights.loc[pd.to_numeric(weights["weight"], errors="coerce") > 0]
    if ((active_weight_rows["phi_role"].astype(str) != "calibration")).any():
        problems.append("only calibration-role observations may have non-zero weight")
    expected_groups = {"25SP", "25FA"}
    if set(groups["season_id"].astype(str)) != expected_groups:
        problems.append("group-weight audit lacks a family-season allocation for a calibration season")
    if groups.duplicated(["season_id", "variable_family"]).any():
        problems.append("family-season budget was allocated more than once")
    expected_active = int(bounds["status"].astype(str).str.lower().eq("active").sum())
    if pst.npar_adj != expected_active:
        problems.append(f"frozen active parameter count is {expected_active}, PST has {pst.npar_adj}")
    xfpht = bounds.loc[bounds["name"].astype(str).str.upper().eq("XFPHT")]
    if len(xfpht) != 1 or float(xfpht.iloc[0]["lower"]) != 31.0 or float(xfpht.iloc[0]["upper"]) != 70.0:
        problems.append("XFPHT frozen bounds must be 31-70")
    xfint = bounds.loc[bounds["name"].astype(str).str.upper().eq("XFINT")]
    if len(xfint) != 1 or float(xfint.iloc[0]["lower"]) != 0.08 or float(xfint.iloc[0]["upper"]) != 0.50:
        problems.append("XFINT frozen bounds must be 0.08-0.50")
    command = " ".join(pst.model_command)
    if "--observation-transform-config" not in command:
        problems.append("multi-season model command dropped the transform configuration")
    if problems:
        raise RuntimeError("T10 formal preflight failed: " + "; ".join(problems))
    return {
        "pst": str(run_dir / f"{case}.pst"),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_total": int(len(obs)),
        "n_observations_active": int(pst.nnz_obs),
        "n_reals": int(n_reals),
        "noptmax": int(pst.control_data.noptmax),
        "calibration_seasons": ["25SP", "25FA"],
        "sealed_validation_season": "26SP",
        "harvest_contract": "direct CHFPW+CHPDT, log once after raw tagged output",
        "xfint_policy": "frozen bounds 0.08-0.50; historical 0.12-0.50 interval is advisory only",
        "model_failure_policy": "DSSAT model_failed members are never high-Phi-screened; Phi-missing fraction must not exceed 0.02 and final retention must meet the engineering gate",
        "status": "built",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-command approved T10 joint calibration")
    parser.add_argument("--run-id", help="default: timestamped T10 formal run ID")
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=4, choices=[4])
    parser.add_argument("--random-seed", type=int, default=20260722)
    parser.add_argument("--build-only", action="store_true", help="build and preflight without launching PEST++")
    args = parser.parse_args(argv)
    if args.n_agents < 1 or args.n_reals < 20:
        raise ValueError("require n_agents>=1 and n_reals>=20 for a formal T10 run")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = args.run_id or f"eggplant_t10_joint_{stamp}"
    run_dir = ROOT / "workspace" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    batch = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716" / "DSSBatch.v48"
    _run([
        sys.executable, str(ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(batch.parent), "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant", "--prefix", run_id,
        "--noptmax", "4", "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed), "--bad-phi-sigma", "1e300",
        "--batch", str(batch), "--harvest-var", "CHPDT", "--include-n-uptake",
        "--out-dir", str(run_dir), "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
    ])
    receipt = _verify_case(run_dir, run_id, args.n_reals)
    receipt.update({"run_id": run_id, "run_dir": str(run_dir), "bounds_id": BOUNDS_ID})
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
    if not status_path.is_file():
        raise RuntimeError("IES completed without run_status.json")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("status") != "completed":
        raise RuntimeError(f"IES did not complete: {status.get('status')!r}")
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(
            "T10 engineering gate failed: "
            + str(status.get("engineering_status_error") or status.get("engineering_status"))
        )
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Formal T10 calibration completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
