#!/usr/bin/env python3
"""Apply Scheme A (Precision Field Soil Water/Nitrogen Calibration) to 26SP and 25SP.
Then execute deterministic simulations across 3 seasons (25SP, 26SP, 25FA) using Candidate C27.
Evaluates:
- Statistical metrics before vs after Scheme A: R^2, RMSE, NRMSE (%), NSE, Mean Bias.
- Treatment-by-treatment residuals and error reduction.
- Water and nitrogen response curves (W2-W1, W3-W1; N1-N0, N2-N0, N3-N0).
- Generates 300 DPI publication-quality diagnostic figures.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dssat.run_dssat import prepare_run_directory

OUT_DIR = PROJECT_ROOT / "workspace" / "experiments" / "scheme_a_evaluation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_IMG_DIR = Path(r"C:\Users\Lidaeus\.gemini\antigravity-cli\brain\06a22b3d-1374-436c-944f-90bd22502f7f\images")
ARTIFACT_IMG_DIR.mkdir(parents=True, exist_ok=True)

C27_PARAM_CSV = PROJECT_ROOT / "workspace/candidates/candidate_c27_real24_root140_sasc092/params.csv"

# Observed yields and metadata
REF_YIELD_CSV = PROJECT_ROOT / "workspace/candidates/candidate_c27_real24_root140_sasc092/all_35_treatments_final_yield.csv"
ref_df = pd.read_csv(REF_YIELD_CSV)

EXP_DIRS = {
    "25SP": PROJECT_ROOT / "data/user/experiments/xxql2501_corrected_20260923",
    "26SP": PROJECT_ROOT / "data/user/experiments/xxql2601_corrected_20260923",
    "25FA": PROJECT_ROOT / "data/user/experiments/xxql2502_corrected_20260923",
}

def modify_tmx_lines_targeted(lines, treatment_scalings):
    """Modify lines of TMX file for specific treatments according to treatment_scalings.
    treatment_scalings: dict {tn: (fw, fn, fc)}
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
                if sa_id in treatment_scalings:
                    _, _, fc = treatment_scalings[sa_id]
                    sabl = int(l[2:8])
                    sadm = float(l[8:14])
                    saoc = float(l[14:20])
                    saoc_new = saoc * fc
                    rest = l[20:]
                    mod_line = f"{sa_id:2d}{sabl:6d}{sadm:6.2f}{saoc_new:6.2f}" + rest
                    out_lines.append(mod_line)
                    continue
            except Exception:
                pass
                
        if in_ic and len(l) > 26 and not l.startswith("@"):
            try:
                ic_id = int(l[:3].strip())
                if ic_id in treatment_scalings:
                    fw, fn, _ = treatment_scalings[ic_id]
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

def run_season_sim(season_name, exp_dir, tmx_lines, batch_file, run_dir):
    """Run DSSAT simulation for a season with modified TMX lines."""
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy genotype templates
    for bf in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
        shutil.copy2(PROJECT_ROOT / "data/templates/genotype" / bf, run_dir / bf)
        
    # Copy experiment files except TMX
    for item in exp_dir.glob("*"):
        if item.is_file() and not item.name.endswith(".TMX") and not item.name.endswith(".OUT"):
            shutil.copy2(item, run_dir / item.name)
            
    # Write modified TMX
    tmx_name = [f for f in exp_dir.glob("*.TMX")][0].name
    (run_dir / tmx_name).write_text("".join(tmx_lines), encoding="utf-8")
    
    # Prepare batch
    batch_dest = prepare_run_directory(run_dir, ["--batch", str(batch_file), "--input-dir", str(run_dir)])
    
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
        print(f"Error in {season_name} run:", p.stderr)
        return {}
        
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
    return sims

def compute_metrics(obs, sim):
    o = np.array(obs)
    s = np.array(sim)
    r = np.corrcoef(o, s)[0, 1] if len(o) > 1 and np.std(o) > 1e-6 and np.std(s) > 1e-6 else np.nan
    r2 = r**2 if not np.isnan(r) else np.nan
    rmse = np.sqrt(np.mean((s - o)**2))
    nrmse = rmse / np.mean(o) * 100.0 if np.mean(o) > 1e-6 else np.nan
    denom = np.sum((o - np.mean(o))**2)
    nse = 1.0 - np.sum((o - s)**2) / denom if denom > 1e-6 else np.nan
    bias = np.mean(s - o)
    bias_pct = bias / np.mean(o) * 100.0 if np.mean(o) > 1e-6 else np.nan
    return {
        "N": len(o),
        "R2": r2,
        "RMSE": rmse,
        "NRMSE": nrmse,
        "NSE": nse,
        "Bias": bias,
        "Bias_pct": bias_pct,
    }

def main():
    print("="*80)
    print("SCHEME A: PRECISION FIELD CALIBRATION & SIMULATION EVALUATION (26SP & 25SP)")
    print("="*80)
    
    # 1. Load optimal scaling files
    opt26_csv = PROJECT_ROOT / "workspace/experiments/soil_water_nitrogen_grid/per_treatment_optimal_scaling.csv"
    opt25_csv = PROJECT_ROOT / "workspace/experiments/soil_water_nitrogen_grid/per_treatment_optimal_scaling_25sp.csv"
    
    if not opt26_csv.exists() or not opt25_csv.exists():
        print(f"Waiting for grid searches to complete: opt26 exists={opt26_csv.exists()}, opt25 exists={opt25_csv.exists()}")
        return
        
    df_opt26 = pd.read_csv(opt26_csv)
    df_opt25 = pd.read_csv(opt25_csv)
    
    # 2. Define Scheme A scalings
    # 26SP Scheme A: T12 (W1N0) and T9 (W3N0)
    row_t12 = df_opt26[df_opt26["TN"] == 12].iloc[0]
    row_t9 = df_opt26[df_opt26["TN"] == 9].iloc[0]
    scalings_26sp = {
        12: (float(row_t12["Opt_fw"]), float(row_t12["Opt_fnc"]), float(row_t12["Opt_fnc"])),
        9:  (float(row_t9["Opt_fw"]), float(row_t9["Opt_fnc"]), float(row_t9["Opt_fnc"])),
    }
    print(f"26SP Scheme A adjustments: {scalings_26sp}")
    
    # 25SP Scheme A: Three N0 treatments with field measurement heterogeneity (T5 W3N0, T9 W2N0, T13 W1N0)
    scalings_25sp = {}
    for _, r in df_opt25.iterrows():
        tn = int(r["TN"])
        if tn in [5, 9, 13]: # Three N0 treatments
            scalings_25sp[tn] = (float(r["Opt_fw"]), float(r["Opt_fnc"]), float(r["Opt_fnc"]))
    print(f"25SP Scheme A adjustments: {scalings_25sp}")
    
    # 3. Setup run directories
    scratch_runs = PROJECT_ROOT / "scratch" / "scheme_a_sims"
    if scratch_runs.exists():
        shutil.rmtree(scratch_runs)
    scratch_runs.mkdir(parents=True, exist_ok=True)
    
    # 4. Run DSSAT simulations for 25SP and 26SP
    # 26SP simulation
    lines_26 = (EXP_DIRS["26SP"] / "XXQL2601.TMX").read_text(encoding="utf-8").splitlines(keepends=True)
    mod_lines_26 = modify_tmx_lines_targeted(lines_26, scalings_26sp)
    batch_26 = EXP_DIRS["26SP"] / "DSSBatch.v48"
    if not batch_26.exists():
        # create batch for 26
        b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
        for tn in range(1, 13):
            b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
        batch_26 = scratch_runs / "DSSBatch_26SP_all.v48"
        batch_26.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")
        
    print("\nRunning 26SP simulation under Scheme A...")
    sims_26 = run_season_sim("26SP", EXP_DIRS["26SP"], mod_lines_26, batch_26, scratch_runs / "run_26sp")
    
    # 25SP simulation
    lines_25 = (EXP_DIRS["25SP"] / "XXQL2501.TMX").read_text(encoding="utf-8").splitlines(keepends=True)
    mod_lines_25 = modify_tmx_lines_targeted(lines_25, scalings_25sp)
    batch_25 = EXP_DIRS["25SP"] / "DSSBatch.v48"
    
    print("Running 25SP simulation under Scheme A...")
    sims_25 = run_season_sim("25SP", EXP_DIRS["25SP"], mod_lines_25, batch_25, scratch_runs / "run_25sp")
    
    # Also get 25FA baseline
    lines_fa = (EXP_DIRS["25FA"] / "XXQL2502.TMX").read_text(encoding="utf-8").splitlines(keepends=True)
    batch_fa = EXP_DIRS["25FA"] / "DSSBatch.v48"
    if not batch_fa.exists():
        bfa_lines = ["$BATCH(SEASON)", "! 2025 Autumn all 12 treatments"]
        for tn in range(1, 13):
            bfa_lines.append(f"XXQL2502.TMX                                                                                    {tn:2d}      1      0      0      0")
        batch_fa = scratch_runs / "DSSBatch_25FA_all.v48"
        batch_fa.write_text("\n".join(bfa_lines) + "\n", encoding="utf-8")
    print("Running 25FA baseline simulation...")
    sims_fa = run_season_sim("25FA", EXP_DIRS["25FA"], lines_fa, batch_fa, scratch_runs / "run_25fa")
    
    # 5. Compile full 35-treatment comparison
    records = []
    for _, row in ref_df.iterrows():
        season = row["season"]
        tn = int(row["treatment"])
        obs = float(row["obs_t_ha"])
        base_sim = float(row["sim_t_ha"])
        base_err = float(row["err_t_ha"])
        
        if season == "26SP":
            scheme_a_sim = sims_26.get(tn, base_sim)
        elif season == "25SP":
            scheme_a_sim = sims_25.get(tn, base_sim)
        else:
            scheme_a_sim = sims_fa.get(tn, base_sim)
            
        scheme_a_err = scheme_a_sim - obs
        err_reduction = abs(base_err) - abs(scheme_a_err)
        
        records.append({
            "season": season,
            "excode": row["excode"],
            "treatment": tn,
            "treatment_label": row["treatment_label"],
            "water": row["water"],
            "nitro": row["nitro"],
            "obs_t_ha": obs,
            "base_sim_t_ha": base_sim,
            "base_err_t_ha": base_err,
            "scheme_a_sim_t_ha": scheme_a_sim,
            "scheme_a_err_t_ha": scheme_a_err,
            "scheme_a_rel_err_pct": scheme_a_err / obs * 100.0,
            "err_reduction_t_ha": err_reduction,
        })
        
    df_all = pd.DataFrame(records)
    all_csv = OUT_DIR / "scheme_a_35_treatments_final_yield.csv"
    df_all.to_csv(all_csv, index=False)
    print(f"\nSaved all 35 treatments Scheme A results to {all_csv}")
    
    # 6. Compute and display metrics table
    print("\n" + "="*80)
    print("METRICS SUMMARY: BEFORE (BASE C27) VS AFTER (SCHEME A)")
    print("="*80)
    
    metrics_list = []
    for season in ["25SP", "26SP", "25FA", "All"]:
        if season == "All":
            sub = df_all
        else:
            sub = df_all[df_all["season"] == season]
            
        m_base = compute_metrics(sub["obs_t_ha"], sub["base_sim_t_ha"])
        m_scheme = compute_metrics(sub["obs_t_ha"], sub["scheme_a_sim_t_ha"])
        
        metrics_list.append({
            "Season": season,
            "N": m_base["N"],
            "Base_R2": m_base["R2"],
            "SchemeA_R2": m_scheme["R2"],
            "R2_Gain": m_scheme["R2"] - m_base["R2"],
            "Base_RMSE": m_base["RMSE"],
            "SchemeA_RMSE": m_scheme["RMSE"],
            "Base_NRMSE": m_base["NRMSE"],
            "SchemeA_NRMSE": m_scheme["NRMSE"],
            "Base_NSE": m_base["NSE"],
            "SchemeA_NSE": m_scheme["NSE"],
        })
        
    df_metrics = pd.DataFrame(metrics_list)
    print(df_metrics.to_string(index=False))
    df_metrics.to_csv(OUT_DIR / "scheme_a_metrics_summary.csv", index=False)
    
    # 7. Print treatment-level details for Spring seasons
    for s in ["25SP", "26SP"]:
        print("\n" + "-"*80)
        print(f"TREATMENT COMPARISON FOR {s}:")
        print("-"*80)
        sub = df_all[df_all["season"] == s][["treatment", "treatment_label", "obs_t_ha", "base_sim_t_ha", "base_err_t_ha", "scheme_a_sim_t_ha", "scheme_a_err_t_ha", "scheme_a_rel_err_pct", "err_reduction_t_ha"]]
        print(sub.to_string(index=False))
        
    # 8. Generate Publication-Quality Figures
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 10,
        "axes.labelsize": 11,
        "axes.titlesize": 12,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "figure.dpi": 300,
    })
    
    # Fig 1: 1:1 Scatter Plot Before vs After Scheme A
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # Panel A: 25SP
    sub25 = df_all[df_all["season"] == "25SP"]
    m25_b = compute_metrics(sub25["obs_t_ha"], sub25["base_sim_t_ha"])
    m25_a = compute_metrics(sub25["obs_t_ha"], sub25["scheme_a_sim_t_ha"])
    
    axes[0].plot([50, 75], [50, 75], "k--", alpha=0.6, label="1:1 Reference Line")
    axes[0].scatter(sub25["obs_t_ha"], sub25["base_sim_t_ha"], color="gray", alpha=0.5, s=70, marker="o", label=f"Base C27 ($R^2$={m25_b['R2']:.3f}, NRMSE={m25_b['NRMSE']:.2f}%)")
    axes[0].scatter(sub25["obs_t_ha"], sub25["scheme_a_sim_t_ha"], color="#1f77b4", edgecolor="black", s=90, marker="o", label=f"Scheme A ($R^2$={m25_a['R2']:.3f}, NRMSE={m25_a['NRMSE']:.2f}%)")
    for _, r in sub25.iterrows():
        axes[0].annotate(r["treatment_label"], (r["obs_t_ha"], r["scheme_a_sim_t_ha"]), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=8)
    axes[0].set_xlabel("Observed Fresh Fruit Yield (t/ha)")
    axes[0].set_ylabel("Simulated Fresh Fruit Yield (t/ha)")
    axes[0].set_title(f"A. 2025 Spring (25SP) 1:1 Yield Fit\n$R^2$: {m25_b['R2']:.3f} -> {m25_a['R2']:.3f} | NRMSE: {m25_b['NRMSE']:.2f}% -> {m25_a['NRMSE']:.2f}% | NSE: {m25_b['NSE']:+.3f} -> {m25_a['NSE']:+.3f}", fontweight="bold")
    axes[0].grid(True, linestyle=":", alpha=0.4)
    axes[0].legend(loc="upper left", framealpha=0.9)
    axes[0].set_xlim(52, 76)
    axes[0].set_ylim(52, 76)
    
    # Panel B: 26SP
    sub26 = df_all[df_all["season"] == "26SP"]
    m26_b = compute_metrics(sub26["obs_t_ha"], sub26["base_sim_t_ha"])
    m26_a = compute_metrics(sub26["obs_t_ha"], sub26["scheme_a_sim_t_ha"])
    
    axes[1].plot([45, 78], [45, 78], "k--", alpha=0.6, label="1:1 Reference Line")
    axes[1].scatter(sub26["obs_t_ha"], sub26["base_sim_t_ha"], color="gray", alpha=0.5, s=70, marker="s", label=f"Base C27 ($R^2$={m26_b['R2']:.3f}, NRMSE={m26_b['NRMSE']:.2f}%)")
    axes[1].scatter(sub26["obs_t_ha"], sub26["scheme_a_sim_t_ha"], color="#d62728", edgecolor="black", s=90, marker="s", label=f"Scheme A ($R^2$={m26_a['R2']:.3f}, NRMSE={m26_a['NRMSE']:.2f}%)")
    for _, r in sub26.iterrows():
        axes[1].annotate(r["treatment_label"], (r["obs_t_ha"], r["scheme_a_sim_t_ha"]), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=8)
    axes[1].set_xlabel("Observed Fresh Fruit Yield (t/ha)")
    axes[1].set_ylabel("Simulated Fresh Fruit Yield (t/ha)")
    axes[1].set_title(f"B. 2026 Spring (26SP) 1:1 Yield Fit\n$R^2$: {m26_b['R2']:.3f} -> {m26_a['R2']:.3f} | NRMSE: {m26_b['NRMSE']:.2f}% -> {m26_a['NRMSE']:.2f}% | NSE: {m26_b['NSE']:+.3f} -> {m26_a['NSE']:+.3f}", fontweight="bold")
    axes[1].grid(True, linestyle=":", alpha=0.4)
    axes[1].legend(loc="upper left", framealpha=0.9)
    axes[1].set_xlim(48, 78)
    axes[1].set_ylim(48, 78)
    
    plt.tight_layout()
    fig1_path = OUT_DIR / "diagnostic_scheme_a_1to1_scatter.png"
    fig.savefig(fig1_path, dpi=300)
    fig.savefig(ARTIFACT_IMG_DIR / "diagnostic_scheme_a_1to1_scatter.png", dpi=300)
    plt.close(fig)
    print(f"Saved 1:1 scatter plot to {fig1_path}")
    
    # Fig 2: Treatment Bar Comparison for 25SP & 26SP
    fig, axes = plt.subplots(2, 1, figsize=(14, 9))
    
    # 25SP bars
    x25 = np.arange(len(sub25))
    width = 0.28
    axes[0].bar(x25 - width, sub25["obs_t_ha"], width, label="Observed", color="#2ca02c", alpha=0.85, edgecolor="black")
    axes[0].bar(x25, sub25["base_sim_t_ha"], width, label="Base C27 Sim", color="#7f7f7f", alpha=0.7, edgecolor="black")
    axes[0].bar(x25 + width, sub25["scheme_a_sim_t_ha"], width, label="Scheme A Sim", color="#1f77b4", alpha=0.9, edgecolor="black")
    axes[0].set_xticks(x25)
    axes[0].set_xticklabels(sub25["treatment_label"], fontweight="bold")
    axes[0].set_ylabel("Yield (t/ha)")
    axes[0].set_title("A. 2025 Spring (25SP) Yield by Treatment", fontweight="bold")
    axes[0].set_ylim(45, 80)
    axes[0].grid(True, axis="y", linestyle=":", alpha=0.4)
    axes[0].legend(loc="upper right", framealpha=0.9)
    
    # 26SP bars
    x26 = np.arange(len(sub26))
    axes[1].bar(x26 - width, sub26["obs_t_ha"], width, label="Observed", color="#2ca02c", alpha=0.85, edgecolor="black")
    axes[1].bar(x26, sub26["base_sim_t_ha"], width, label="Base C27 Sim", color="#7f7f7f", alpha=0.7, edgecolor="black")
    axes[1].bar(x26 + width, sub26["scheme_a_sim_t_ha"], width, label="Scheme A Sim", color="#d62728", alpha=0.9, edgecolor="black")
    axes[1].set_xticks(x26)
    axes[1].set_xticklabels(sub26["treatment_label"], fontweight="bold")
    axes[1].set_ylabel("Yield (t/ha)")
    axes[1].set_title("B. 2026 Spring (26SP) Yield by Treatment", fontweight="bold")
    axes[1].set_ylim(45, 80)
    axes[1].grid(True, axis="y", linestyle=":", alpha=0.4)
    axes[1].legend(loc="upper right", framealpha=0.9)
    
    plt.tight_layout()
    fig2_path = OUT_DIR / "diagnostic_scheme_a_treatment_bars.png"
    fig.savefig(fig2_path, dpi=300)
    fig.savefig(ARTIFACT_IMG_DIR / "diagnostic_scheme_a_treatment_bars.png", dpi=300)
    plt.close(fig)
    print(f"Saved treatment bars to {fig2_path}")
    
    # Fig 3: Water & Nitrogen Response Curves (25SP & 26SP)
    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    
    # 25SP Nitrogen response
    for w, col, ls in [("W1", "#2ca02c", ":"), ("W2", "#1f77b4", "--"), ("W3", "#d62728", "-")]:
        sub_w = sub25[sub25["water"] == w].sort_values("nitro")
        if not sub_w.empty:
            axes[0, 0].plot(sub_w["nitro"], sub_w["obs_t_ha"], marker="o", color=col, linestyle=ls, alpha=0.6, label=f"Obs ({w})")
            axes[0, 0].plot(sub_w["nitro"], sub_w["scheme_a_sim_t_ha"], marker="s", color=col, linestyle="-", linewidth=2.0, label=f"Sim Scheme A ({w})")
    axes[0, 0].set_xlabel("Nitrogen Level")
    axes[0, 0].set_ylabel("Fresh Fruit Yield (t/ha)")
    axes[0, 0].set_title("A. 2025 Spring (25SP) Nitrogen Response Curves", fontweight="bold")
    axes[0, 0].grid(True, linestyle=":", alpha=0.4)
    axes[0, 0].legend(loc="lower right", framealpha=0.9, fontsize=8)
    axes[0, 0].set_ylim(48, 76)
    
    # 25SP Water response
    for n, col, ls in [("N0", "#7f7f7f", ":"), ("N1", "#1f77b4", "--"), ("N2", "#ff7f0e", "-."), ("N3", "#d62728", "-")]:
        sub_n = sub25[sub25["nitro"] == n].sort_values("water")
        if not sub_n.empty:
            axes[0, 1].plot(sub_n["water"], sub_n["obs_t_ha"], marker="o", color=col, linestyle=ls, alpha=0.6, label=f"Obs ({n})")
            axes[0, 1].plot(sub_n["water"], sub_n["scheme_a_sim_t_ha"], marker="s", color=col, linestyle="-", linewidth=2.0, label=f"Sim Scheme A ({n})")
    axes[0, 1].set_xlabel("Water Level")
    axes[0, 1].set_ylabel("Fresh Fruit Yield (t/ha)")
    axes[0, 1].set_title("B. 2025 Spring (25SP) Water Response Curves", fontweight="bold")
    axes[0, 1].grid(True, linestyle=":", alpha=0.4)
    axes[0, 1].legend(loc="lower right", framealpha=0.9, fontsize=8)
    axes[0, 1].set_ylim(48, 76)
    
    # 26SP Nitrogen response
    for w, col, ls in [("W1", "#2ca02c", ":"), ("W2", "#1f77b4", "--"), ("W3", "#d62728", "-")]:
        sub_w = sub26[sub26["water"] == w].sort_values("nitro")
        if not sub_w.empty:
            axes[1, 0].plot(sub_w["nitro"], sub_w["obs_t_ha"], marker="o", color=col, linestyle=ls, alpha=0.6, label=f"Obs ({w})")
            axes[1, 0].plot(sub_w["nitro"], sub_w["scheme_a_sim_t_ha"], marker="s", color=col, linestyle="-", linewidth=2.0, label=f"Sim Scheme A ({w})")
    axes[1, 0].set_xlabel("Nitrogen Level")
    axes[1, 0].set_ylabel("Fresh Fruit Yield (t/ha)")
    axes[1, 0].set_title("C. 2026 Spring (26SP) Nitrogen Response Curves", fontweight="bold")
    axes[1, 0].grid(True, linestyle=":", alpha=0.4)
    axes[1, 0].legend(loc="lower right", framealpha=0.9, fontsize=8)
    axes[1, 0].set_ylim(48, 76)
    
    # 26SP Water response
    for n, col, ls in [("N0", "#7f7f7f", ":"), ("N1", "#1f77b4", "--"), ("N2", "#ff7f0e", "-."), ("N3", "#d62728", "-")]:
        sub_n = sub26[sub26["nitro"] == n].sort_values("water")
        if not sub_n.empty:
            axes[1, 1].plot(sub_n["water"], sub_n["obs_t_ha"], marker="o", color=col, linestyle=ls, alpha=0.6, label=f"Obs ({n})")
            axes[1, 1].plot(sub_n["water"], sub_n["scheme_a_sim_t_ha"], marker="s", color=col, linestyle="-", linewidth=2.0, label=f"Sim Scheme A ({n})")
    axes[1, 1].set_xlabel("Water Level")
    axes[1, 1].set_ylabel("Fresh Fruit Yield (t/ha)")
    axes[1, 1].set_title("D. 2026 Spring (26SP) Water Response Curves", fontweight="bold")
    axes[1, 1].grid(True, linestyle=":", alpha=0.4)
    axes[1, 1].legend(loc="lower right", framealpha=0.9, fontsize=8)
    axes[1, 1].set_ylim(48, 76)
    
    plt.tight_layout()
    fig3_path = OUT_DIR / "diagnostic_scheme_a_water_nitrogen_response.png"
    fig.savefig(fig3_path, dpi=300)
    fig.savefig(ARTIFACT_IMG_DIR / "diagnostic_scheme_a_water_nitrogen_response.png", dpi=300)
    plt.close(fig)
    print(f"Saved response curves to {fig3_path}")
    
    print("\n" + "="*80)
    print("SCHEME A EVALUATION AND PLOTTING FINISHED SUCCESSFULLY!")
    print("="*80)

if __name__ == "__main__":
    main()
