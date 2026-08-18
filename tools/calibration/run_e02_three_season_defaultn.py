"""Run the special three-season E02 calibration with default FileX mineral N."""

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
DESIGN = ROOT / "configs/runs/eggplant_e02_joint62_three_season_defaultn_v1_20260730.json"
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_v2.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_n_response_group_policy_harvestdry250_v2.csv"
BOUNDS_ID = "eggplant_e02_joint62_v6_touchrelax_slpf096_20260729"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_special_defaultn_v1_20260730"
OFFSET_NAMES = {
    "DLFMAX_AUT", "DSLAVR_AUT", "DXFRT_AUT", "DSFDUR_AUT",
    "DTB1_AUT", "DTB2_AUT", "DTB3_AUT",
}
EXPECTED_SEASONS = {"25SP", "25FA", "26SP"}
IES_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
}


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def apply_ies_profile(run_dir: Path, case: str) -> None:
    path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(path))
    pst.pestpp_options.update(IES_PROFILE)
    pst.write(str(path))


def verify_default_n_bundles() -> dict[str, dict]:
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    summaries: dict[str, dict] = {}
    problems: list[str] = []
    for season in design["seasons"]:
        season_id = str(season["season_id"])
        bundle = ROOT / str(season["bundle_path"])
        manifest = json.loads((bundle / "input_manifest.json").read_text(encoding="utf-8"))
        audit = manifest.get("initial_mineral_n_audit") or {}
        if float(audit.get("SNO3", -1)) != 1.0 or float(audit.get("SNH4", -1)) != 0.5:
            problems.append(f"{season_id}: manifest does not declare SNO3=1 and SNH4=0.5")
        rows = audit.get("rows") or []
        if not rows:
            problems.append(f"{season_id}: initial mineral-N row audit is empty")
        for row in rows:
            if float(row["new_sno3"]) != 1.0 or float(row["new_snh4"]) != 0.5:
                problems.append(f"{season_id}: non-default N row found in manifest audit")
                break
        summaries[season_id] = {
            "bundle": str(bundle),
            "manifest_sha256": str(season["bundle_manifest_sha256"]),
            "rows_changed": int(audit.get("row_count", 0)),
            "ic_count": int(audit.get("ic_count", 0)),
            "depths_cm": audit.get("depths_cm", []),
        }
    if problems:
        raise RuntimeError("Default-N bundle preflight failed: " + "; ".join(problems))
    return summaries


def verify(run_dir: Path, case: str, n_reals: int, noptmax: int) -> dict:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(
        run_dir / f"{case}_observation_registry.csv",
        encoding="utf-8-sig",
    )
    bounds = pd.read_csv(
        ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv",
        encoding="utf-8-sig",
    )
    groups = pd.read_csv(GROUP_POLICY, encoding="utf-8-sig")
    problems: list[str] = []
    if pst.npar_adj != 62 or int(bounds["status"].astype(str).str.lower().eq("active").sum()) != 62:
        problems.append(f"expected 62 adjustable terms; PST={pst.npar_adj}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"expected noptmax={noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append(f"expected ies_num_reals={n_reals}")
    if not OFFSET_NAMES <= {str(x).upper() for x in pst.parameter_data.index}:
        problems.append("seasonal offsets missing")
    active = registry.loc[pd.to_numeric(registry["weight"], errors="coerce") > 0]
    if len(active) != int(pst.nnz_obs):
        problems.append(f"registry/PST active observation mismatch: {len(active)} != {pst.nnz_obs}")
    season_ids = set(active["season_id"].astype(str).unique())
    if season_ids != EXPECTED_SEASONS:
        problems.append(f"expected active seasons {sorted(EXPECTED_SEASONS)}, found {sorted(season_ids)}")
    adap = registry.loc[registry["obgnme"].astype(str).str.upper().str.contains("ADAPM")]
    if not adap.empty and (pd.to_numeric(adap["weight"], errors="coerce") > 0).any():
        problems.append("ADAP entered Phi despite the permanent diagnostic-only invariant")
    dry_budget = groups.loc[groups["group"].eq("HARVEST_DRY"), "phi_budget"]
    if len(dry_budget) != 1 or float(dry_budget.iloc[0]) != 2.5:
        problems.append("HARVEST_DRY budget must be 2.5")
    slpf = bounds.loc[bounds["name"].eq("SOIL_SLPF")].iloc[0]
    if (float(slpf["lower"]), float(slpf["upper"])) != (0.9, 0.96):
        problems.append("SOIL_SLPF bounds must be 0.90-0.96")
    bundles = verify_default_n_bundles()
    if problems:
        raise RuntimeError("E02 three-season default-N preflight failed: " + "; ".join(problems))
    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "design": str(DESIGN),
        "bounds_id": BOUNDS_ID,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "active_seasons": sorted(season_ids),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "adap_role": "diagnostic_only",
        "harvest_dry_budget": 2.5,
        "soil_slpf_bounds": [0.9, 0.96],
        "filex_initial_mineral_n": {"SNO3": 1.0, "SNH4": 0.5},
        "input_bundles": bundles,
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=150)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260730)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id or f"e02_joint62_three_season_defaultn_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = ROOT / "workspace/runs" / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)
    verify_default_n_bundles()
    run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(DESIGN),
        "--input-dir", str(INPUT_DIR),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", run_id,
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
    apply_ies_profile(run_dir, run_id)
    receipt = verify(run_dir, run_id, args.n_reals, args.noptmax)
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
        "--run-dir", str(run_dir), "--case", run_id, "--mode", "ies",
        "--n-agents", str(args.n_agents), "--wait",
    ])
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(status.get("engineering_status_error") or status.get("engineering_status"))
    run([
        sys.executable, "-m", "src.reporting.export_seasonal_parameters",
        "--run-dir", str(run_dir), "--prefix", run_id, "--design", str(DESIGN),
    ])
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
