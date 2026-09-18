"""Build and launch the approved T8 two-season PEST-IES calibration.

No arguments are required for the formal run.  XXQL2501 and XXQL2502 share
one genetic-parameter ensemble; XXQL2601 remains sealed for later validation.
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
DESIGN = ROOT / "configs" / "runs" / "eggplant_t8_joint_25sp_25fa_v1.json"
POLICY = ROOT / "configs" / "runs" / "assumption_based_sigma_v2.csv"
BOUNDS_ID = "eggplant_t7_formal_v5_20260721"


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _verify_case(run_dir: Path, case: str, n_reals: int) -> dict[str, object]:
    pst_path = run_dir / f"{case}.pst"
    registry_path = run_dir / f"{case}_observation_registry.csv"
    run_map_path = run_dir / f"{case}_run_mapping.csv"
    audit_path = run_dir / f"{case}.weights.audit.csv"
    pst = pyemu.Pst(str(pst_path))
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    run_map = pd.read_csv(run_map_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    problems: list[str] = []
    if int(pst.control_data.noptmax) < 0:
        problems.append("NOPTMAX must not be negative")
    if len(run_map) != 16 or set(run_map["season_id"]) != {"25SP", "25FA"}:
        problems.append("run mapping must contain 16 runs from 25SP and 25FA")
    if registry["season_id"].isna().any() or len(registry) != len(pst.observation_data):
        problems.append("observation registry is incomplete")
    obs_names = pst.observation_data["obsnme"].astype(str).str.lower()
    if not obs_names.str.startswith(("25sp_", "25fa_")).all():
        problems.append("observation names must be explicitly season-scoped")
    if "phi_role" not in audit or ((audit["phi_role"] != "calibration") & (audit["weight"] > 0)).any():
        problems.append("diagnostic/sensitivity observations must have zero weight")
    if float(pst.pestpp_options.get("ies_bad_phi_sigma", 0)) < 1.0e299:
        problems.append("formal case must disable automatic relative-Phi culling")
    obs_ensemble = str(pst.pestpp_options.get("ies_observation_ensemble", ""))
    if not obs_ensemble or not (run_dir / obs_ensemble).is_file():
        problems.append("explicit observation-noise ensemble is missing")
    if pst.nnz_obs <= 0:
        problems.append("case contains no active calibration observations")
    if problems:
        raise RuntimeError("formal preflight failed: " + "; ".join(problems))
    return {
        "pst": str(pst_path),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_total": int(len(pst.observation_data)),
        "n_observations_active": int(pst.nnz_obs),
        "n_reals": int(n_reals),
        "noptmax": int(pst.control_data.noptmax),
        "bad_phi_sigma": float(pst.pestpp_options["ies_bad_phi_sigma"]),
        "observation_ensemble": obs_ensemble,
        "calibration_seasons": ["25SP", "25FA"],
        "sealed_validation_season": "26SP",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-command T8 formal joint calibration")
    parser.add_argument("--run-id", help="default: timestamped formal run ID")
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--n-reals", type=int, default=240)
    parser.add_argument("--noptmax", type=int, default=4)
    parser.add_argument("--random-seed", type=int, default=20260729)
    parser.add_argument("--build-only", action="store_true", help="build and preflight without starting IES")
    args = parser.parse_args(argv)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = args.run_id or f"eggplant_t8_joint_formal_{stamp}"
    case = run_id
    run_dir = ROOT / "workspace" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    if args.n_agents < 1 or args.n_reals < 4 or args.noptmax < 0:
        raise ValueError("require n_agents>=1, n_reals>=4, and noptmax>=0")

    batch = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716" / "DSSBatch.v48"
    build = [
        sys.executable, str(ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(DESIGN),
        "--input-dir", str(batch.parent),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", case,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(batch),
        "--harvest-var", "CHPDT", "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "import",
        "--observation-policy-csv", str(POLICY),
    ]
    _run(build)
    receipt = _verify_case(run_dir, case, args.n_reals)
    receipt.update({
        "run_id": run_id,
        "run_dir": str(run_dir),
        "design": str(DESIGN),
        "bounds_id": BOUNDS_ID,
        "status": "built" if args.build_only else "launching",
    })
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {receipt_path}")
    if args.build_only:
        return 0

    _run([
        sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(run_dir), "--case", case,
        "--mode", "ies", "--n-agents", str(args.n_agents), "--wait",
    ])
    receipt["status"] = "pestpp_completed"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Formal calibration completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
