"""Build, preflight and optionally execute the E02 V2 no-SOIL_WATER rerun."""
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
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_formal25sp_nosoilwater_20260802.json"
POLICY = ROOT / "configs/runs/e02_v2_canopy_yield_nresponse_nosoilwater_policy_20260802.csv"
BOUNDS = "eggplant_e02_v2_formal25sp_nosoilwater_20260802"
BATCH = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/DSSBatch.v48"


def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--n-reals", type=int, default=200)
    ap.add_argument("--noptmax", type=int, default=5)
    ap.add_argument("--n-agents", type=int, default=6)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    case = args.run_id or f"e02_v2_formal25sp_nosoilwater_{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    out = ROOT / "workspace/runs" / case
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(BATCH.parent), "--bounds-id", BOUNDS, "--bounds-crop", "eggplant",
        "--prefix", case, "--noptmax", str(args.noptmax), "--ies-num-reals", str(args.n_reals),
        "--random-seed", "20260802", "--bad-phi-sigma", "1e300", "--batch", str(BATCH),
        "--harvest-var", "CHPDT", "--include-n-uptake", "--include-soil", "--out-dir", str(out),
        "--param-review-mode", "off", "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol",
    ])
    pst = pyemu.Pst(str(out / f"{case}.pst"))
    registry = pd.read_csv(out / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    active = registry[pd.to_numeric(registry["weight"], errors="coerce") > 0]
    groups = active["obgnme"].astype(str)
    soil = active[groups.str.contains("SOIL_WATER", case=False, regex=True)]
    nresp = int(groups.str.contains("NRESP", case=False, regex=True).sum())
    bad = int(groups.str.contains("PDAP|ADAP|MDAP|CHTD|PHENO", case=False, regex=True).sum())
    seasons = set(active["season_id"].astype(str))
    if pst.npar_adj < 90 or nresp == 0 or len(soil) or bad or seasons != {"25SP"}:
        raise RuntimeError(f"preflight failed npar={pst.npar_adj}, active_obs={len(active)}, nresp={nresp}, soil_water={len(soil)}, bad={bad}, seasons={seasons}")
    receipt = {
        "run_id": case, "design": str(DESIGN), "bounds_id": BOUNDS,
        "seasons": ["25SP"], "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(len(active)), "n_nresp_active": nresp,
        "n_soil_water_active": int(len(soil)), "n_reals": args.n_reals,
        "noptmax": args.noptmax, "initial_ensemble_method": "sobol", "status": "built",
    }
    (out / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Preflight passed:", json.dumps(receipt, ensure_ascii=False))
    if args.execute:
        run([sys.executable, str(ROOT / "tools/parallel/run_parallel.py"), "--run-dir", str(out), "--case", case, "--mode", "ies", "--n-agents", str(args.n_agents), "--wait"])
        status = json.loads((out / "run_status.json").read_text())
        receipt["status"] = status.get("engineering_status", status.get("status"))
        (out / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
