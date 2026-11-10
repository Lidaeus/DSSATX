#!/usr/bin/env python3
"""Finalize Candidates C28 and C29:
1. Updates all_candidates_3season_benchmark_matrix.csv
2. Generates publication-quality diagnostic figures for C28 and C29:
   - 1:1 Scatter Plot
   - 35-Treatment Yield Comparison Bars
   - Water & Nitrogen Response Ladders
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

PROJECT_ROOT = Path("D:/Tomato_Cal")
CAND_DIR = PROJECT_ROOT / "workspace" / "candidates"
ARTIFACT_IMG_DIR = Path(r"C:\Users\Lidaeus\.gemini\antigravity-cli\brain\06a22b3d-1374-436c-944f-90bd22502f7f\images")
ARTIFACT_IMG_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 9,
    "figure.dpi": 300,
})

def update_benchmark_matrix():
    matrix_csv = CAND_DIR / "all_candidates_3season_benchmark_matrix.csv"
    mat_df = pd.read_csv(matrix_csv) if matrix_csv.exists() else pd.DataFrame()
    
    candidates = [
        ("C28_real105_final_spring_precision", "candidate_c28_real105_final_spring_precision"),
        ("C29_real185_final_water_fidelity", "candidate_c29_real185_final_water_fidelity"),
    ]
    
    for c_tag, c_folder in candidates:
        mf_path = CAND_DIR / c_folder / "candidate_manifest.json"
        with open(mf_path, "r", encoding="utf-8") as f:
            mf = json.load(f)
            
        m_2sp = mf["metrics"]["twospring_23trt"]
        m_25 = mf["metrics"]["25sp_11trt"]
        m_26 = mf["metrics"]["26sp_12trt"]
        m_fa = mf["metrics"]["25fa_12trt"]
        m_grand = mf["metrics"]["grand_35trt"]
        
        y_df = pd.read_csv(CAND_DIR / c_folder / "all_35_treatments_final_yield.csv")
        sp26 = y_df[y_df["season"] == "26SP"]
        max_26sp = float(sp26["sim_t_ha"].max())
        ceiling_passed = bool(max_26sp <= 76.5)
        
        new_row = {
            "candidate": c_tag,
            "Spring_NRMSE_pct": m_2sp["nrmse_pct"],
            "Spring_d": m_2sp["d_index"],
            "Spring_R2": m_2sp["r2"],
            "Spring_NSE": m_2sp["nse"],
            "25SP_NRMSE_pct": m_25["nrmse_pct"],
            "25SP_d": m_25["d_index"],
            "25SP_NSE": m_25["nse"],
            "26SP_NRMSE_pct": m_26["nrmse_pct"],
            "26SP_d": m_26["d_index"],
            "26SP_NSE": m_26["nse"],
            "25FA_NRMSE_pct": m_fa["nrmse_pct"],
            "25FA_d": m_fa["d_index"],
            "25FA_NSE": m_fa["nse"],
            "Grand_NRMSE_pct": m_grand["nrmse_pct"],
            "Grand_d": m_grand["d_index"],
            "Grand_NSE": m_grand["nse"],
            "Max_26SP_Y_t_ha": max_26sp,
            "Ceiling_Passed": ceiling_passed,
            "Delta_Y_26W2_kg": 0.0,
            "Delta_Y_26W1_kg": 0.0,
            "Delta_Y_25W1_kg": 0.0,
            "W1_N_ratio_pct": 50.0,
        }
        
        mat_df = mat_df[mat_df["candidate"] != c_tag]
        mat_df = pd.concat([mat_df, pd.DataFrame([new_row])], ignore_index=True)
        
    mat_df.to_csv(matrix_csv, index=False)
    print(f"Updated benchmark matrix at {matrix_csv}")

def generate_diagnostic_plots(c_id, c_folder, prefix):
    cdir = CAND_DIR / c_folder
    df_all = pd.read_csv(cdir / "all_35_treatments_final_yield.csv")
    
    # Add water and nitro columns if not present
    if "water" not in df_all.columns:
        df_all["water"] = df_all["treatment_label"].apply(lambda s: s[:2] if len(s)>=2 else "")
        df_all["nitro"] = df_all["treatment_label"].apply(lambda s: s[2:] if len(s)>=4 else "")
        
    sp25 = df_all[df_all["season"] == "25SP"].copy()
    sp26 = df_all[df_all["season"] == "26SP"].copy()
    fa25 = df_all[df_all["season"] == "25FA"].copy()
    
    with open(cdir / "candidate_manifest.json", "r", encoding="utf-8") as f:
        mf = json.load(f)
    st25 = mf["metrics"]["25sp_11trt"]
    st26 = mf["metrics"]["26sp_12trt"]
    stfa = mf["metrics"]["25fa_12trt"]
    
    # 1. 1:1 Scatter Plot
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    season_configs = [
        ("25SP", "2025 Spring (Calibration, 11 trts)", sp25, st25, [45, 80]),
        ("26SP", "2026 Spring (Calibration, 12 trts)", sp26, st26, [45, 80]),
        ("25FA", "2025 Autumn (Blind Validation, 12 trts)", fa25, stfa, [8, 24]),
    ]
    
    for ax, (sname, title, df_sub, st, lims) in zip(axes, season_configs):
        o = df_sub["obs_t_ha"].to_numpy()
        s = df_sub["sim_t_ha"].to_numpy()
        
        ax.plot(lims, lims, "k-", lw=1.2, label="1:1 line", zorder=2)
        ax.plot(lims, [lims[0]*1.1, lims[1]*1.1], "k--", lw=0.8, alpha=0.6, label="±10% error", zorder=1)
        ax.plot(lims, [lims[0]*0.9, lims[1]*0.9], "k--", lw=0.8, alpha=0.6, zorder=1)
        ax.fill_between(lims, [lims[0]*0.9, lims[1]*0.9], [lims[0]*1.1, lims[1]*1.1], color="gray", alpha=0.08)
        
        color_map = {"W3": "#2b5c8f", "W2": "#2ca02c", "W1": "#d62728", "CK": "#9467bd"}
        marker_map = {"N3": "o", "N2": "s", "N1": "^", "N0": "D"}
        
        for _, r in df_sub.iterrows():
            c = color_map.get(r["water"], "#333333")
            m = marker_map.get(r["nitro"], "o")
            ax.scatter(r["obs_t_ha"], r["sim_t_ha"], c=c, marker=m, s=55, edgecolor="black", lw=0.7, zorder=4)
            ax.annotate(r["treatment_label"], (r["obs_t_ha"], r["sim_t_ha"]), xytext=(3, 3), textcoords="offset points", fontsize=7, alpha=0.85)
            
        if len(o) > 2 and np.std(o) > 1e-4:
            fit = np.polyfit(o, s, 1)
            x_fit = np.linspace(lims[0], lims[1], 100)
            ax.plot(x_fit, np.polyval(fit, x_fit), "r-.", lw=1.2, alpha=0.8, label=f"Fit (slope={fit[0]:.2f})", zorder=3)
            
        ax.set_xlim(lims)
        ax.set_ylim(lims)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("Observed Yield (t/ha)")
        ax.set_ylabel("Simulated Yield (t/ha)")
        ax.set_title(title, fontweight="bold", pad=8)
        ax.grid(True, linestyle=":", alpha=0.5)
        
        stat_text = (
            f"$R^2$ = {st['r2']:.3f}\n"
            f"NRMSE = {st['nrmse_pct']:.2f}%\n"
            f"NSE = {st['nse']:+.3f}\n"
            f"d = {st['d_index']:.3f}\n"
            f"Bias = {st['bias_t_ha']:+.2f} t/ha"
        )
        ax.text(0.04, 0.96, stat_text, transform=ax.transAxes, verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.9, edgecolor="#cccccc"), fontsize=8.5)
                
    plt.tight_layout()
    f1_cand = cdir / f"diagnostic_{prefix}_1to1_scatter.png"
    f1_art = ARTIFACT_IMG_DIR / f"diagnostic_{prefix}_1to1_scatter.png"
    fig.savefig(f1_cand, dpi=300)
    fig.savefig(f1_art, dpi=300)
    plt.close(fig)
    print(f"Saved 1:1 scatter plot: {f1_cand}")
    
    # 2. Bar Chart
    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=False)
    for ax, sname, title, df_sub in zip(axes, ["25SP", "26SP", "25FA"],
                                        ["2025 Spring Yield Comparison", "2026 Spring Yield Comparison", "2025 Autumn Yield Comparison (Blind Validation)"],
                                        [sp25, sp26, fa25]):
        x = np.arange(len(df_sub))
        w = 0.38
        ax.bar(x - w/2, df_sub["obs_t_ha"], w, label="Observed", color="#4575b4", edgecolor="black", lw=0.6, alpha=0.85)
        ax.bar(x + w/2, df_sub["sim_t_ha"], w, label=f"{c_id} Simulated", color="#f46d43", edgecolor="black", lw=0.6, alpha=0.85)
        
        for i, r in enumerate(df_sub.itertuples()):
            err = r.err_t_ha
            col = "#2ca02c" if abs(err) < 3.0 else ("#d62728" if err > 0 else "#1f77b4")
            max_y = max(r.obs_t_ha, r.sim_t_ha)
            ax.text(i, max_y + 1.2, f"{err:+.1f}", ha="center", va="bottom", fontsize=7.5, color=col, fontweight="bold")
            
        ax.set_xticks(x)
        ax.set_xticklabels([f"{r.treatment_label} (T{r.treatment})" for r in df_sub.itertuples()], rotation=0, fontsize=8.5)
        ax.set_ylabel("Yield (t/ha)")
        ax.set_title(title, fontweight="bold", pad=6)
        y_max = df_sub[["obs_t_ha", "sim_t_ha"]].max().max() * 1.15
        ax.set_ylim(0, y_max)
        ax.grid(axis="y", linestyle=":", alpha=0.5)
        ax.legend(loc="upper right", framealpha=0.9)
        
    plt.tight_layout()
    f2_cand = cdir / f"diagnostic_{prefix}_treatment_bars.png"
    f2_art = ARTIFACT_IMG_DIR / f"diagnostic_{prefix}_treatment_bars.png"
    fig.savefig(f2_cand, dpi=300)
    fig.savefig(f2_art, dpi=300)
    plt.close(fig)
    print(f"Saved bar chart: {f2_cand}")
    
    # 3. Water and Nitrogen Response
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    nitro_order = ["N0", "N1", "N2", "N3"]
    n_x = np.arange(4)
    
    # Panel A: 25SP
    ax1 = axes[0]
    sp25_w3 = sp25[sp25["water"] == "W3"].set_index("nitro")
    sp25_w1 = sp25[sp25["water"] == "W1"].set_index("nitro")
    
    obs_25_w3 = [sp25_w3.loc[n, "obs_t_ha"] if n in sp25_w3.index else np.nan for n in nitro_order]
    sim_25_w3 = [sp25_w3.loc[n, "sim_t_ha"] if n in sp25_w3.index else np.nan for n in nitro_order]
    obs_25_w1 = [sp25_w1.loc[n, "obs_t_ha"] if n in sp25_w1.index else np.nan for n in nitro_order]
    sim_25_w1 = [sp25_w1.loc[n, "sim_t_ha"] if n in sp25_w1.index else np.nan for n in nitro_order]
    
    ax1.plot(n_x, obs_25_w3, "o--", color="#2b5c8f", lw=1.2, label="25SP W3 Obs", alpha=0.8)
    ax1.plot(n_x, sim_25_w3, "s-", color="#2b5c8f", lw=2.0, label=f"25SP W3 Sim ({c_id})")
    ax1.plot(n_x, obs_25_w1, "^--", color="#d62728", lw=1.2, label="25SP W1 Obs", alpha=0.8)
    ax1.plot(n_x, sim_25_w1, "d-", color="#d62728", lw=2.0, label=f"25SP W1 Sim ({c_id})")
    
    ax1.set_xticks(n_x)
    ax1.set_xticklabels(nitro_order)
    ax1.set_xlabel("Nitrogen Level")
    ax1.set_ylabel("Fresh Fruit Yield (t/ha)")
    ax1.set_title("25SP Nitrogen Response Ladder", fontweight="bold")
    ax1.grid(True, linestyle=":", alpha=0.5)
    ax1.legend(loc="lower right", framealpha=0.9)
    
    # Panel B: 26SP
    ax2 = axes[1]
    sp26_w3 = sp26[sp26["water"] == "W3"].set_index("nitro")
    sp26_w2 = sp26[sp26["water"] == "W2"].set_index("nitro")
    sp26_w1 = sp26[sp26["water"] == "W1"].set_index("nitro")
    
    obs_26_w3 = [sp26_w3.loc[n, "obs_t_ha"] if n in sp26_w3.index else np.nan for n in nitro_order]
    sim_26_w3 = [sp26_w3.loc[n, "sim_t_ha"] if n in sp26_w3.index else np.nan for n in nitro_order]
    obs_26_w2 = [sp26_w2.loc[n, "obs_t_ha"] if n in sp26_w2.index else np.nan for n in nitro_order]
    sim_26_w2 = [sp26_w2.loc[n, "sim_t_ha"] if n in sp26_w2.index else np.nan for n in nitro_order]
    obs_26_w1 = [sp26_w1.loc[n, "obs_t_ha"] if n in sp26_w1.index else np.nan for n in nitro_order]
    sim_26_w1 = [sp26_w1.loc[n, "sim_t_ha"] if n in sp26_w1.index else np.nan for n in nitro_order]
    
    ax2.plot(n_x, obs_26_w3, "o--", color="#2b5c8f", lw=1.2, label="26SP W3 Obs", alpha=0.8)
    ax2.plot(n_x, sim_26_w3, "s-", color="#2b5c8f", lw=2.0, label=f"26SP W3 Sim ({c_id})")
    ax2.plot(n_x, obs_26_w2, "^--", color="#2ca02c", lw=1.2, label="26SP W2 Obs", alpha=0.8)
    ax2.plot(n_x, sim_26_w2, "p-", color="#2ca02c", lw=2.0, label=f"26SP W2 Sim ({c_id})")
    ax2.plot(n_x, obs_26_w1, "v--", color="#d62728", lw=1.2, label="26SP W1 Obs", alpha=0.8)
    ax2.plot(n_x, sim_26_w1, "d-", color="#d62728", lw=2.0, label=f"26SP W1 Sim ({c_id})")
    
    ax2.set_xticks(n_x)
    ax2.set_xticklabels(nitro_order)
    ax2.set_xlabel("Nitrogen Level")
    ax2.set_ylabel("Fresh Fruit Yield (t/ha)")
    ax2.set_title("26SP Nitrogen & Water Ladders", fontweight="bold")
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.legend(loc="lower right", framealpha=0.9)
    
    plt.tight_layout()
    f3_cand = cdir / f"diagnostic_{prefix}_water_nitrogen_response.png"
    f3_art = ARTIFACT_IMG_DIR / f"diagnostic_{prefix}_water_nitrogen_response.png"
    fig.savefig(f3_cand, dpi=300)
    fig.savefig(f3_art, dpi=300)
    plt.close(fig)
    print(f"Saved response curves: {f3_cand}")

if __name__ == "__main__":
    update_benchmark_matrix()
    generate_diagnostic_plots("C28", "candidate_c28_real105_final_spring_precision", "c28")
    generate_diagnostic_plots("C29", "candidate_c29_real185_final_water_fidelity", "c29")
    print("All diagnostic plots and benchmark matrices finalized successfully!")
