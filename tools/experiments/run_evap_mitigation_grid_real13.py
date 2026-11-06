#!/usr/bin/env python3
"""Run medium-resolution grid experiment for drip irrigation evaporation mitigation.

Co-optimizing 4 factors:
1. SLU1 (First stage soil evaporation limit): [0.5, 1.0, 1.5, 2.0] mm
2. Mulch cover (Plastic mulch width PMWD with PLRS=90cm): [0.0, 0.3, 0.5, 0.7] (PMWD: 0, 27, 45, 63 cm)
3. SLLL_top (Super-topsoil wilting point, layers 1 & 2: 0-2cm and 2-4cm): [0.142, 0.180, 0.220]
4. Irrigation efficiency (IREFF / EFIR): 0.95 (fixed)

Genetic baseline: candidate_iter5_real13 from full_gen_page22_sasc0925_150x5.
Dataset: 25SP all 11 treatments (DSSBatch.v48).
"""

import os
import sys
import shutil
import subprocess
import re
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.eval_full_gen98 import evaluate_run, calc_metrics

# Output directory
OUT_DIR = PROJECT_ROOT / "workspace" / "runs" / "grid_evap_mitigation_real13_20260919"
WORK_DIR = OUT_DIR / "work"
TEMPLATE_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_150x5_20260918" / "full_season_iter5_real13_25SP"
DSSAT_EXE = Path("C:/DSSAT48/DSCSM048.EXE")

# Grid definition
SLU1_LEVELS = [0.5, 1.0, 1.5, 2.0]
MULCH_LEVELS = [0.0, 0.3, 0.5, 0.7]  # Cover fraction
SLLL_TOP_LEVELS = [0.142, 0.180, 0.220]
EFIR_FIXED = 0.95
ROW_SPACING_CM = 90.0

def mulch_to_pmwd(mulch_frac: float) -> int:
    if mulch_frac <= 0.0:
        return 0
    return int(round(mulch_frac * ROW_SPACING_CM))

def setup_work_directory():
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)
    
    # Copy all essential files from TEMPLATE_DIR
    for f in TEMPLATE_DIR.glob("*"):
        if f.is_file() and not f.suffix.lower() == ".out":
            shutil.copy2(f, WORK_DIR)
            
    # Ensure CUL, ECO, SPE exist
    for ext in ["CUL", "ECO", "SPE"]:
        src_f = TEMPLATE_DIR / f"TMGRO048.{ext}"
        if src_f.exists():
            shutil.copy2(src_f, WORK_DIR)
            
    # Copy DSSAT executable
    shutil.copy2(DSSAT_EXE, WORK_DIR)
    print(f"Work directory initialized at {WORK_DIR}")

def update_soil_sol(slu1: float, slll_top: float, sol_file: Path):
    txt = sol_file.read_text(encoding="utf-8", errors="ignore")
    
    # 1. Update SLU1 in XXSL2501 (@ SCOM line)
    target_scom = "   -99  0.13   5.5  0.65  75.0  1.00  .863 IB001 IB001 IB001"
    repl_scom   = f"   -99  0.13{slu1:6.1f}  0.65  75.0  1.00  .863 IB001 IB001 IB001"
    if target_scom in txt:
        txt = txt.replace(target_scom, repl_scom)
    else:
        # Fallback regex with strict spacing
        txt = re.sub(r'(\s+-99\s+0\.13)\s+[\d\.]+(\s+0\.65\s+75\.0)', rf'\g<1>{slu1:6.1f}\g<2>', txt)
    
    # 2. Update SLLL for Layer 1 (0-2cm, depth 2) and Layer 2 (2-4cm, depth 4)
    l1_old = "     2   -99 .1419 .3147 .4876 1.000  3.50  1.40  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99"
    l1_new = f"     2   -99 {slll_top:5.3f} .3147 .4876 1.000  3.50  1.40  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99"
    
    l2_old = "     4   -99 .1527 .3091 .4313 1.000  3.50  1.55  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99"
    l2_new = f"     4   -99 {slll_top:5.3f} .3091 .4313 1.000  3.50  1.55  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99"
    
    if l1_old in txt and l2_old in txt:
        txt = txt.replace(l1_old, l1_new).replace(l2_old, l2_new)
    else:
        txt = re.sub(r'(\n\s+2\s+-99\s+)[\d\.]+(\s+\.3147)', rf'\g<1>{slll_top:5.3f}\g<2>', txt)
        txt = re.sub(r'(\n\s+4\s+-99\s+)[\d\.]+(\s+\.3091)', rf'\g<1>{slll_top:5.3f}\g<2>', txt)
    
    sol_file.write_text(txt, encoding="utf-8")

def update_tmx_file(pmwd: int, efir: float, tmx_file: Path):
    txt = tmx_file.read_text(encoding="utf-8", errors="ignore")
    
    # 1. Update EFIR in @I
    txt = re.sub(r'(\*IRRIGATION AND WATER MANAGEMENT\s+@I\s+EFIR[^\n]+\n\s+\d+\s+)[\d\.]+(\s+)', rf'\g<1>{efir:.2f}\g<2>', txt)
    
    # 2. Update IREFF in @N IRRIGATION
    txt = re.sub(r'(@N IRRIGATION[^\n]+\n\s+\d+\s+IR\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\d+\s+)[\d\.]+', rf'\g<1>{efir:.2f}', txt)
    
    # 3. Update FIELDS tier 3 (@L PMALB PMWD)
    lines = txt.splitlines()
    new_lines = []
    skip = False
    for l in lines:
        if l.startswith("@L PMALB") or (skip and l.strip().startswith("5") and len(l.split()) == 3):
            skip = True
            continue
        skip = False
        new_lines.append(l)
        if l.strip().startswith("5") and "FH101" in l:
            new_lines.append("@L PMALB  PMWD")
            if pmwd <= 0:
                new_lines.append(" 5   -99   -99")
            else:
                new_lines.append(f" 5  0.10   {pmwd:4d}")
                
    tmx_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

def parse_et_out(et_path: Path):
    """Extract final cumulative ET components for each treatment."""
    et_data = {}
    if not et_path.exists():
        return et_data
        
    with open(et_path, encoding="latin1") as f:
        lines = f.readlines()
        
    headers = None
    for l in lines:
        if l.startswith("@YEAR"):
            headers = l.split()[1:]
            break
            
    if not headers:
        return et_data
        
    cur_tn = None
    last_record = None
    for l in lines:
        if l.startswith("*RUN"):
            if cur_tn is not None and last_record is not None:
                et_data[cur_tn] = dict(zip(headers, last_record))
            parts = l.split()
            cur_tn = int(parts[-1])
            last_record = None
        elif cur_tn is not None and len(l.split()) == len(headers) + 1 and l.strip()[0].isdigit():
            last_record = l.split()[1:]
            
    if cur_tn is not None and last_record is not None:
        et_data[cur_tn] = dict(zip(headers, last_record))
        
    return et_data

def parse_plantgro_out(plantgro_path: Path):
    """Extract end of season LAID for each treatment."""
    pg_data = {}
    if not plantgro_path.exists():
        return pg_data
        
    with open(plantgro_path, encoding="latin1") as f:
        lines = f.readlines()
        
    cur_tn = None
    last_line = None
    for l in lines:
        if l.startswith("*RUN"):
            if cur_tn is not None and last_line is not None:
                parts = last_line.split()
                # LAID is index 6 (YEAR DOY DAS DAP L#SD GSTD LAID)
                pg_data[cur_tn] = float(parts[6])
            cur_tn = int(l.split()[-1])
            last_line = None
        elif cur_tn is not None and len(l.split()) > 20 and l.strip()[0].isdigit():
            last_line = l
            
    if cur_tn is not None and last_line is not None:
        parts = last_line.split()
        pg_data[cur_tn] = float(parts[6])
        
    return pg_data

def parse_soilwat_out(soilwat_path: Path):
    """Extract simulated VWC profile on specific dates for each treatment."""
    target_doys = {121: "mid", 144: "late"}
    sw_data = {} # {tn: {doy: {layer_name: vwc}}}
    
    if not soilwat_path.exists():
        return sw_data
        
    with open(soilwat_path, encoding="latin1") as f:
        lines = f.readlines()
        
    cur_tn = None
    for l in lines:
        if l.startswith("*RUN"):
            cur_tn = int(l.split()[-1])
            if cur_tn not in sw_data:
                sw_data[cur_tn] = {}
        elif cur_tn is not None and len(l.split()) > 25 and l.strip()[0].isdigit():
            parts = l.split()
            doy = int(parts[1])
            if doy in target_doys:
                sw1 = float(parts[17])
                sw2 = float(parts[18])
                sw3 = float(parts[19])
                sw4 = float(parts[20])
                sw5 = float(parts[21])
                sw6 = float(parts[22])
                sw7 = float(parts[23])
                sw8 = float(parts[24])
                
                # Calculate 5 standard depth layers
                vwc_0_20 = 0.10 * sw1 + 0.10 * sw2 + 0.55 * sw3 + 0.25 * sw4
                vwc_20_40 = 0.50 * sw4 + 0.50 * sw5
                vwc_40_60 = sw6
                vwc_60_80 = sw7
                vwc_80_100 = sw8
                
                sw_data[cur_tn][doy] = {
                    "0-20": vwc_0_20,
                    "20-40": vwc_20_40,
                    "40-60": vwc_40_60,
                    "60-80": vwc_60_80,
                    "80-100": vwc_80_100,
                }
    return sw_data

def evaluate_soil_water_fit(sw_data, obs_df):
    """Compute RMSE of simulated vs observed soil water for W1 treatments (TN 10 & 13)."""
    w1_obs = obs_df[(obs_df["trno"].isin([10, 13])) & (obs_df["date"].isin(["2025-05-01", "2025-05-24"]))]
    date_to_doy = {"2025-05-01": 121, "2025-05-24": 144}
    
    errs_0_20 = []
    errs_all = []
    late_0_20_sim = {}
    
    for _, row in w1_obs.iterrows():
        tn = int(row["trno"])
        doy = date_to_doy.get(row["date"])
        depth = row["depth_label"]
        obs_val = float(row["vwc_mean"])
        
        sim_val = sw_data.get(tn, {}).get(doy, {}).get(depth, np.nan)
        if np.isfinite(sim_val):
            err = sim_val - obs_val
            errs_all.append(err)
            if depth == "0-20":
                errs_0_20.append(err)
                if doy == 144:
                    late_0_20_sim[tn] = sim_val
                    
    rmse_0_20 = np.sqrt(np.mean(np.array(errs_0_20)**2)) if errs_0_20 else np.nan
    rmse_all = np.sqrt(np.mean(np.array(errs_all)**2)) if errs_all else np.nan
    
    return {
        "rmse_0_20": rmse_0_20,
        "rmse_all": rmse_all,
        "sim_0_20_tn10_late": late_0_20_sim.get(10, np.nan),
        "sim_0_20_tn13_late": late_0_20_sim.get(13, np.nan),
    }

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_work_directory()
    
    obs_file = WORK_DIR / "soil_water_observations.csv"
    obs_df = pd.read_csv(obs_file)
    
    records = []
    total_runs = len(SLU1_LEVELS) * len(MULCH_LEVELS) * len(SLLL_TOP_LEVELS)
    run_count = 0
    
    print(f"Starting grid sweep across {total_runs} combinations...")
    
    # Pristine backups
    base_sol_txt = (WORK_DIR / "SOIL.SOL").read_text(encoding="utf-8")
    base_tmx_txt = (WORK_DIR / "XXQL2501.TMX").read_text(encoding="utf-8")
    
    for slu1 in SLU1_LEVELS:
        for mulch in MULCH_LEVELS:
            pmwd = mulch_to_pmwd(mulch)
            for slll_top in SLLL_TOP_LEVELS:
                run_count += 1
                run_tag = f"run_{run_count:02d}_slu1_{slu1:.1f}_mulch_{mulch:.1f}_slll_{slll_top:.3f}"
                print(f"\n[{run_count:02d}/{total_runs}] Executing {run_tag} (PMWD={pmwd}cm)...")
                
                # 1. Reset and update SOIL.SOL
                (WORK_DIR / "SOIL.SOL").write_text(base_sol_txt, encoding="utf-8")
                update_soil_sol(slu1, slll_top, WORK_DIR / "SOIL.SOL")
                
                # 2. Reset and update XXQL2501.TMX
                (WORK_DIR / "XXQL2501.TMX").write_text(base_tmx_txt, encoding="utf-8")
                update_tmx_file(pmwd, EFIR_FIXED, WORK_DIR / "XXQL2501.TMX")
                
                # 3. Run DSSAT
                res = subprocess.run([str(DSSAT_EXE), "B", "DSSBatch.v48"], cwd=WORK_DIR, capture_output=True, text=True)
                if res.returncode != 0:
                    print(f"ERROR: DSSAT run failed with return code {res.returncode}")
                    continue
                    
                # 4. Harvest yield evaluation
                df_h, _ = evaluate_run(WORK_DIR / "DSSBatch.v48", WORK_DIR)
                last_rows = df_h.sort_values("DATE").groupby("TN").last().reset_index()
                rmse_y, nrmse_y, d_y, r2_y = calc_metrics(last_rows["OBS_FRESH_CUM"], last_rows["SIM_FRESH_CUM"])
                
                # Extract individual treatment yields
                y_dict = dict(zip(last_rows["TN"].astype(int), last_rows["SIM_FRESH_CUM"]))
                
                y_w1n3 = y_dict.get(10, np.nan)
                y_w1n0 = y_dict.get(13, np.nan)
                delta_w1 = y_w1n3 - y_w1n0
                obs_delta_w1 = 71137.0 - 59547.0 # 11590 kg/ha
                ratio_w1 = (delta_w1 / obs_delta_w1) * 100.0
                
                y_w3n3 = y_dict.get(2, np.nan)
                y_w3n0 = y_dict.get(5, np.nan)
                delta_w3 = y_w3n3 - y_w3n0
                obs_delta_w3 = 72323.0 - 68228.0 # 4095 kg/ha
                ratio_w3 = (delta_w3 / obs_delta_w3) * 100.0
                
                # 5. ET & Evaporation
                et_data = parse_et_out(WORK_DIR / "ET.OUT")
                
                tn10_et = et_data.get(10, {})
                tn13_et = et_data.get(13, {})
                tn2_et = et_data.get(2, {})
                tn5_et = et_data.get(5, {})
                
                tn10_es = float(tn10_et.get("ESAC", np.nan))
                tn10_ep = float(tn10_et.get("EPAC", np.nan))
                tn10_tot = float(tn10_et.get("ETAC", np.nan))
                tn10_ratio = (tn10_es / tn10_tot * 100.0) if tn10_tot > 0 else np.nan
                
                tn13_es = float(tn13_et.get("ESAC", np.nan))
                tn13_ep = float(tn13_et.get("EPAC", np.nan))
                tn13_tot = float(tn13_et.get("ETAC", np.nan))
                tn13_ratio = (tn13_es / tn13_tot * 100.0) if tn13_tot > 0 else np.nan
                
                w1_mean_es = (tn10_es + tn13_es) / 2.0
                w1_mean_es_ratio = (tn10_ratio + tn13_ratio) / 2.0
                
                tn2_es = float(tn2_et.get("ESAC", np.nan))
                tn2_tot = float(tn2_et.get("ETAC", np.nan))
                w3_mean_es_ratio = (tn2_es / tn2_tot * 100.0) if tn2_tot > 0 else np.nan
                
                # 6. PlantGro (LAI)
                pg_data = parse_plantgro_out(WORK_DIR / "PlantGro.OUT")
                lai_w3n0 = pg_data.get(5, np.nan)
                lai_w3n3 = pg_data.get(2, np.nan)
                lai_w1n3 = pg_data.get(10, np.nan)
                
                # 7. Soil Water
                sw_data = parse_soilwat_out(WORK_DIR / "SoilWat.OUT")
                sw_eval = evaluate_soil_water_fit(sw_data, obs_df)
                
                # 8. Record row
                rec = {
                    "run_idx": run_count,
                    "SLU1": slu1,
                    "mulch_cover": mulch,
                    "pmwd_cm": pmwd,
                    "slll_top": slll_top,
                    "efir": EFIR_FIXED,
                    # Yield
                    "Yield_RMSE_kg_ha": round(rmse_y, 1),
                    "Yield_NRMSE_pct": round(nrmse_y, 2),
                    "Yield_R2": round(r2_y, 4),
                    "Yield_d_index": round(d_y, 4),
                    # W1 Yield & N response
                    "Y_W1N3_kg_ha": round(y_w1n3, 1),
                    "Y_W1N0_kg_ha": round(y_w1n0, 1),
                    "Delta_Y_W1_sim": round(delta_w1, 1),
                    "W1_N_resp_ratio_pct": round(ratio_w1, 2),
                    # W3 Yield & N response
                    "Y_W3N3_kg_ha": round(y_w3n3, 1),
                    "Y_W3N0_kg_ha": round(y_w3n0, 1),
                    "Delta_Y_W3_sim": round(delta_w3, 1),
                    "W3_N_resp_ratio_pct": round(ratio_w3, 2),
                    # LAI
                    "LAI_W3N0_end": round(lai_w3n0, 2),
                    "LAI_W3N3_end": round(lai_w3n3, 2),
                    "LAI_W1N3_end": round(lai_w1n3, 2),
                    # Evaporation
                    "TN10_ESAC_mm": round(tn10_es, 1),
                    "TN10_EPAC_mm": round(tn10_ep, 1),
                    "TN10_ETAC_mm": round(tn10_tot, 1),
                    "TN10_Es_ratio_pct": round(tn10_ratio, 1),
                    "TN13_ESAC_mm": round(tn13_es, 1),
                    "TN13_Es_ratio_pct": round(tn13_ratio, 1),
                    "W1_mean_ESAC_mm": round(w1_mean_es, 1),
                    "W1_mean_Es_ratio_pct": round(w1_mean_es_ratio, 1),
                    "W3_mean_Es_ratio_pct": round(w3_mean_es_ratio, 1),
                    # Soil Water
                    "Sim_0_20_TN10_late": round(sw_eval["sim_0_20_tn10_late"], 3),
                    "Sim_0_20_TN13_late": round(sw_eval["sim_0_20_tn13_late"], 3),
                    "SoilWat_RMSE_0_20cm": round(sw_eval["rmse_0_20"], 4),
                    "SoilWat_RMSE_all_layers": round(sw_eval["rmse_all"], 4),
                }
                records.append(rec)
                
                print(f"   -> W1 ESAC: {w1_mean_es:.1f} mm ({w1_mean_es_ratio:.1f}%), Delta W1: {delta_w1:.1f} kg/ha ({ratio_w1:.1f}%)")
                print(f"   -> Yield NRMSE: {nrmse_y:.2f}%, d: {d_y:.4f}, SoilWat RMSE (0-20): {sw_eval['rmse_0_20']:.4f}")
                
                # Save partial CSV
                df_out = pd.DataFrame(records)
                df_out.to_csv(OUT_DIR / "grid_evap_summary_metrics.csv", index=False)
                
    print(f"\nAll {total_runs} grid runs completed successfully!")
    print(f"Summary table saved to {OUT_DIR / 'grid_evap_summary_metrics.csv'}")

if __name__ == "__main__":
    main()
