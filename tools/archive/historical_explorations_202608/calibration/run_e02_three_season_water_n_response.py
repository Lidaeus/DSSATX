"""Build and optionally execute the three-season water x N response case."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_e02_joint62_three_season_water_n_response_v1_20260730.json"
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_v3.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv"
BOUNDS_ID = "eggplant_e02_joint62_v7_nstfac050_rhght035_20260730"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(
    run_dir: Path,
    case: str,
    n_reals: int,
    noptmax: int,
    bounds_id: str,
    design_path: Path,
    expected_npar: int = 62,
    expected_response_obs: int = 114,
) -> dict:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(
        run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig"
    )
    audit = pd.read_csv(
        run_dir / f"{case}_group_weight_audit.csv", encoding="utf-8-sig"
    )
    active = registry.loc[
        pd.to_numeric(registry["weight"], errors="coerce") > 0
    ].copy()
    response = active.loc[
        active["variable_family"].astype(str).eq("N_RESPONSE")
    ] if "variable_family" in active else active.loc[
        active["obgnme"].astype(str).str.contains("NRESP", case=False)
    ]
    problems: list[str] = []
    if pst.npar_adj != expected_npar:
        problems.append(f"expected {expected_npar} adjustable terms; found {pst.npar_adj}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append("noptmax mismatch")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append("ies_num_reals mismatch")
    if len(response) != expected_response_obs:
        problems.append(
            f"expected {expected_response_obs} N-response contrasts; found {len(response)}"
        )
    response_audit = audit.loc[audit["variable_family"].eq("N_RESPONSE")]
    if len(response_audit) != 3:
        problems.append("N_RESPONSE must have one static budget bucket per season")
    elif not response_audit["phi_budget"].astype(float).eq(0.75).all():
        problems.append("N_RESPONSE budget must be 0.75 in every season")
    harvest_audit = audit.loc[audit["variable_family"].eq("HARVEST_DRY")]
    if not harvest_audit["phi_budget"].astype(float).eq(1.75).all():
        problems.append("HARVEST_DRY absolute budget must be 1.75")
    adap = active.loc[
        active["obgnme"].astype(str).str.contains("ADAP", case=False)
    ]
    if not adap.empty:
        problems.append("ADAP entered Phi")
    if problems:
        raise RuntimeError("water x N response preflight failed: " + "; ".join(problems))
    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "design": str(design_path),
        "bounds_id": bounds_id,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "n_response_observations": int(len(response)),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "harvest_budget_total": 2.5,
        "absolute_harvest_budget": 1.75,
        "nitrogen_response_budget": 0.75,
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=100)
    parser.add_argument("--noptmax", type=int, default=4)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260730)
    parser.add_argument("--bounds-id", default=BOUNDS_ID)
    parser.add_argument("--expected-npar", type=int, default=62)
    parser.add_argument("--expected-response-obs", type=int, default=114)
    parser.add_argument("--design", type=Path, default=DESIGN)
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument(
        "--response-target",
        choices=("observed_shape", "monotone_plateau"),
        default="observed_shape",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    target_tag = (
        "observedshape"
        if args.response_target == "observed_shape"
        else "noexcessn"
    )
    case = args.run_id or (
        f"e02_joint62_three_season_water_n_response_{target_tag}_"
        f"{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    run_dir = ROOT / "workspace/runs" / case
    if run_dir.exists():
        raise FileExistsError(run_dir)
    design_source = args.design.resolve()
    design_payload = json.loads(design_source.read_text(encoding="utf-8"))
    # Refresh bundle paths and hashes so the corrected 95%-moisture/5%-DMC
    # bundles are the actual inputs, not stale manifests from prior runs.
    active_bundles = {
        "25SP": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        "25FA": ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "26SP": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
    }
    for season in design_payload.get("seasons", []):
        sid = str(season.get("season_id", ""))
        bundle = active_bundles.get(sid)
        if bundle is not None:
            season["bundle_path"] = str(bundle.relative_to(ROOT))
            season["bundle_manifest_sha256"] = sha256(bundle / "input_manifest.json")
            season["role"] = "calibration"
    design_payload["design_id"] = (
        "eggplant_e02_joint62_three_season_water_n_response_"
        f"{target_tag}_v1_20260730"
    )
    design_payload["nitrogen_response_objective"][
        "response_target"
    ] = args.response_target
    runtime_design = run_dir / "runtime_multiseason_design.json"
    run_dir.mkdir(parents=True)
    runtime_design.write_text(
        json.dumps(design_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(runtime_design),
        "--input-dir", str(args.input_dir.resolve()),
        "--bounds-id", args.bounds_id,
        "--bounds-crop", "eggplant",
        "--prefix", case,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(args.input_dir.resolve() / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
    ])
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    pst.pestpp_options.update({
        "ies_use_approx": False,
        "ies_lambda_mults": "0.5,1.0,10.0",
        "lambda_scale_fac": "0.9,1.0",
        "ies_enforce_bounds": True,
    })
    pst.write(str(run_dir / f"{case}.pst"))
    receipt = verify(
        run_dir,
        case,
        args.n_reals,
        args.noptmax,
        args.bounds_id,
        runtime_design,
        expected_npar=args.expected_npar,
        expected_response_obs=args.expected_response_obs,
    )
    receipt["response_target"] = args.response_target
    receipt["design"] = str(runtime_design)
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Preflight passed: {receipt_path}")
    if not args.execute:
        return 0
    run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", case,
        "--mode", "ies", "--n-agents", str(args.n_agents), "--wait",
    ])
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(
            status.get("engineering_status_error")
            or str(status.get("engineering_status"))
        )
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
