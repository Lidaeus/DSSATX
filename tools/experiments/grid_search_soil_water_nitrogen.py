#!/usr/bin/env python3
"""Dense 2D Grid Experiment for Initial Soil Water & Nitrogen/Carbon Scaling (26SP)
Investigates:
1. Water scaling factor: fw in [0.90, 1.05] (step = 0.01, 16 levels)
2. Initial N & Organic Carbon scaling factor: fnc in [0.70, 1.20] (step = 0.02, 26 levels)
Total 416 grid points evaluated using 6 parallel workers.

For each treatment, extracts response surface Y_i(fw, fnc).
Identifies:
- Individual optimal (fw*, fnc*) for each abnormal treatment (T12, T10, T7, T9, T6).
- Group optimal scaling for deficit W1 treatments and low-N treatments.
- Evaluates 26SP R^2, NRMSE, NSE under optimal scaling combinations.
- Generates 2D heatmaps and diagnostic plots.
"""

import os
import sys
import shutil
import subprocess
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dssat.run_dssat import prepare_run_directory

OUT_DIR = PROJECT_ROOT / "workspace" / "experiments" / "soil_water_nitrogen_grid"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCRATCH_DIR = PROJECT_ROOT / "scratch" / "soil_grid_workers"
ARTIFACT_IMG_DIR = Path(r"C:\Users\Lidaeus\.gemini\antigravity-cli\brain\06a22b3d-1374-436c-944f-90bd22502f7f\images")
ARTIFACT_IMG_DIR.mkdir(parents=True, exist_ok=True)

# Reference parameters: Candidate C27 (Real 24 + SRGF09=0.010 + SASC=0.92)
C27_PARAM_CSV = PROJECT_ROOT / "workspace/candidates/candidate_c27_real24_root140_sasc092/params.csv"
EXP_DIR_26 = PROJECT_ROOT / "data/user/experiments/xxql2601_corrected_20260923"
BASE_TMX_PATH = EXP_DIR_26 / "XXQL2601.TMX"
BASE_TMX_CONTENT = BASE_TMX_PATH.read_text(encoding="utf-8")

# Batch for 26SP (all 12 treatments)
b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
for tn in range(1, 13):
    b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
BATCH_CONTENT = "\n".join(b26_lines) + "\n"

# Observed yields for 26SP
REF_OBS_CSV = PROJECT_ROOT / "workspace/candidates/candidate_c27_real24_root140_sasc092/all_35_treatments_final_yield.csv"
obs_df = pd.read_csv(REF_OBS_CSV)
obs_26 = obs_df[obs_df["season"] == "26SP"].sort_values("treatment")
OBS_YIELDS = {int(r["treatment"]): float(r["obs_t_ha"]) for _, r in obs_26.iterrows()}
TRT_LABELS = {int(r["treatment"]): str(r["treatment_label"]) for _, r in obs_26.iterrows()}

def modify_tmx_lines(lines, fw, fn, fc, target_tns=None):
    """Scale SH2O by fw, SNH4 and SNO3 by fn in *INITIAL CONDITIONS;
    Scale SAOC by fc in *SOIL ANALYSIS.
    If target_tns is None, scale all treatments; otherwise only scale specified treatments.
    """
    out_lines = []
    in_ic = False
    in_sa = False
    
    for l in lines:
        if "*SOIL ANALYSIS" in l:
            in_sa = True
            in_ic = False
            out_lines.append(l)
            continue
        elif "*INITIAL CONDITIONS" in l:
            in_sa = False
            in_ic = True
            out_lines.append(l)
            continue
        elif l.startswith("*"):
            in_sa = False
            in_ic = False
            out_lines.append(l)
            continue
            
        if in_sa and len(l) > 20 and not l.startswith("@"):
            try:
                sa_id = int(l[:2].strip())
                if target_tns is None or sa_id in target_tns:
                    sabl = int(l[2:8])
                    sadm = float(l[8:14])
                    saoc = float(l[14:20])
                    saoc_new = saoc * fc
                    rest = l[20:]
                    # Ensure same width
                    mod_line = f"{sa_id:2d}{sabl:6d}{sadm:6.2f}{saoc_new:6.2f}" + rest
                    out_lines.append(mod_line)
                    continue
            except Exception:
                pass
                
        if in_ic and len(l) > 26 and not l.startswith("@"):
            try:
                ic_id = int(l[:3].strip())
                if target_tns is None or ic_id in target_tns:
                    icbl = int(l[3:9])
                    sh2o = float(l[9:15])
                    snh4 = float(l[15:21])
                    sno3 = float(l[21:27])
                    rest = l[27:]
                    
                    sh2o_new = min(max(sh2o * fw, 0.05), 0.50)
                    snh4_new = snh4 * fn
                    sno3_new = sno3 * fn
                    
                    mod_line = f"{ic_id:3d}{icbl:6d}{sh2o_new:6.3f}{snh4_new:6.2f}{sno3_new:6.2f}" + rest
                    out_lines.append(mod_line)
                    continue
            except Exception:
                pass
                
        out_lines.append(l)
        
    return out_lines

def setup_worker(worker_id):
    wdir = SCRATCH_DIR / f"worker_{worker_id}"
    if wdir.exists():
        shutil.rmtree(wdir)
    wdir.mkdir(parents=True, exist_ok=True)
    # Copy template experiment directory
    shutil.copytree(EXP_DIR_26, wdir / "exp")
    # Copy genotype templates
    for bf in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
        shutil.copy2(PROJECT_ROOT / "data/templates/genotype" / bf, wdir / "exp" / bf)
    # Write batch file
    (wdir / "exp" / "DSSBatch_26SP_all.v48").write_text(BATCH_CONTENT, encoding="utf-8")
    return wdir

def run_grid_task(task_args):
    fw, fnc, worker_id, task_idx = task_args
    wdir = SCRATCH_DIR / f"worker_{worker_id}"
    exp_dir = wdir / "exp"
    run_dir = wdir / f"run_{task_idx}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Modify TMX in place inside run_dir
    tmx_lines = BASE_TMX_CONTENT.splitlines(keepends=True)
    mod_lines = modify_tmx_lines(tmx_lines, fw=fw, fn=fnc, fc=fnc, target_tns=None)
    
    # Prepare run dir
    batch_dest = prepare_run_directory(run_dir, ["--batch", str(exp_dir / "DSSBatch_26SP_all.v48"), "--input-dir", str(exp_dir)])
    (run_dir / "XXQL2601.TMX").write_text("".join(mod_lines), encoding="utf-8")
    
    cmd = [
        sys.executable, "-m", "src.dssat.run_dssat",
        "--param-csv", str(C27_PARAM_CSV.resolve()),
        "--batch", batch_dest.name,
        "--harvest-var", "CHPDT",
        "--input-dir", str(run_dir.resolve()),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(cmd, cwd=run_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    if p.returncode != 0:
        return {"fw": fw, "fnc": fnc, "error": p.stderr}
        
    # Parse PestHarvest.OUT
    ph_path = run_dir / "PestHarvest.OUT"
    sims = {}
    if ph_path.exists():
        with open(ph_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if "TN" in parts and "@CHFPWS@" in parts:
                    tn = int(parts[parts.index("TN") + 1])
                    val = float(parts[parts.index("@CHFPWS@") + 1])
                    sims[tn] = val / 1000.0
                    
    # Clean up run dir to save disk
    shutil.rmtree(run_dir, ignore_errors=True)
    
    res = {"fw": fw, "fnc": fnc}
    for tn in range(1, 13):
        res[f"Y_T{tn}"] = sims.get(tn, np.nan)
        res[f"Err_T{tn}"] = sims.get(tn, np.nan) - OBS_YIELDS.get(tn, np.nan)
    return res

def main():
    print("="*80)
    print("INITIALIZING DENSE 2D WATER & NITROGEN/CARBON GRID SEARCH (26SP)")
    print("="*80)
    
    fw_list = np.round(np.linspace(0.90, 1.05, 16), 2)  # step = 0.01: 16 levels
    fnc_list = np.round(np.linspace(0.70, 1.20, 26), 2) # step = 0.02: 26 levels
    
    print(f"Water scaling range   : [{fw_list[0]:.2f}, {fw_list[-1]:.2f}], step=0.01, count={len(fw_list)}")
    print(f"N & Carbon scaling    : [{fnc_list[0]:.2f}, {fnc_list[-1]:.2f}], step=0.02, count={len(fnc_list)}")
    print(f"Total grid points     : {len(fw_list)} x {len(fnc_list)} = {len(fw_list)*len(fnc_list)}")
    
    num_workers = 6
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Setting up {num_workers} parallel worker sandboxes...")
    for wid in range(num_workers):
        setup_worker(wid)
        
    tasks = []
    idx = 0
    for fw in fw_list:
        for fnc in fnc_list:
            wid = idx % num_workers
            tasks.append((float(fw), float(fnc), wid, idx))
            idx += 1
            
    print(f"Launching {len(tasks)} simulation tasks across {num_workers} processes...")
    t0 = time.time()
    results = []
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(run_grid_task, t): t for t in tasks}
        done_cnt = 0
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            done_cnt += 1
            if done_cnt % 50 == 0 or done_cnt == len(tasks):
                elapsed = time.time() - t0
                rate = done_cnt / elapsed
                print(f"  Progress: {done_cnt}/{len(tasks)} ({done_cnt/len(tasks)*100:.1f}%) | Elapsed: {elapsed:.1f}s | Rate: {rate:.1f} runs/s")
                
    total_time = time.time() - t0
    print(f"\nAll {len(tasks)} runs completed in {total_time:.1f} s ({total_time/60:.2f} min)!")
    
    # Save full grid results
    df_grid = pd.DataFrame(results).sort_values(["fw", "fnc"])
    grid_csv = OUT_DIR / "soil_water_nitrogen_grid_26sp.csv"
    df_grid.to_csv(grid_csv, index=False)
    print(f"Saved full grid dataset to {grid_csv}")
    
    # -------------------------------------------------------------
    # PART 2: Comprehensive Diagnostic Analysis of Response Surfaces
    # -------------------------------------------------------------
    print("\n" + "="*80)
    print("PART 2: OPTIMAL SCALING FACTOR IDENTIFICATION PER TREATMENT")
    print("="*80)
    
    treatment_optimals = []
    for tn in range(1, 13):
        lbl = TRT_LABELS[tn]
        obs = OBS_YIELDS[tn]
        
        # Base (fw=1.0, fnc=1.0)
        base_row = df_grid[(df_grid["fw"] == 1.00) & (df_grid["fnc"] == 1.00)].iloc[0]
        base_sim = base_row[f"Y_T{tn}"]
        base_err = base_row[f"Err_T{tn}"]
        
        # Absolute errors
        sub = df_grid.copy()
        sub["abs_err"] = np.abs(sub[f"Err_T{tn}"])
        best_row = sub.sort_values("abs_err").iloc[0]
        
        treatment_optimals.append({
            "TN": tn,
            "Label": lbl,
            "Obs_t_ha": obs,
            "Base_Sim": base_sim,
            "Base_Err": base_err,
            "Opt_fw": best_row["fw"],
            "Opt_fnc": best_row["fnc"],
            "Opt_Sim": best_row[f"Y_T{tn}"],
            "Opt_Err": best_row[f"Err_T{tn}"],
            "Min_AbsErr": best_row["abs_err"],
        })
        
    df_opt = pd.DataFrame(treatment_optimals)
    print(df_opt.to_string(index=False))
    df_opt.to_csv(OUT_DIR / "per_treatment_optimal_scaling.csv", index=False)
    
    # -------------------------------------------------------------
    # PART 3: Group & Targeted Optimization for Outlier Treatments
    # -------------------------------------------------------------
    print("\n" + "="*80)
    print("PART 3: ABNORMAL TREATMENT GROUP OPTIMIZATION & 26SP R^2 SENSITIVITY")
    print("="*80)
    
    # Check baseline 26SP stats at fw=1.0, fnc=1.0
    o_vec = np.array([OBS_YIELDS[tn] for tn in range(1, 13)])
    base_sims = np.array([base_row[f"Y_T{tn}"] for tn in range(1, 13)])
    r2_base = (np.corrcoef(o_vec, base_sims)[0, 1])**2
    rmse_base = np.sqrt(np.mean((base_sims - o_vec)**2))
    nrmse_base = rmse_base / np.mean(o_vec) * 100.0
    nse_base = 1.0 - np.sum((o_vec - base_sims)**2) / np.sum((o_vec - np.mean(o_vec))**2)
    print(f"C27 Unscaled Baseline: R^2 = {r2_base:.4f}, NRMSE = {nrmse_base:.2f}%, NSE = {nse_base:+.4f}")
    
    # Scenario A: If each abnormal treatment adopts its individual optimum
    # Abnormal treatments: T12 (W1N0), T10 (W1N1), T7 (W3N1), T9 (W3N0), T6 (W1N2)
    abnormal_tns = [12, 10, 7, 9, 6]
    sims_indiv_opt = base_sims.copy()
    for tn in abnormal_tns:
        sims_indiv_opt[tn - 1] = df_opt.loc[df_opt["TN"] == tn, "Opt_Sim"].values[0]
        
    r2_indiv = (np.corrcoef(o_vec, sims_indiv_opt)[0, 1])**2
    rmse_indiv = np.sqrt(np.mean((sims_indiv_opt - o_vec)**2))
    nrmse_indiv = rmse_indiv / np.mean(o_vec) * 100.0
    nse_indiv = 1.0 - np.sum((o_vec - sims_indiv_opt)**2) / np.sum((o_vec - np.mean(o_vec))**2)
    print(f"\nScenario A (Individual Optimum on Outliers): R^2 = {r2_indiv:.4f}, NRMSE = {nrmse_indiv:.2f}%, NSE = {nse_indiv:+.4f}")
    print(f"  Gain in R^2: {r2_indiv - r2_base:+.4f} | NRMSE reduced from {nrmse_base:.2f}% to {nrmse_indiv:.2f}%")
    
    # Scenario B: Coordinated Group Scaling for Abnormal Treatments
    # Notice:
    # W1 deficit group: T12, T10, T6 (all over-predicted due to wet/high-carbon topsoil)
    # What (fw, fnc) jointly minimizes RMSE across T12, T10, T6?
    w1_group_scores = []
    for _, r in df_grid.iterrows():
        errs = [r[f"Err_T{tn}"] for tn in [12, 10, 6]]
        rmse_w1 = np.sqrt(np.mean(np.array(errs)**2))
        w1_group_scores.append({"fw": r["fw"], "fnc": r["fnc"], "rmse_w1": rmse_w1})
    df_w1_group = pd.DataFrame(w1_group_scores).sort_values("rmse_w1")
    best_w1_group = df_w1_group.iloc[0]
    print(f"\nScenario B1 (Optimal Group Scaling for W1 Outliers T12, T10, T6):")
    print(f"  Best Water Scale fw = {best_w1_group['fw']:.2f}, Best N/C Scale fnc = {best_w1_group['fnc']:.2f} (RMSE reduced to {best_w1_group['rmse_w1']:.2f} t/ha)")
    
    # What (fw, fnc) jointly minimizes error for low-N W3 group: T7 (W3N1), T9 (W3N0)?
    w3_group_scores = []
    for _, r in df_grid.iterrows():
        errs = [r[f"Err_T{tn}"] for tn in [7, 9]]
        rmse_w3 = np.sqrt(np.mean(np.array(errs)**2))
        w3_group_scores.append({"fw": r["fw"], "fnc": r["fnc"], "rmse_w3": rmse_w3})
    df_w3_group = pd.DataFrame(w3_group_scores).sort_values("rmse_w3")
    best_w3_group = df_w3_group.iloc[0]
    print(f"Scenario B2 (Optimal Group Scaling for W3 Low-N Outliers T7, T9):")
    print(f"  Best Water Scale fw = {best_w3_group['fw']:.2f}, Best N/C Scale fnc = {best_w3_group['fnc']:.2f} (RMSE reduced to {best_w3_group['rmse_w3']:.2f} t/ha)")

    # -------------------------------------------------------------
    # PART 4: Generate 2D Heatmaps and Publication Figures
    # -------------------------------------------------------------
    print("\n" + "="*80)
    print("PART 4: GENERATING 2D HEATMAPS AND DIAGNOSTIC CHARTS")
    print("="*80)
    
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 10,
        "axes.labelsize": 11,
        "axes.titlesize": 12,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "figure.dpi": 300,
    })
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    
    # Treatments to plot: T12 (W1-N0), T10 (W1-N1), T7 (W3-N1), T9 (W3-N0)
    plot_trts = [
        (12, "W1-N0 (T12): Fresh Fruit Yield Error (t/ha)", axes[0, 0]),
        (10, "W1-N1 (T10): Fresh Fruit Yield Error (t/ha)", axes[0, 1]),
        (7,  "W3-N1 (T7): Fresh Fruit Yield Error (t/ha)", axes[1, 0]),
        (9,  "W3-N0 (T9): Fresh Fruit Yield Error (t/ha)", axes[1, 1]),
    ]
    
    FW, FNC = np.meshgrid(fw_list, fnc_list)
    
    for tn, title, ax in plot_trts:
        obs = OBS_YIELDS[tn]
        lbl = TRT_LABELS[tn]
        
        # Create 2D grid matrix of errors
        err_mat = np.zeros((len(fnc_list), len(fw_list)))
        for i, fnc in enumerate(fnc_list):
            for j, fw in enumerate(fw_list):
                val = df_grid[(df_grid["fw"] == fw) & (df_grid["fnc"] == fnc)][f"Err_T{tn}"].values[0]
                err_mat[i, j] = val
                
        # Diverging colormap centered at 0
        vmax = max(abs(err_mat.min()), abs(err_mat.max()), 5.0)
        c = ax.contourf(fw_list, fnc_list, err_mat, levels=25, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
        
        # Zero error contour line (the perfect fit locus)
        cs = ax.contour(fw_list, fnc_list, err_mat, levels=[0.0], colors="black", linewidths=2.0, linestyles="-")
        ax.clabel(cs, fmt="Zero Err", inline=True, fontsize=9)
        
        # Mark baseline (1.0, 1.0)
        ax.scatter([1.0], [1.0], c="yellow", s=100, edgecolor="black", marker="*", zorder=5, label="C27 Baseline (1.0, 1.0)")
        
        # Mark optimal point
        opt_info = df_opt[df_opt["TN"] == tn].iloc[0]
        ax.scatter([opt_info["Opt_fw"]], [opt_info["Opt_fnc"]], c="lime", s=90, edgecolor="black", marker="o", zorder=5,
                   label=f"Optimum ({opt_info['Opt_fw']:.2f}, {opt_info['Opt_fnc']:.2f})")
        
        cb = plt.colorbar(c, ax=ax, shrink=0.88, pad=0.03)
        cb.set_label("Yield Error = Sim - Obs (t/ha)")
        
        ax.set_xlabel("Water Scaling Factor ($f_w$)")
        ax.set_ylabel("Initial N & Carbon Scaling Factor ($f_{nc}$)")
        ax.set_title(title, fontweight="bold", pad=8)
        ax.grid(True, linestyle=":", alpha=0.4)
        ax.legend(loc="lower left", framealpha=0.9, fontsize=8.5)
        
    plt.tight_layout()
    fig_heatmap_cand = OUT_DIR / "diagnostic_soil_water_nitrogen_heatmaps.png"
    fig_heatmap_art = ARTIFACT_IMG_DIR / "diagnostic_soil_water_nitrogen_heatmaps.png"
    fig.savefig(fig_heatmap_cand, dpi=300)
    fig.savefig(fig_heatmap_art, dpi=300)
    plt.close(fig)
    print(f"Saved 2D heatmap charts to {fig_heatmap_cand} and {fig_heatmap_art}")
    
    # Fig 2: 26SP R^2 and NRMSE response to global scaling
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    
    r2_mat = np.zeros((len(fnc_list), len(fw_list)))
    nrmse_mat = np.zeros((len(fnc_list), len(fw_list)))
    
    for i, fnc in enumerate(fnc_list):
        for j, fw in enumerate(fw_list):
            row = df_grid[(df_grid["fw"] == fw) & (df_grid["fnc"] == fnc)].iloc[0]
            sims = np.array([row[f"Y_T{tn}"] for tn in range(1, 13)])
            r2 = (np.corrcoef(o_vec, sims)[0, 1])**2
            nrmse = np.sqrt(np.mean((sims - o_vec)**2)) / np.mean(o_vec) * 100.0
            r2_mat[i, j] = r2
            nrmse_mat[i, j] = nrmse
            
    c1 = axes[0].contourf(fw_list, fnc_list, r2_mat, levels=20, cmap="viridis")
    axes[0].scatter([1.0], [1.0], c="red", s=100, marker="*", edgecolor="black", label="C27 Baseline")
    cb1 = plt.colorbar(c1, ax=axes[0], shrink=0.88)
    cb1.set_label(r"26SP $R^2$")
    axes[0].set_xlabel("Water Scaling Factor ($f_w$)")
    axes[0].set_ylabel("Initial N & Carbon Scaling Factor ($f_{nc}$)")
    axes[0].set_title(r"A. Global Scaling Impact on 26SP $R^2$", fontweight="bold")
    axes[0].grid(True, linestyle=":", alpha=0.4)
    axes[0].legend(loc="lower left", framealpha=0.9)
    
    c2 = axes[1].contourf(fw_list, fnc_list, nrmse_mat, levels=20, cmap="magma_r")
    axes[1].scatter([1.0], [1.0], c="cyan", s=100, marker="*", edgecolor="black", label="C27 Baseline")
    cb2 = plt.colorbar(c2, ax=axes[1], shrink=0.88)
    cb2.set_label("26SP NRMSE (%)")
    axes[1].set_xlabel("Water Scaling Factor ($f_w$)")
    axes[1].set_ylabel("Initial N & Carbon Scaling Factor ($f_{nc}$)")
    axes[1].set_title("B. Global Scaling Impact on 26SP NRMSE (%)", fontweight="bold")
    axes[1].grid(True, linestyle=":", alpha=0.4)
    axes[1].legend(loc="lower left", framealpha=0.9)
    
    plt.tight_layout()
    fig_global_cand = OUT_DIR / "diagnostic_global_scaling_r2_nrmse.png"
    fig_global_art = ARTIFACT_IMG_DIR / "diagnostic_global_scaling_r2_nrmse.png"
    fig.savefig(fig_global_cand, dpi=300)
    fig.savefig(fig_global_art, dpi=300)
    plt.close(fig)
    print(f"Saved global scaling R^2/NRMSE figure to {fig_global_cand} and {fig_global_art}")
    
    print("\n" + "="*80)
    print("ALL GRID EXPERIMENTS AND DIAGNOSTICS COMPLETED SUCCESSFULLY!")
    print("="*80)

if __name__ == "__main__":
    main()
