"""Run the 25SP+26SP four-corner-treatment calibration."""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_e02_spring_pair_histbest_v1_20260730.json"
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_v3.csv"
BOUNDS_ID = "eggplant_e02_spring_pair_histbest_rtn_relax_20260730"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"

def run(cmd: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--n-reals", type=int, default=150)
    ap.add_argument("--noptmax", type=int, default=5)
    ap.add_argument("--n-agents", type=int, default=6)
    ap.add_argument("--random-seed", type=int, default=20260730)
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    case = a.run_id or f"e02_spring_pair_histbest_4corner_{a.n_reals}x{a.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = ROOT / "workspace/runs" / case
    if run_dir.exists(): raise FileExistsError(run_dir)
    run_dir.mkdir(parents=True)
    runtime = run_dir / "runtime_multiseason_design.json"
    runtime.write_text(DESIGN.read_text(encoding="utf-8"), encoding="utf-8")
    run([sys.executable, str(ROOT / "src/calibration/build_pest.py"),
         "--mode", "eggplant_stage2", "--multiseason-design", str(runtime),
         "--input-dir", str(INPUT_DIR), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
         "--prefix", case, "--noptmax", str(a.noptmax), "--ies-num-reals", str(a.n_reals),
         "--random-seed", str(a.random_seed), "--bad-phi-sigma", "1e300",
         "--batch", str(INPUT_DIR / "DSSBatch.v48"), "--harvest-var", "CHPDT",
         "--include-n-uptake", "--out-dir", str(run_dir), "--param-review-mode", "off",
         "--observation-policy-csv", str(POLICY)])
    pst_path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.pestpp_options.update({"ies_use_approx": False, "ies_lambda_mults": "0.5,1.0,10.0", "lambda_scale_fac": "0.9,1.0", "ies_enforce_bounds": True})
    pst.write(str(pst_path))
    reg = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    active = reg[pd.to_numeric(reg["weight"], errors="coerce") > 0]
    family = active["variable_family"] if "variable_family" in active.columns else active["obgnme"]
    response = active[family.astype(str).str.contains("N_RESPONSE|NRESP", case=False, regex=True)]
    if pst.npar_adj != 55: raise RuntimeError(f"expected 55 adjustable parameters, got {pst.npar_adj}")
    if len(response) == 0: raise RuntimeError("no active N_RESPONSE observations")
    receipt = {"run_id": case, "run_dir": str(run_dir), "design": str(DESIGN), "bounds_id": BOUNDS_ID, "n_parameters_adjustable": int(pst.npar_adj), "n_observations_active": int(pst.nnz_obs), "n_response_observations": int(len(response)), "selected_treatments": {"25SP": [13,10,5,2], "26SP": [12,3,9,1]}, "n_reals": a.n_reals, "noptmax": a.noptmax, "status": "built"}
    (run_dir / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {run_dir / 'formal_launch_receipt.json'}")
    if not a.execute: return 0
    run([sys.executable, str(ROOT / "tools/parallel/run_parallel.py"), "--run-dir", str(run_dir), "--case", case, "--mode", "ies", "--n-agents", str(a.n_agents), "--wait"])
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("engineering_status") != "engineering_validated": raise RuntimeError(status.get("engineering_status_error") or status.get("engineering_status"))
    receipt["status"] = "engineering_validated"
    (run_dir / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
