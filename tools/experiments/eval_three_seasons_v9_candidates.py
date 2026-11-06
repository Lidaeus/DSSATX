#!/usr/bin/env python3
"""Full 3-season deterministic evaluation (35 treatments) for top V9 candidates:
- real_51 (Qualified Champion 1: Pass all gates, W1 ratio=29.6%, LAI=1.26, 26SP W2N3=73.8t)
- real_68 (Qualified Champion 2: Pass all gates, W1 ratio=22.3%, LAI=1.35, 26SP W2N3=73.5t)
- real_44 (Global Min Phi=1627.0: W1 ratio=36.6%, LAI=1.77, 26SP W2N3=77.1t)
- real_74 (Low NRMSE: Calib NRMSE=12.94%, W1 ratio=19.5%, LAI=1.46, 26SP W2N3=66.2t)
- real_65 (Low NRMSE: Calib NRMSE=12.05%, W1 ratio=19.6%, LAI=1.22, 26SP W2N3=73.8t)

Seasons:
1. 25SP: 11 treatments (DSSBatch.v48)
2. 26SP: 12 treatments (DSSBatch_26sp.v48 or custom batch)
3. 25FA: 12 treatments (DSSBatch_25fa.v48 or custom batch)
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

RUN_DIR = PROJECT_ROOT / "workspace/runs/full_gen_slll4cm_s0922_0945_150x5_20260919"
CASE = "full_gen_slll4cm_s0922_0945_150x5"

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

CANDIDATES = ["51", "68", "44", "74", "65"]

def prepare_batches():
    # 25SP batch: all 11 treatments
    b25 = PROJECT_ROOT / "data/templates/batch/DSSBatch.v48"
    
    # 26SP batch: all 12 treatments
    b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
    for tn in range(1, 13):
        b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
    b26 = RUN_DIR / "DSSBatch_26SP_all.v48"
    b26.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")
    
    # 25FA batch: all 12 treatments
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

def main():
    batches = prepare_batches()
    par_file = RUN_DIR / f"{CASE}.5.par.csv"
    df_par = pd.read_csv(par_file)
    df_par["real_name"] = df_par["real_name"].astype(str)
    
    eval_dir = RUN_DIR / "three_seasons_eval"
    eval_dir.mkdir(exist_ok=True)
    
    summary_records = []
    
    for cand in CANDIDATES:
        print(f"\n=======================================================")
        print(f"Evaluating Candidate real_{cand} across 3 seasons (35 treatments)...")
        print(f"=======================================================")
        row = df_par[df_par["real_name"] == cand]
        if row.empty:
            print(f"Candidate {cand} not found in par file.")
            continue
        p_row = row.iloc[0].drop(["real_name", "par_realization", "total_phi"], errors="ignore")
        
        # Save individual candidate parameter CSV
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
            
            # Season yield metrics
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
            print(f"[{season}]: NRMSE={nrmse_y:.2f}%, d={d_y:.4f}, R2={r2_y:.4f}, Harvest Dynamics NSE={nse_cum:.4f}")
            
        # Pooled metrics
        df_pooled_h = pd.concat(all_season_h, ignore_index=True)
        last_pooled = df_pooled_h.sort_values("DATE").groupby(["SEASON", "EXCODE", "TN"]).last().reset_index()
        rmse_tot, nrmse_tot, d_tot, r2_tot = calc_metrics(last_pooled["OBS_FRESH_CUM"], last_pooled["SIM_FRESH_CUM"])
        nse_tot = calc_nse(df_pooled_h["OBS_FRESH_CUM"], df_pooled_h["SIM_FRESH_CUM"])
        print(f"[GRAND POOLED 35 TRT]: NRMSE={nrmse_tot:.2f}%, d={d_tot:.4f}, R2={r2_tot:.4f}, Dynamics NSE={nse_tot:.4f}")
        
        # Extract specific checks
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
        
        rec = {
            "real_name": cand,
            "SASC_RATIO": p_row.get("sasc_ratio", np.nan),
            "SOIL_SLLL_01": p_row.get("soil_slll_01", np.nan),
            "SOIL_SLLL_02": p_row.get("soil_slll_02", np.nan),
            "SOIL_SLDR": p_row.get("soil_sldr", np.nan),
            # 25SP
            "25SP_NRMSE_pct": round(season_metrics["25SP"]["nrmse"], 2),
            "25SP_d": round(season_metrics["25SP"]["d"], 4),
            "25SP_NSE": round(season_metrics["25SP"]["nse"], 4),
            "Delta_Y_W1_25SP": round(delta_25_w1, 1),
            "W1_N_ratio_pct": round(w1_ratio, 2),
            # 26SP
            "26SP_NRMSE_pct": round(season_metrics["26SP"]["nrmse"], 2),
            "26SP_d": round(season_metrics["26SP"]["d"], 4),
            "26SP_NSE": round(season_metrics["26SP"]["nse"], 4),
            "Y_26SP_W2N3": round(y26_w2n3, 1),
            "Y_26SP_W1N3": round(y26_w1n3, 1),
            # 25FA Independent
            "25FA_NRMSE_pct": round(season_metrics["25FA"]["nrmse"], 2),
            "25FA_d": round(season_metrics["25FA"]["d"], 4),
            "25FA_NSE": round(season_metrics["25FA"]["nse"], 4),
            # Grand Pooled
            "Pooled_35trt_NRMSE_pct": round(nrmse_tot, 2),
            "Pooled_35trt_d": round(d_tot, 4),
            "Pooled_35trt_Dynamics_NSE": round(nse_tot, 4),
        }
        summary_records.append(rec)
        
        # Save individual candidate full harvest table
        last_pooled.to_csv(cand_dir / "all_35_treatments_final_yield.csv", index=False)
        df_pooled_h.to_csv(cand_dir / "all_harvest_events_dynamics.csv", index=False)
        
    df_sum = pd.DataFrame(summary_records)
    df_sum.to_csv(eval_dir / "candidates_three_seasons_summary.csv", index=False)
    print("\n=======================================================")
    print("THREE SEASONS COMPARATIVE SUMMARY:")
    print("=======================================================")
    print(df_sum.to_string(index=False))

if __name__ == "__main__":
    main()
