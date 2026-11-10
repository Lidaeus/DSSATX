#!/usr/bin/env python3
"""Deterministic 3-season evaluation across 35 treatments for unconstrained 200x6 run:
Automatically ranks top realizations by objective function Phi, evaluating:
1. 25SP: 11 treatments (DSSBatch.v48)
2. 26SP: 12 treatments (DSSBatch_26SP_all.v48)
3. 25FA: 12 treatments (DSSBatch_25FA_all.v48)
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUN_DIR = PROJECT_ROOT / "workspace/runs/full_gen_sasc094_sldr024_200x6_20260919"
CASE = "full_gen_sasc094_sldr024_200x6"

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

def prepare_batches():
    b25 = PROJECT_ROOT / "data/templates/batch/DSSBatch.v48"
    
    b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
    for tn in range(1, 13):
        b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
    b26 = RUN_DIR / "DSSBatch_26SP_all.v48"
    b26.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")
    
    bfa_lines = ["$BATCH(SEASON)", "! 2025 Autumn all 12 treatments"]
    for tn in range(1, 13):
        bfa_lines.append(f"XXQL2502.TMX                                                                                    {tn:2d}      1      0      0      0")
    bfa = RUN_DIR / "DSSBatch_25FA_all.v48"
    bfa.write_text("\n".join(bfa_lines) + "\n", encoding="utf-8")
    
    return {"25SP": b25, "26SP": b26, "25FA": bfa}

def run_deterministic_season(p_row: pd.Series, season: str, batch_path: Path, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    
    param_df = pd.DataFrame({"name": p_row.index, "value": p_row.values})
    param_csv = out_dir / "params.csv"
    param_df.to_csv(param_csv, index=False)
    
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path)])
    
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(param_csv.resolve()),
        "--batch",
        batch_dest.name,
        "--harvest-var",
        "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print(f"Error in {out_dir}: {res.stderr[:500]}")
        return None
        
    df_h, df_eval = evaluate_run(batch_dest, out_dir)
    return df_h, df_eval

def calc_nse(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) < 2: return np.nan
    denom = np.sum((o - np.mean(o))**2)
    if denom == 0: return np.nan
    return 1.0 - (np.sum((o - s)**2) / denom)

def main(top_k: int = 10):
    batches = prepare_batches()
    
    # Find final iteration par file
    par_files = sorted(RUN_DIR.glob(f"{CASE}.*.par.csv"), key=lambda p: str(p))
    iter_par_files = [p for p in par_files if p.stem.split(".")[-2].isdigit()]
    if not iter_par_files:
        print("No iteration par files found!")
        return
    final_par = iter_par_files[-1]
    iter_no = final_par.stem.split(".")[-2]
    print(f"Loading final ensemble from: {final_par.name} (Iteration {iter_no})")
    
    df_par = pd.read_csv(final_par)
    df_par["real_name"] = df_par["real_name"].astype(str)
    
    # Check phi actual file
    phi_actual_file = RUN_DIR / f"{CASE}.phi.actual.csv"
    if phi_actual_file.exists():
        df_phi = pd.read_csv(phi_actual_file)
        row_iter = df_phi[df_phi["iteration"] == int(iter_no)]
        if not row_iter.empty:
            r0 = row_iter.iloc[0]
            phi_map = {str(k): float(v) for k, v in r0.items() if str(k) not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"] and pd.notna(v)}
            df_par["total_phi"] = df_par["real_name"].map(phi_map)
    
    if "total_phi" in df_par.columns:
        df_par = df_par.sort_values("total_phi")
    
    top_candidates = df_par.head(top_k)
    print(f"Top {top_k} realizations to evaluate:")
    for idx, r in top_candidates.iterrows():
        phi_val = r.get("total_phi", np.nan)
        print(f"  Realization {r['real_name']}: Phi = {phi_val:.2f}")
        
    eval_dir = RUN_DIR / "three_seasons_eval"
    eval_dir.mkdir(exist_ok=True)
    
    summary_records = []
    
    for idx, row in top_candidates.reset_index().iterrows():
        cand = str(row["real_name"])
        phi_val = row.get("total_phi", np.nan)
        print(f"\n=======================================================")
        print(f"[{idx+1}/{top_k}] Evaluating Candidate real_{cand} (Phi={phi_val:.1f}) across 3 seasons (35 treatments)...")
        print(f"=======================================================")
        
        p_row = row.drop(["real_name", "par_realization", "total_phi", "index"], errors="ignore")
        
        cand_dir = eval_dir / f"cand_real_{cand}"
        cand_dir.mkdir(exist_ok=True)
        pd.DataFrame({"name": p_row.index, "value": p_row.values}).to_csv(cand_dir / "params.csv", index=False)
        
        all_season_h = []
        season_metrics = {}
        
        for season, bpath in batches.items():
            s_dir = cand_dir / season
            res = run_deterministic_season(p_row, season, bpath, s_dir)
            if res is None:
                continue
            df_h, df_eval = res
            df_h["SEASON"] = season
            all_season_h.append(df_h)
            
            last_rows = df_h.sort_values("DATE").groupby(["EXCODE", "TN"]).last().reset_index()
            rmse_y, nrmse_y, d_y, r2_y = calc_metrics(last_rows["OBS_FRESH_CUM"], last_rows["SIM_FRESH_CUM"])
            nse_cum = calc_nse(df_h["OBS_FRESH_CUM"], df_h["SIM_FRESH_CUM"])
            
            season_metrics[season] = {
                "rmse": rmse_y,
                "nrmse": nrmse_y,
                "d": d_y,
                "r2": r2_y,
                "nse": nse_cum,
                "last_rows": last_rows,
            }
            print(f"[{season}]: NRMSE={nrmse_y:.2f}%, d={d_y:.4f}, R2={r2_y:.4f}, Dynamics NSE={nse_cum:.4f}")
            
        if not all_season_h:
            continue
            
        df_pooled_h = pd.concat(all_season_h, ignore_index=True)
        last_pooled = df_pooled_h.sort_values("DATE").groupby(["SEASON", "EXCODE", "TN"]).last().reset_index()
        rmse_tot, nrmse_tot, d_tot, r2_tot = calc_metrics(last_pooled["OBS_FRESH_CUM"], last_pooled["SIM_FRESH_CUM"])
        nse_tot = calc_nse(df_pooled_h["OBS_FRESH_CUM"], df_pooled_h["SIM_FRESH_CUM"])
        print(f"[GRAND POOLED 35 TRT]: NRMSE={nrmse_tot:.2f}%, d={d_tot:.4f}, R2={r2_tot:.4f}, Dynamics NSE={nse_tot:.4f}")
        
        # 25SP W1
        y25 = season_metrics["25SP"]["last_rows"]
        y25_dict = dict(zip(y25["TN"].astype(int), y25["SIM_FRESH_CUM"]))
        delta_25_w1 = y25_dict.get(10, 0) - y25_dict.get(13, 0)
        w1_ratio = (delta_25_w1 / 11590.0) * 100.0
        
        # 26SP W2N3 & W1N3
        y26 = season_metrics["26SP"]["last_rows"]
        y26_dict = dict(zip(y26["TN"].astype(int), y26["SIM_FRESH_CUM"]))
        y26_w2n3 = y26_dict.get(2, 0)
        y26_w1n3 = y26_dict.get(3, 0)
        
        m_25 = season_metrics.get("25SP", {})
        m_26 = season_metrics.get("26SP", {})
        m_fa = season_metrics.get("25FA", {})
        
        rec = {
            "rank": idx + 1,
            "real_name": cand,
            "phi": round(phi_val, 2) if np.isfinite(phi_val) else np.nan,
            # 25SP
            "25SP_NRMSE_pct": round(m_25.get("nrmse", np.nan), 2) if "nrmse" in m_25 else np.nan,
            "25SP_d": round(m_25.get("d", np.nan), 4) if "d" in m_25 else np.nan,
            "25SP_NSE": round(m_25.get("nse", np.nan), 4) if "nse" in m_25 else np.nan,
            "Delta_Y_W1_25SP": round(delta_25_w1, 1),
            "W1_N_ratio_pct": round(w1_ratio, 2),
            # 26SP
            "26SP_NRMSE_pct": round(m_26.get("nrmse", np.nan), 2) if "nrmse" in m_26 else np.nan,
            "26SP_d": round(m_26.get("d", np.nan), 4) if "d" in m_26 else np.nan,
            "26SP_NSE": round(m_26.get("nse", np.nan), 4) if "nse" in m_26 else np.nan,
            "Y_26SP_W2N3": round(y26_w2n3, 1),
            "Y_26SP_W1N3": round(y26_w1n3, 1),
            # 25FA Independent
            "25FA_NRMSE_pct": round(m_fa.get("nrmse", np.nan), 2) if "nrmse" in m_fa else np.nan,
            "25FA_d": round(m_fa.get("d", np.nan), 4) if "d" in m_fa else np.nan,
            "25FA_NSE": round(m_fa.get("nse", np.nan), 4) if "nse" in m_fa else np.nan,
            # Grand Pooled
            "Pooled_35trt_NRMSE_pct": round(nrmse_tot, 2),
            "Pooled_35trt_d": round(d_tot, 4),
            "Pooled_35trt_Dynamics_NSE": round(nse_tot, 4),
        }
        summary_records.append(rec)
        
        last_pooled.to_csv(cand_dir / "all_35_treatments_final_yield.csv", index=False)
        df_pooled_h.to_csv(cand_dir / "all_harvest_events_dynamics.csv", index=False)
        
    df_sum = pd.DataFrame(summary_records)
    df_sum.to_csv(eval_dir / "candidates_three_seasons_summary.csv", index=False)
    print("\n=======================================================")
    print("ALL TOP CANDIDATES THREE SEASONS COMPARATIVE SUMMARY:")
    print("=======================================================")
    print(df_sum.to_string(index=False))

if __name__ == "__main__":
    main()
