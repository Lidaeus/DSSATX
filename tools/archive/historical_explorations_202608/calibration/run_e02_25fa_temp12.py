"""Run a 25FA-only 12-temperature-parameter conditional E02 calibration."""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DESIGN = ROOT / "workspace/runs/e02_joint62_posterior_soil_wnresponse_200x5_20260802/runtime_multiseason_design.json"
POLICY = ROOT / "configs/runs/e02_posterior_soil_no_pdap_chtd_nresponse_v1.csv"
BOUNDS_ID = "eggplant_e02_25fa_temp12_from_wnresponse200x5_20260802"
BUNDLE = ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"

def run(cmd):
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--n-reals", type=int, default=100)
    ap.add_argument("--noptmax", type=int, default=4)
    ap.add_argument("--n-agents", type=int, default=6)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    case = args.run_id or f"e02_25fa_temp12_{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    out = ROOT / "workspace/runs" / case
    if out.exists(): raise FileExistsError(out)
    out.mkdir(parents=True)
    payload = json.loads(SOURCE_DESIGN.read_text(encoding="utf-8"))
    season = next(s for s in payload["seasons"] if s["season_id"] == "25FA")
    season["bundle_path"] = str(BUNDLE.relative_to(ROOT)).replace("\\", "/")
    payload["seasons"] = [season]
    payload["diagnostic_single_season"] = True
    payload["seasonal_parameterization"] = None
    payload["design_id"] = "eggplant_e02_25fa_temp12_v1_20260802"
    payload["observation_policy"] = str(POLICY.relative_to(ROOT)).replace("\\", "/")
    payload["nitrogen_response_objective"] = {"enabled": False, "reason": "NRESP excluded from Phi"}
    payload["t10_scheme"] = {"purpose": "25FA-only conditional 12-temperature calibration", "active_parameters_target": 12}
    design = out / "runtime_multiseason_design.json"
    design.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run([sys.executable, str(ROOT/"src/calibration/build_pest.py"), "--mode", "eggplant_stage2", "--multiseason-design", str(design), "--input-dir", str(BUNDLE), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant", "--prefix", case, "--noptmax", str(args.noptmax), "--ies-num-reals", str(args.n_reals), "--random-seed", "20260802", "--bad-phi-sigma", "1e300", "--batch", str(BUNDLE/"DSSBatch.v48"), "--harvest-var", "CHPDT", "--include-n-uptake", "--out-dir", str(out), "--param-review-mode", "off", "--observation-policy-csv", str(POLICY)])
    pst = pyemu.Pst(str(out/f"{case}.pst"))
    pst.pestpp_options.update({"ies_use_approx":False,"ies_lambda_mults":"0.5,1.0,10.0","lambda_scale_fac":"0.9,1.0","ies_enforce_bounds":True})
    pst.write(str(out/f"{case}.pst"))
    reg = pd.read_csv(out/f"{case}_observation_registry.csv", encoding="utf-8-sig")
    active = reg[pd.to_numeric(reg.weight, errors="coerce") > 0]
    if pst.npar_adj != 12 or len(active) == 0 or active.obgnme.astype(str).str.contains("PDAP|CHTD|NRESP", case=False, regex=True).any():
        raise RuntimeError(f"preflight failed: npar={pst.npar_adj}, active_obs={len(active)}")
    receipt={"run_id":case,"bounds_id":BOUNDS_ID,"n_parameters_adjustable":int(pst.npar_adj),"n_observations_active":int(len(active)),"n_reals":args.n_reals,"noptmax":args.noptmax,"temperature_parameters":sorted(["TB1","TB2","TB3","TM1","TM2","TM3","TO11","TO12","TO13","TO21","TO22","TO23"]),"status":"built"}
    (out/"formal_launch_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Preflight passed")
    if not args.execute: return 0
    run([sys.executable,str(ROOT/"tools/parallel/run_parallel.py"),"--run-dir",str(out),"--case",case,"--mode","ies","--n-agents",str(args.n_agents),"--wait"])
    status=json.loads((out/"run_status.json").read_text(encoding="utf-8"))
    if status.get("engineering_status") != "engineering_validated": raise RuntimeError(status.get("engineering_status_error") or status)
    receipt["status"]="engineering_validated"
    (out/"formal_launch_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__": main()
