#!/usr/bin/env python3
"""Sandbox Evaluation Script for Eggplant Model Representative Solution local_00023.

Executes batch eggplant_26sp_all12_robust_joint65_200x5_20261012 under:
1. Vanilla Baseline (dscsm048_vanilla.exe) with MEPHO='L' (original params)
2. Vanilla Baseline (dscsm048_vanilla.exe) with MEPHO='C' (original params)
3. Custom Scheme B (dscsm048_cnc.exe) with MEPHO='L' (backward compatibility check)
4. Custom Scheme B (dscsm048_cnc.exe) with MEPHO='C' (active Scheme B NNI coupling)
5. Vanilla Baseline (dscsm048_vanilla.exe) with MEPHO='L' (refined params: FL-LF=60.0, SENPOR_LATE=0.25)
6. Custom Scheme B (dscsm048_cnc.exe) with MEPHO='C' (refined params: FL-LF=60.0, SENPOR_LATE=0.25)

Extracts metrics, daily trajectories, LAI overshooting analysis, biomass partitioning,
leaf N and NNI dynamics, and mass conservation.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dssat.array_expander import expand_senpor


def parse_whitespace_line(line: str) -> list[str]:
    return line.strip().split()


def parse_dssat_out_file(file_path: Path) -> dict[int, list[dict[str, str]]]:
    """Parses a multi-run DSSAT output file into {trt_no: [records]}."""
    if not file_path.exists():
        return {}
    
    lines = file_path.read_text(encoding="latin-1", errors="ignore").splitlines()
    data_by_trt: dict[int, list[dict[str, str]]] = {}
    current_trt = None
    headers: list[str] = []
    
    for line in lines:
        sline = line.strip()
        if not sline:
            continue
        if sline.startswith("*RUN"):
            # Format: *RUN   1        : W3_N3                     CRGRO048 XXQL2601    1
            parts = sline.split()
            try:
                current_trt = int(parts[1])
                data_by_trt[current_trt] = []
            except (ValueError, IndexError):
                current_trt = None
            headers = []
            continue
        if sline.startswith("@"):
            # Header line: @YEAR DOY   DAS   DAP ...
            headers = [h.strip() for h in sline[1:].split()]
            continue
        if sline.startswith("*") or sline.startswith("!"):
            continue
        if current_trt is not None and headers:
            values = sline.split()
            if len(values) >= len(headers):
                rec = {headers[i]: values[i] for i in range(len(headers))}
                data_by_trt[current_trt].append(rec)
            elif len(values) > 0:
                rec = {headers[i]: values[i] for i in range(len(values))}
                data_by_trt[current_trt].append(rec)
                
    return data_by_trt


def compute_metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    """Compute RMSE, NRMSE, R2, NSE, d-index, MAE, MBE."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs = obs[mask]
    sim = sim[mask]
    n = len(obs)
    if n == 0:
        return {"n": 0, "rmse": np.nan, "nrmse": np.nan, "r2": np.nan, "nse": np.nan, "d": np.nan, "mae": np.nan, "mbe": np.nan}
    
    diff = sim - obs
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    obs_mean = float(np.mean(obs))
    nrmse = float(100.0 * rmse / abs(obs_mean)) if abs(obs_mean) > 1e-9 else np.nan
    mae = float(np.mean(np.abs(diff)))
    mbe = float(np.mean(diff))
    
    # R2
    if np.std(obs) > 1e-9 and np.std(sim) > 1e-9:
        r = float(np.corrcoef(obs, sim)[0, 1])
        r2 = r ** 2
    else:
        r2 = np.nan
        
    # NSE
    ss_tot = float(np.sum((obs - obs_mean) ** 2))
    ss_res = float(np.sum(diff ** 2))
    nse = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-9 else np.nan
    
    # Willmott d-index
    d_denom = float(np.sum((np.abs(sim - obs_mean) + np.abs(obs - obs_mean)) ** 2))
    d = float(1.0 - ss_res / d_denom) if d_denom > 1e-9 else np.nan
    
    return {"n": n, "rmse": rmse, "nrmse": nrmse, "r2": r2, "nse": nse, "d": d, "mae": mae, "mbe": mbe}


def setup_sandbox_dir(
    sandbox_dir: Path,
    model_src: Path,
    binary_path: Path,
    mepho: str = "L",
    refine_params: bool = False,
    refined_fl_lf: float = 60.0,
    refined_senpor_late: float = 0.25,
) -> None:
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy essential input files
    copy_files = [
        "DSSAT48.INH", "DSSAT48.INP", "DSSATPRO.v48", "DSSBatch.v48",
        "SOIL.SOL", "SOIL.SOL.base", "TMGRO048.CUL", "TMGRO048.CUL.base",
        "TMGRO048.ECO", "TMGRO048.ECO.base", "TMGRO048.SPE", "TMGRO048.SPE.base",
        "XXQL2601.TMA", "XXQL2601.TMT", "XXQL2601.TMX", "XXTW2403.WTH",
        "parameters.csv"
    ]
    for fn in copy_files:
        src_f = model_src / fn
        if src_f.exists():
            shutil.copy(src_f, sandbox_dir / fn)
            
    # Copy binary as DSCSM048.EXE
    shutil.copy(binary_path, sandbox_dir / "DSCSM048.EXE")
    
    # Modify MEPHO in XXQL2601.TMX if requested
    tmx_path = sandbox_dir / "XXQL2601.TMX"
    if tmx_path.exists() and mepho.upper() == "C":
        txt = tmx_path.read_text(encoding="latin-1")
        txt = txt.replace("S     L     R     1", "S     C     R     1")
        tmx_path.write_text(txt, encoding="latin-1")
        
    # Refine physiological parameters if requested
    if refine_params:
        # 1. Update FL-LF in TMGRO048.CUL
        cul_path = sandbox_dir / "TMGRO048.CUL"
        if cul_path.exists():
            cul_lines = cul_path.read_text(encoding="latin-1").splitlines()
            new_lines = []
            for line in cul_lines:
                if line.startswith("TM0008"):
                    # The line format:
                    # TM0008 Brilliance           . TM0001 12.33  0.00  27.7   3.3  24.7 400.0 192.3  2.42  168. 297.4 .9267  .004  27.1 111.4   9.5   8.5  .300  .050
                    # FL-LF is the 7th coefficient after TM0001 (EM-FL, FL-SH, FL-SD, SD-PM, FL-LF)
                    # Notice: ' 192.3' -> replace with f'{refined_fl_lf:6.1f}'
                    old_str = " 192.3"
                    new_str = f"{refined_fl_lf:6.1f}"
                    line = line.replace(old_str, new_str)
                new_lines.append(line)
            cul_path.write_text("\n".join(new_lines) + "\n", encoding="latin-1")
            
        # 2. Update SENPOR_LATE in TMGRO048.SPE
        spe_path = sandbox_dir / "TMGRO048.SPE"
        if spe_path.exists():
            spe_lines = spe_path.read_text(encoding="latin-1").splitlines()
            new_lines = []
            sen_expanded = expand_senpor(refined_senpor_late).y_values
            # sen_expanded is (0.0, 0.0, 0.09, 0.25)
            # Format: '   0.0   0.0  .090  .250'
            new_senpor_str = f"   0.0   0.0  {sen_expanded[2]:.3f}  {sen_expanded[3]:.3f}".replace("0.", ".")
            for i, line in enumerate(spe_lines):
                if "! .......SENPOR........." in line and i + 1 < len(spe_lines):
                    # Next line contains SENPOR and SENMAX
                    next_line = spe_lines[i + 1]
                    # Original: '   0.0   0.0  .077  .215   0.0    .4   .37   .24'
                    # Replace first 22 chars with new SENPOR
                    old_senpor_part = next_line[:22]
                    new_line = new_senpor_str + next_line[22:]
                    spe_lines[i + 1] = new_line
            spe_path.write_text("\n".join(spe_lines) + "\n", encoding="latin-1")


def run_simulation(sandbox_dir: Path) -> dict[str, Any]:
    t0 = time.time()
    cmd = [str(sandbox_dir / "DSCSM048.EXE"), "CRGRO048", "B", "DSSBatch.v48"]
    res = subprocess.run(
        cmd,
        cwd=sandbox_dir,
        input="\n" * 8,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.time() - t0
    
    plantgro_path = sandbox_dir / "PlantGro.OUT"
    plantgro_lines = 0
    if plantgro_path.exists():
        plantgro_lines = len(plantgro_path.read_text(encoding="latin-1", errors="ignore").splitlines())
        
    return {
        "returncode": res.returncode,
        "elapsed_sec": elapsed,
        "plantgro_lines": plantgro_lines,
        "stdout_tail": res.stdout[-300:] if res.stdout else "",
        "stderr": res.stderr,
    }


def main():
    print("=" * 80)
    print("EGGPLANT LOCAL_00023 SCHEME B & VANILLA SANDBOX EVALUATION")
    print("=" * 80)
    
    model_src = PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/selected_deterministic/_model"
    comp_file = PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv"
    tmt_meta_file = PROJECT_ROOT / "configs/figures/treatment_metadata_xxql2601.csv"
    
    bin_vanilla = PROJECT_ROOT / "subprojects/critical_n/bin/dscsm048_vanilla.exe"
    bin_cnc = PROJECT_ROOT / "subprojects/critical_n/bin/dscsm048_cnc.exe"
    
    runs_root = PROJECT_ROOT / "subprojects/critical_n/runs/eval_local00023"
    reports_dir = PROJECT_ROOT / "subprojects/critical_n/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    assert model_src.exists(), f"Missing model source: {model_src}"
    assert bin_vanilla.exists(), f"Missing vanilla binary: {bin_vanilla}"
    assert bin_cnc.exists(), f"Missing CNC binary: {bin_cnc}"
    assert comp_file.exists(), f"Missing comparison file: {comp_file}"
    assert tmt_meta_file.exists(), f"Missing metadata file: {tmt_meta_file}"
    
    tmt_meta = pd.read_csv(tmt_meta_file)
    obs_df = pd.read_csv(comp_file)
    obs_df_26 = obs_df[obs_df["season_id"] == "26SP"].copy()
    
    configs = [
        {
            "id": "vanilla_mepho_l_orig",
            "label": "Vanilla Baseline (MEPHO=L, Orig Params)",
            "binary": bin_vanilla,
            "mepho": "L",
            "refine": False,
        },
        {
            "id": "vanilla_mepho_c_orig",
            "label": "Vanilla Canopy Photo (MEPHO=C, Orig Params)",
            "binary": bin_vanilla,
            "mepho": "C",
            "refine": False,
        },
        {
            "id": "cnc_mepho_l_orig",
            "label": "Scheme B Binary (MEPHO=L, Orig Params)",
            "binary": bin_cnc,
            "mepho": "L",
            "refine": False,
        },
        {
            "id": "cnc_mepho_c_orig",
            "label": "Scheme B Active Coupled (MEPHO=C, Orig Params)",
            "binary": bin_cnc,
            "mepho": "C",
            "refine": False,
        },
        {
            "id": "vanilla_mepho_l_refined",
            "label": "Vanilla Baseline (MEPHO=L, Refined: FL-LF=60, SENPOR=0.25)",
            "binary": bin_vanilla,
            "mepho": "L",
            "refine": True,
        },
        {
            "id": "cnc_mepho_c_refined",
            "label": "Scheme B Active Coupled (MEPHO=C, Refined: FL-LF=60, SENPOR=0.25)",
            "binary": bin_cnc,
            "mepho": "C",
            "refine": True,
        },
    ]
    
    run_results = {}
    parsed_runs = {}
    
    for cfg in configs:
        cid = cfg["id"]
        sb_dir = runs_root / cid
        print(f"\n[*] Preparing & Running Sandbox: {cid} ({cfg['label']})...")
        setup_sandbox_dir(
            sandbox_dir=sb_dir,
            model_src=model_src,
            binary_path=cfg["binary"],
            mepho=cfg["mepho"],
            refine_params=cfg["refine"],
            refined_fl_lf=60.0,
            refined_senpor_late=0.25,
        )
        res = run_simulation(sb_dir)
        run_results[cid] = res
        print(f"    Exit code: {res['returncode']} | Elapsed: {res['elapsed_sec']:.2f}s | PlantGro lines: {res['plantgro_lines']}")
        assert res["returncode"] == 0, f"Simulation failed for {cid}: {res['stderr']}"
        
        # Parse outputs
        pg_data = parse_dssat_out_file(sb_dir / "PlantGro.OUT")
        pn_data = parse_dssat_out_file(sb_dir / "PlantN.OUT")
        fw_data = parse_dssat_out_file(sb_dir / "FreshWt.OUT")
        
        parsed_runs[cid] = {
            "pg": pg_data,
            "pn": pn_data,
            "fw": fw_data,
            "dir": sb_dir,
        }
        
    print("\n[+] All 6 sandbox simulations completed successfully!")
    
    # Analyze daily trajectories and compute NNI & mass balance
    all_trajectories = []
    treatment_summaries = []
    
    for cfg in configs:
        cid = cfg["id"]
        data = parsed_runs[cid]
        pg_by_trt = data["pg"]
        pn_by_trt = data["pn"]
        fw_by_trt = data["fw"]
        
        for trt in range(1, 13):
            pg_recs = pg_by_trt.get(trt, [])
            pn_recs = pn_by_trt.get(trt, [])
            fw_recs = fw_by_trt.get(trt, [])
            
            # Map by DAP
            pn_map = {int(r["DAP"]): r for r in pn_recs if "DAP" in r}
            fw_map = {int(r["DAP"]): r for r in fw_recs if "DAP" in r}
            
            meta_row = tmt_meta[tmt_meta["treatment"] == trt].iloc[0]
            w_level = meta_row["water_level"]
            n_level = meta_row["nitrogen_level"]
            
            final_chfpw = 0.0
            final_chpdt = 0.0
            peak_lai = 0.0
            final_lai = 0.0
            max_n_residual = 0.0
            
            for r_pg in pg_recs:
                if "DAP" not in r_pg:
                    continue
                dap = int(r_pg["DAP"])
                doy = int(r_pg.get("DOY", 0))
                lai = float(r_pg.get("LAID", 0.0))
                cwad = float(r_pg.get("CWAD", 0.0))
                lwad = float(r_pg.get("LWAD", 0.0))
                swad = float(r_pg.get("SWAD", 0.0))
                gwad = float(r_pg.get("GWAD", 0.0))
                chtd = float(r_pg.get("CHTD", 0.0))
                
                r_pn = pn_map.get(dap, {})
                cnad = float(r_pn.get("CNAD", 0.0))
                pcnl = float(r_pn.get("LN%D", 0.0))
                pcnst = float(r_pn.get("SN%D", 0.0))
                lnad = float(r_pn.get("LNAD", 0.0))
                snad = float(r_pn.get("SNAD", 0.0))
                gnad = float(r_pn.get("GNAD", 0.0))
                nupc = float(r_pn.get("NUPC", 0.0))
                
                r_fw = fw_map.get(dap, {})
                chfpw = float(r_fw.get("CHFPW", 0.0))
                chpdt = float(r_fw.get("CHPDT", 0.0))
                hfpow = float(r_fw.get("HFPOW", 0.0))
                hpodw = float(r_fw.get("HPODW", 0.0))
                
                # Critical N dilution calculation
                w_eff = (cwad + chpdt) / 1000.0  # t DM/ha
                nc_crit = 4.85 * (max(1.0, w_eff) ** (-0.38))  # Greenwood-Lemaire Nc (%)
                nni = pcnl / nc_crit if nc_crit > 1e-4 else np.nan
                
                # N mass balance check:
                # In CROPGRO, CNAD is total standing tops N (LNAD + SNAD + Pod N).
                # Total absorbed N NUPC = standing tops N + cumulative harvest N + root N (approx).
                # Internal tops residual check:
                n_organs = lnad + snad + gnad
                n_residual = abs(cnad - n_organs)
                if n_residual > max_n_residual:
                    max_n_residual = n_residual
                
                if lai > peak_lai:
                    peak_lai = lai
                final_lai = lai
                final_chfpw = chfpw
                final_chpdt = chpdt
                
                all_trajectories.append({
                    "config_id": cid,
                    "treatment": trt,
                    "water_level": w_level,
                    "nitrogen_level": n_level,
                    "dap": dap,
                    "doy": doy,
                    "lai": lai,
                    "lwad": lwad,
                    "swad": swad,
                    "gwad": gwad,
                    "cwad": cwad,
                    "w_eff": w_eff,
                    "pcnl": pcnl,
                    "pcnst": pcnst,
                    "nc_crit": nc_crit,
                    "nni": nni,
                    "lnad": lnad,
                    "snad": snad,
                    "gnad": gnad,
                    "cnad": cnad,
                    "nupc": nupc,
                    "chfpw": chfpw,
                    "chpdt": chpdt,
                    "hfpow": hfpow,
                    "hpodw": hpodw,
                    "chtd": chtd,
                })
                
            treatment_summaries.append({
                "config_id": cid,
                "treatment": trt,
                "water_level": w_level,
                "nitrogen_level": n_level,
                "peak_lai": peak_lai,
                "final_lai": final_lai,
                "final_chfpw": final_chfpw,
                "final_chpdt": final_chpdt,
                "max_n_residual": max_n_residual,
            })
            
    df_traj = pd.DataFrame(all_trajectories)
    df_tmt_sum = pd.DataFrame(treatment_summaries)
    
    # Save trajectories and treatment summary
    traj_csv = reports_dir / "eval_local00023_trajectories_all.csv"
    tmt_sum_csv = reports_dir / "eval_local00023_treatment_summary.csv"
    df_traj.to_csv(traj_csv, index=False)
    df_tmt_sum.to_csv(tmt_sum_csv, index=False)
    print(f"\n[+] Exported daily trajectories to: {traj_csv} ({len(df_traj)} rows)")
    print(f"[+] Exported treatment summary to: {tmt_sum_csv} ({len(df_tmt_sum)} rows)")
    
    # Statistical validation against 2026 spring observations
    print("\n[+] Evaluating performance metrics against 2026 spring observations...")
    eval_vars = ["CHFPW", "CHPDT", "LAID", "LWAD", "SWAD", "LEAF_N_PCT", "STEM_N_PCT"]
    metrics_records = []
    
    # Map variable names in df_traj
    var_map = {
        "CHFPW": "chfpw",
        "CHPDT": "chpdt",
        "LAID": "lai",
        "LWAD": "lwad",
        "SWAD": "swad",
        "LEAF_N_PCT": "pcnl",
        "STEM_N_PCT": "pcnst",
    }
    
    for cfg in configs:
        cid = cfg["id"]
        cfg_traj = df_traj[df_traj["config_id"] == cid]
        
        for vname in eval_vars:
            traj_col = var_map[vname]
            v_obs_df = obs_df_26[obs_df_26["variable"] == vname]
            
            obs_vals = []
            sim_vals = []
            
            for _, row in v_obs_df.iterrows():
                trt = int(row["trno"])
                # Extract date/dap
                # In comparison_all_roles, model_date or date
                # Let's check date or model_date
                # We can match by treatment and DAP or date
                # In 2026 spring, planting was DAP 0 on DOY 71
                dt_str = str(row["date"])  # e.g. '2026-05-02'
                # Convert date to DOY or match with observation
                # In comparison_all_roles, row['simulated'] was simulated by the model
                # We can find the matching sim value in cfg_traj
                # In comparison_all_roles:
                # CHFPW and CHPDT are terminal observations at harvest end (DAP ~127 / DOY 198)
                if vname in ["CHFPW", "CHPDT"]:
                    # Take the terminal simulated value for this treatment
                    t_sub = cfg_traj[cfg_traj["treatment"] == trt]
                    if not t_sub.empty:
                        s_val = t_sub.iloc[-1][traj_col]
                        obs_vals.append(float(row["observed"]))
                        sim_vals.append(float(s_val))
                else:
                    # Match by DOY or DAP
                    # Let's parse date to DOY
                    try:
                        ts = pd.to_datetime(dt_str)
                        doy = ts.dayofyear
                    except Exception:
                        doy = None
                    if doy is not None:
                        t_sub = cfg_traj[(cfg_traj["treatment"] == trt) & (cfg_traj["doy"] == doy)]
                        if not t_sub.empty:
                            s_val = t_sub.iloc[0][traj_col]
                            obs_vals.append(float(row["observed"]))
                            sim_vals.append(float(s_val))
                            
            m = compute_metrics(np.array(obs_vals), np.array(sim_vals))
            metrics_records.append({
                "config_id": cid,
                "config_label": cfg["label"],
                "variable": vname,
                "n": m["n"],
                "rmse": m["rmse"],
                "nrmse": m["nrmse"],
                "r2": m["r2"],
                "nse": m["nse"],
                "d": m["d"],
                "mae": m["mae"],
                "mbe": m["mbe"],
            })
            
    df_metrics = pd.DataFrame(metrics_records)
    metrics_csv = reports_dir / "eval_local00023_metrics_summary.csv"
    df_metrics.to_csv(metrics_csv, index=False)
    print(f"[+] Exported metrics summary to: {metrics_csv}")
    
    # Print comparison matrix table
    print("\n" + "=" * 90)
    print("METRICS COMPARISON TABLE ACROSS CONFIGURATIONS")
    print("=" * 90)
    for vname in eval_vars:
        print(f"\n--- Variable: {vname} ---")
        v_df = df_metrics[df_metrics["variable"] == vname][["config_id", "n", "rmse", "nrmse", "r2", "nse", "d", "mbe"]]
        print(v_df.to_string(index=False))
        
    print("\n" + "=" * 90)
    print("TREATMENT-LEVEL LAI & YIELD COMPARISON (N0 vs N1 vs N2 vs N3 under W2):")
    print("=" * 90)
    # W2 treatments are: TN2 (W2-N3), TN5 (W2-N2), TN8 (W2-N1), TN11 (W2-N0)
    # Treatments: 2, 5, 8, 11
    w2_trts = [11, 8, 5, 2]  # N0, N1, N2, N3
    w2_summary = df_tmt_sum[df_tmt_sum["treatment"].isin(w2_trts)]
    print(w2_summary.pivot(index="config_id", columns="treatment", values=["peak_lai", "final_lai", "final_chfpw"]).to_string())
    
    print("\n[+] Sandbox evaluation completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
