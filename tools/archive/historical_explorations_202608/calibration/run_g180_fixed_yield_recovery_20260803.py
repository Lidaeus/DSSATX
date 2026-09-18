#!/usr/bin/env python3
"""Build, smoke-test, and optionally run the G180-fixed 100x4 calibration."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_joint25sp26sp_nosoil_nresp_20260802.json"
POLICY = ROOT / "configs/runs/e02_v2_joint25sp26sp_nosoil_nresp_policy_20260802.csv"
BOUNDS = "eggplant_e02_g180_yield_recovery_v1_20260803"
INPUT = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
BATCH = INPUT / "DSSBatch.v48"
FIXED = ROOT / "workspace/diagnostics/g180_fixed_yield_recovery_20260803/g180_fixed.csv"
INIT = ROOT / "workspace/diagnostics/n_min_tissue_g140_extension_20260803/G180/parameters.csv"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def audit(out: Path, case: str) -> dict:
    pst = pyemu.Pst(str(out / f"{case}.pst"))
    registry = pd.read_csv(out / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    active = registry[pd.to_numeric(registry["weight"], errors="coerce") > 0]
    groups = active["obgnme"].astype(str).str.upper()
    soil = int(groups.str.contains(r"SOIL_WATER|^(?:25SP|26SP)_SW\d+M", regex=True).sum())
    nresp = int(groups.str.contains("NRESP", regex=True).sum())
    if pst.npar_adj != 29:
        raise RuntimeError(f"expected 29 adjustable parameters, got {pst.npar_adj}")
    if soil or nresp:
        raise RuntimeError(f"excluded objective rows active: soil={soil}, nresp={nresp}")
    if set(active["season_id"].astype(str)) != {"25SP", "26SP"}:
        raise RuntimeError("unexpected active seasons")
    return {
        "adjustable_parameters": int(pst.npar_adj),
        "total_parameters": int(len(pst.parameter_data)),
        "active_observations": int(len(active)),
        "soil_water_active": soil,
        "nresp_active": nresp,
        "seasons": sorted(set(active["season_id"].astype(str))),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="e02_g180_fixed_yield_recovery_100x4_20260803")
    ap.add_argument("--n-reals", type=int, default=100)
    ap.add_argument("--noptmax", type=int, default=4)
    ap.add_argument("--n-agents", type=int, default=4)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4020)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    out = ROOT / "workspace/runs" / args.run_id
    if out.exists() and args.execute and (out / f"{args.run_id}.pst").is_file():
        # Permit the safe two-step workflow: build/preflight first, then
        # launch the already-audited directory without rebuilding it.
        preflight = audit(out, args.run_id)
        print("Using existing preflight-passed run:", json.dumps(preflight, ensure_ascii=False))
    else:
        if out.exists():
            raise FileExistsError(out)
        out.mkdir(parents=True)
        cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(INPUT), "--bounds-id", BOUNDS, "--bounds-crop", "eggplant",
        "--prefix", args.run_id, "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals), "--random-seed", "20260803",
        "--bad-phi-sigma", "1e300", "--batch", str(BATCH), "--harvest-var", "CHPDT",
        "--include-n-uptake", "--out-dir", str(out), "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY), "--initial-ensemble-method", "sobol",
        "--init-from", str(INIT), "--fixed-from", str(FIXED),
        ]
        run(cmd)
        preflight = audit(out, args.run_id)
    receipt = {
        "run_id": args.run_id,
        "bounds_id": BOUNDS,
        "fixed_g180": str(FIXED),
        "initial_member": str(INIT),
        "design": str(DESIGN),
        "seasons": ["25SP", "26SP"],
        "n_reals": args.n_reals,
        "noptmax": args.noptmax,
        "initial_ensemble_method": "sobol",
        "manager_host": args.host,
        "manager_port": args.port,
        "status": "built",
        "preflight": preflight,
    }
    (out / "launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Preflight passed:", json.dumps(preflight, ensure_ascii=False))
    if not args.execute:
        return 0
    run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(out), "--case", args.run_id, "--mode", "ies",
        "--n-agents", str(args.n_agents), "--host", args.host, "--port", str(args.port), "--wait",
    ])
    status_path = out / "run_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    receipt["status"] = status.get("engineering_status", status.get("status"))
    receipt["run_status"] = status
    (out / "launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "engineering_validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
