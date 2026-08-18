"""Build and optionally execute the canonical three-season default-N case."""

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
DESIGN = ROOT / "configs/runs/eggplant_e02_joint62_three_season_defaultn_nresponse_v2_20260730.json"
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_v3.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv"
BOUNDS_ID = "eggplant_e02_joint62_defaultn_replan_v1_20260730"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_special_defaultn_v1_20260730"
EXPECTED_MANIFESTS = {
    "25SP": "8d6de7989de08ea6741603e9b333e4d2bfab322290fcd3ff05e2763c5b376c4f",
    "25FA": "8c923317a26b5c70662498145bd55a41c5b0d3ec8997d9e915906c012740852d",
    "26SP": "a6e065ab82b4ccb7a43ab1b05f124c7fb535cc2c30fcfd4e9608b394b20f88f1",
}


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def verify(run_dir: Path, case: str, n_reals: int, noptmax: int) -> dict:
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
    design = json.loads((run_dir / "runtime_multiseason_design.json").read_text(encoding="utf-8"))
    default_n_audit: dict[str, dict] = {}
    for season in design["seasons"]:
        season_id = str(season["season_id"])
        bundle = ROOT / str(season["bundle_path"])
        manifest_path = bundle / "input_manifest.json"
        import hashlib
        actual_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if actual_hash != EXPECTED_MANIFESTS[season_id]:
            problems.append(f"{season_id} manifest hash mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mineral_n = manifest.get("initial_mineral_n_audit") or {}
        if float(mineral_n.get("SNO3", -1)) != 1.0 or float(mineral_n.get("SNH4", -1)) != 0.5:
            problems.append(f"{season_id} is not the canonical SNO3=1/SNH4=0.5 bundle")
        default_n_audit[season_id] = {
            "bundle": str(bundle),
            "manifest_sha256": actual_hash,
            "row_count": int(mineral_n.get("row_count", 0)),
            "ic_count": int(mineral_n.get("ic_count", 0)),
        }
    if pst.npar_adj != 62:
        problems.append(f"expected 62 adjustable terms; found {pst.npar_adj}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append("noptmax mismatch")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append("ies_num_reals mismatch")
    if len(response) != 114:
        problems.append(f"expected 114 N-response contrasts; found {len(response)}")
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
        raise RuntimeError("default-N replan preflight failed: " + "; ".join(problems))
    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "design": str(DESIGN),
        "bounds_id": BOUNDS_ID,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "n_response_observations": int(len(response)),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "harvest_budget_total": 2.5,
        "absolute_harvest_budget": 1.75,
        "nitrogen_response_budget": 0.75,
        "filex_initial_mineral_n": {"SNO3": 1.0, "SNH4": 0.5},
        "input_bundles": default_n_audit,
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=150)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260730)
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
        f"e02_joint62_three_season_defaultn_replan_{target_tag}_"
        f"{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    run_dir = ROOT / "workspace/runs" / case
    if run_dir.exists():
        raise FileExistsError(run_dir)
    design_payload = json.loads(DESIGN.read_text(encoding="utf-8"))
    design_payload["design_id"] = (
        "eggplant_e02_joint62_three_season_defaultn_nresponse_"
        f"{target_tag}_v2_20260730"
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
        "--input-dir", str(INPUT_DIR),
        "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant",
        "--prefix", case,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(INPUT_DIR / "DSSBatch.v48"),
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
    receipt = verify(run_dir, case, args.n_reals, args.noptmax)
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
