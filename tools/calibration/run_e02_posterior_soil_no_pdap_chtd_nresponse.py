"""Rerun E02 from the posterior-soil bounds without PDAP, CHTD or NRESP in Phi."""

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
SOURCE_DESIGN = ROOT / "workspace/runs/e02_joint62_posterior_soil_100x4_20260802/runtime_multiseason_design.json"
POLICY = ROOT / "configs/runs/e02_posterior_soil_no_pdap_chtd_nresponse_v1.csv"
BOUNDS_ID = "eggplant_e02_posterior_soil_v3_20260802"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_runtime_design(run_dir: Path) -> Path:
    payload = json.loads(SOURCE_DESIGN.read_text(encoding="utf-8"))
    payload["design_id"] = "eggplant_e02_joint62_posterior_soil_no_pdap_chtd_nresponse_v1_20260802"
    payload["observation_policy"] = str(POLICY.relative_to(ROOT)).replace("\\", "/")
    payload["nitrogen_response_objective"] = {
        "enabled": False,
        "reason": "Three-season NRESP retained only for diagnostics; excluded from Phi by request",
    }
    payload["t10_scheme"] = {
        **payload.get("t10_scheme", {}),
        "response_shape": "disabled",
        "nitrogen_response_budget": 0.0,
    }
    path = run_dir / "runtime_multiseason_design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def verify(run_dir: Path, case: str, n_reals: int, noptmax: int, design: Path) -> dict:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    active = registry.loc[pd.to_numeric(registry["weight"], errors="coerce") > 0].copy()
    groups = active["obgnme"].astype(str).str.upper()
    forbidden = active.loc[groups.str.contains(r"PDAP|CHTD|NRESP", regex=True), "obgnme"].tolist()
    problems: list[str] = []
    if pst.npar_adj != 99:
        problems.append(f"expected 99 adjustable terms; found {pst.npar_adj}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append("noptmax mismatch")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append("ies_num_reals mismatch")
    if forbidden:
        problems.append(f"forbidden groups entered Phi: {forbidden[:5]}")
    if not active.empty and groups.str.contains("ADAP", regex=False).any():
        problems.append("ADAP entered Phi")
    if problems:
        raise RuntimeError("no-PDAP/CHTD/NRESP preflight failed: " + "; ".join(problems))
    diagnostic = registry.loc[
        registry["obgnme"].astype(str).str.upper().str.contains(r"PDAP|CHTD|NRESP", regex=True)
    ]
    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "design": str(design),
        "bounds_id": BOUNDS_ID,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_registry": int(len(registry)),
        "n_observations_active": int(len(active)),
        "n_removed_from_phi": int(len(diagnostic.loc[pd.to_numeric(diagnostic["weight"], errors="coerce") <= 0])),
        "n_pdap_chtd_nresp_active": 0,
        "n_reals": n_reals,
        "noptmax": noptmax,
        "nitrogen_response_in_phi": False,
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
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    case = args.run_id or (
        f"e02_joint62_posterior_soil_no_pdap_chtd_nresponse_"
        f"{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    run_dir = ROOT / "workspace/runs" / case
    if run_dir.exists():
        raise FileExistsError(run_dir)
    run_dir.mkdir(parents=True)
    design = build_runtime_design(run_dir)
    run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(design),
        "--input-dir", str(INPUT_DIR.resolve()),
        "--bounds-id", args.bounds_id,
        "--bounds-crop", "eggplant",
        "--prefix", case,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str((INPUT_DIR / "DSSBatch.v48").resolve()),
        "--harvest-var", "CHPDT",
        "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY.resolve()),
    ])
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    pst.pestpp_options.update({
        "ies_use_approx": False,
        "ies_lambda_mults": "0.5,1.0,10.0",
        "lambda_scale_fac": "0.9,1.0",
        "ies_enforce_bounds": True,
    })
    pst.write(str(run_dir / f"{case}.pst"))
    receipt = verify(run_dir, case, args.n_reals, args.noptmax, design)
    receipt["bounds_id"] = args.bounds_id
    receipt["policy"] = str(POLICY)
    receipt["source_posterior_run"] = "e02_joint62_posterior_soil_100x4_20260802"
    receipt["source_posterior_bounds_sha256"] = sha256(
        ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{args.bounds_id}.csv"
    )
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        raise RuntimeError(status.get("engineering_status_error") or str(status.get("engineering_status")))
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
