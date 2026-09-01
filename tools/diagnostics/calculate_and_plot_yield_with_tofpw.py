#!/usr/bin/env python3
"""Calculate metrics and generate comprehensive diagnostic figures for:
'What if TOFPW (on-plant fruit biomass) is counted towards the final harvest yield in best125?'
Outputs saved to: D:/Tomato_Cal/figture/e02_formal_v40_3x_yield_best125_20260830/tofpw_impact_analysis/
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DET_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v40_3x_yield_200x4_20260830/best_member_125_two_season_deterministic_20260830"
FIG_OUT_DIR = PROJECT_ROOT / "figture/e02_formal_v40_3x_yield_best125_20260830/tofpw_impact_analysis"
FIG_OUT_DIR.mkdir(parents=True, exist_ok=True)

# Use clean English labels to ensure universal rendering compatibility
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Helvetica"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 10
plt.rcParams["axes.labelsize"] = 11
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["xtick.labelsize"] = 9
plt.rcParams["ytick.labelsize"] = 9
plt.rcParams["legend.fontsize"] = 9
plt.rcParams["figure.titlesize"] = 13


def calc_stats(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
    o, s = obs[ok], sim[ok]
    n = len(o)
    if n == 0:
        return {"n": 0, "r2": np.nan, "nse": np.nan, "d_idx": np.nan, "rrmse_pct": np.nan, "rmse": np.nan, "pbias_pct": np.nan, "mae": np.nan}
    
    mean_o = np.mean(o)
    sst = np.sum((o - mean_o) ** 2)
    sse = np.sum((s - o) ** 2)
    
    nse = float(1.0 - sse / sst) if sst > 0 else np.nan
    rmse = float(np.sqrt(np.mean((s - o) ** 2)))
    rrmse_pct = float(100.0 * rmse / mean_o) if mean_o > 0 else np.nan
    pbias_pct = float(100.0 * np.sum(s - o) / np.sum(o)) if np.sum(o) > 0 else np.nan
    mae = float(np.mean(np.abs(s - o)))
    
    if n > 1 and np.std(o) > 0 and np.std(s) > 0:
        r2 = float(np.corrcoef(o, s)[0, 1] ** 2)
    else:
        r2 = np.nan
        
    denom_d = np.sum((np.abs(s - mean_o) + np.abs(o - mean_o)) ** 2)
    d_idx = float(1.0 - sse / denom_d) if denom_d > 0 else np.nan
    
    return {
        "n": n,
        "r2": round(r2, 4),
        "nse": round(nse, 4),
        "d_idx": round(d_idx, 4),
        "rrmse_pct": round(rrmse_pct, 2),
        "rmse": round(rmse, 1),
        "pbias_pct": round(pbias_pct, 2),
        "mae": round(mae, 1),
    }


def parse_season_data(sid: str) -> pd.DataFrame:
    s_dir = DET_DIR / "_seasons" / sid
    h_file = s_dir / f"{sid}_deterministic_harvest_compare.csv"
    fw_file = s_dir / "FreshWt.OUT"
    
    df_h = pd.read_csv(h_file)
    max_hno = df_h["HNO"].max()
    term_h = df_h[df_h["HNO"] == max_hno].copy()
    
    lines = fw_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_line = [l for l in lines if l.startswith("@YEAR")][0]
    cols = header_line.replace("@", "").split()
    
    runs = []
    current_run = 0
    current_tn = 0
    for l in lines:
        if l.startswith("*RUN"):
            current_run += 1
            parts = l.split()
            current_tn = int(parts[-1])
        elif l.startswith(" 2025") or l.startswith(" 2026"):
            row = l.split()
            runs.append([current_run, current_tn] + row)
            
    df_fw = pd.DataFrame(runs, columns=["RUN", "TN"] + cols)
    df_fw = df_fw.astype({
        "DAP": int, "CHFPW": float, "TOFPW": float, "MTFPW": float, 
        "HFPOW": float, "CHPDT": float, "TOPOW": float, "PDMCD": float
    })
    
    last_fw = df_fw.groupby("TN").last().reset_index()
    
    merged = pd.merge(
        term_h[["TN", "OBS_FRESH_CUM", "SIM_FRESH_CUM", "OBS_DRY_CUM", "SIM_DRY_CUM"]],
        last_fw[["TN", "CHFPW", "TOFPW", "MTFPW", "TOPOW", "CHPDT", "PDMCD"]],
        on="TN",
        how="left"
    )
    
    merged["Season"] = sid
    merged["SIM_FRESH_BASE"] = merged["CHFPW"]
    merged["SIM_FRESH_PLUS_MTFPW"] = merged["CHFPW"] + merged["MTFPW"]
    merged["SIM_FRESH_PLUS_TOFPW"] = merged["CHFPW"] + merged["TOFPW"]
    
    merged["SIM_DRY_BASE"] = merged["SIM_DRY_CUM"]
    merged["SIM_DRY_PLUS_TOPOW"] = merged["SIM_DRY_CUM"] + merged["TOPOW"]
    
    mapping_file = PROJECT_ROOT / "configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv"
    if mapping_file.exists():
        mapping = pd.read_csv(mapping_file)
        m_sub = mapping[mapping["season_id"] == sid].set_index("treatment")
        merged["Water"] = merged["TN"].map(m_sub["water_level"])
        merged["N_Level"] = merged["TN"].map(m_sub["nitrogen_level"])
        merged["Fert_N_kg"] = merged["TN"].map(m_sub["nitrogen_kg_ha"])
        merged["Role"] = merged["TN"].map(m_sub["objective_role"])
    else:
        merged["Water"] = "?"
        merged["N_Level"] = "?"
        merged["Fert_N_kg"] = np.nan
        merged["Role"] = "?"
        
    return merged


def generate_plots(df25: pd.DataFrame, df26: pd.DataFrame, stats_summary: pd.DataFrame):
    print("\nGenerating Diagnostic Figures...")
    
    # ----------------------------------------------------
    # Figure 1: Per-Treatment Bar Chart (Observed vs Base vs With TOFPW)
    # ----------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), dpi=300)
    
    for ax, df_s, sid in zip(axes, [df25, df26], ["25SP (Spring 2025)", "26SP (Spring 2026)"]):
        x = np.arange(len(df_s))
        width = 0.26
        
        t_labels = [f"TN{r['TN']}\n({r['Water']}{r['N_Level']})" for _, r in df_s.iterrows()]
        
        rects1 = ax.bar(x - width, df_s["OBS_FRESH_CUM"] / 1000.0, width, label="Observed Field Yield", color="#2C3E50", alpha=0.9)
        rects2 = ax.bar(x, df_s["SIM_FRESH_BASE"] / 1000.0, width, label="Sim Baseline (CHFPW)", color="#E74C3C", alpha=0.85)
        rects3 = ax.bar(x + width, df_s["SIM_FRESH_PLUS_TOFPW"] / 1000.0, width, label="Sim + In-situ TOFPW", color="#27AE60", alpha=0.85)
        
        ax.set_title(f"{sid} - Treatment Yield Comparison", fontsize=12, fontweight="bold")
        ax.set_xlabel("Treatment (Water x Nitrogen)", fontweight="bold")
        ax.set_ylabel("Fresh Fruit Yield (t / ha)", fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(t_labels, fontsize=8.5)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.legend(frameon=True, facecolor="white", edgecolor="none")
        
        sub_stat = stats_summary[stats_summary["Season"].str.contains(sid[:4])]
        b_nse = sub_stat[sub_stat["Scheme"] == "Baseline (CHFPW)"]["NSE"].values[0]
        b_rrmse = sub_stat[sub_stat["Scheme"] == "Baseline (CHFPW)"]["RRMSE_%"].values[0]
        t_nse = sub_stat[sub_stat["Scheme"] == "With TOFPW (CHFPW+TOFPW)"]["NSE"].values[0]
        t_rrmse = sub_stat[sub_stat["Scheme"] == "With TOFPW (CHFPW+TOFPW)"]["RRMSE_%"].values[0]
        
        text_str = (
            f"Baseline: NSE = {b_nse:.3f}, RRMSE = {b_rrmse:.1f}%\n"
            f"+ TOFPW : NSE = {t_nse:.3f}, RRMSE = {t_rrmse:.1f}%"
        )
        ax.text(0.03, 0.95, text_str, transform=ax.transAxes, verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#F8F9F9", edgecolor="#BDC3C7", alpha=0.9), fontsize=9)
        
    plt.tight_layout()
    fig1_path = FIG_OUT_DIR / "fig1_per_treatment_yield_with_tofpw.png"
    plt.savefig(fig1_path)
    plt.close()
    print(f"  [OK] Saved Figure 1 to {fig1_path}")
    
    # ----------------------------------------------------
    # Figure 2: 1:1 Scatter & Regression (Baseline vs With TOFPW)
    # ----------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(13, 12), dpi=300)
    
    plot_configs = [
        (axes[0, 0], df25, "SIM_FRESH_BASE", "25SP: Baseline (CHFPW only)", "#E74C3C", 40, 90),
        (axes[0, 1], df25, "SIM_FRESH_PLUS_TOFPW", "25SP: With In-situ TOFPW (CHFPW+TOFPW)", "#27AE60", 40, 90),
        (axes[1, 0], df26, "SIM_FRESH_BASE", "26SP: Baseline (CHFPW only)", "#E74C3C", 35, 85),
        (axes[1, 1], df26, "SIM_FRESH_PLUS_TOFPW", "26SP: With In-situ TOFPW (CHFPW+TOFPW)", "#27AE60", 35, 85),
    ]
    
    for ax, df_s, sim_col, title, col, vmin, vmax in plot_configs:
        obs = df_s["OBS_FRESH_CUM"].to_numpy(float) / 1000.0
        sim = df_s[sim_col].to_numpy(float) / 1000.0
        
        st = calc_stats(obs * 1000.0, sim * 1000.0)
        
        ax.plot([vmin, vmax], [vmin, vmax], "k--", lw=1.2, label="1:1 Line", alpha=0.7)
        ax.scatter(obs, sim, color=col, edgecolors="black", s=70, zorder=4, label="Treatments")
        
        if len(obs) > 1:
            z = np.polyfit(obs, sim, 1)
            p = np.poly1d(z)
            x_line = np.linspace(vmin, vmax, 100)
            ax.plot(x_line, p(x_line), color=col, linestyle="-", lw=1.8, label=f"Fit (y = {z[0]:.2f}x + {z[1]:.1f})")
            
        ax.set_xlim(vmin, vmax)
        ax.set_ylim(vmin, vmax)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_xlabel("Observed Fresh Yield (t/ha)", fontweight="bold")
        ax.set_ylabel("Simulated Fresh Yield (t/ha)", fontweight="bold")
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.legend(loc="lower right", frameon=True, fontsize=8)
        
        stats_box = (
            f"R² = {st['r2']:.4f}\n"
            f"NSE = {st['nse']:.4f}\n"
            f"d-index = {st['d_idx']:.4f}\n"
            f"RRMSE = {st['rrmse_pct']:.2f}%\n"
            f"PBIAS = {st['pbias_pct']:+.2f}%\n"
            f"MAE = {st['mae']/1000.0:.2f} t/ha"
        )
        ax.text(0.04, 0.96, stats_box, transform=ax.transAxes, verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#EAEDED", edgecolor="#BDC3C7", alpha=0.9), fontsize=8.5)
                
    plt.tight_layout()
    fig2_path = FIG_OUT_DIR / "fig2_1to1_scatter_and_stats.png"
    plt.savefig(fig2_path)
    plt.close()
    print(f"  [OK] Saved Figure 2 to {fig2_path}")
    
    # ----------------------------------------------------
    # Figure 3: Summary Metrics Bar Chart Comparison
    # ----------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), dpi=300)
    
    metrics = [("NSE", "Nash-Sutcliffe Efficiency (NSE ↑)", (-7.0, 1.0)),
               ("RRMSE_%", "Relative RMSE (RRMSE % ↓)", (0, 35)),
               ("PBIAS_%", "Percent Bias (PBIAS % → 0)", (-20, 30))]
               
    for ax, (m_col, m_name, y_lim) in zip(axes, metrics):
        x = np.arange(2)
        width = 0.35
        
        v_base = [stats_summary[(stats_summary["Season"].str.contains(s)) & (stats_summary["Scheme"] == "Baseline (CHFPW)")][m_col].values[0] for s in ["25SP", "26SP"]]
        v_tofpw = [stats_summary[(stats_summary["Season"].str.contains(s)) & (stats_summary["Scheme"] == "With TOFPW (CHFPW+TOFPW)")][m_col].values[0] for s in ["25SP", "26SP"]]
        
        ax.bar(x - width/2, v_base, width, label="Baseline (CHFPW only)", color="#E74C3C", alpha=0.85)
        ax.bar(x + width/2, v_tofpw, width, label="With In-situ TOFPW", color="#27AE60", alpha=0.85)
        
        ax.set_title(m_name, fontsize=11, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(["2025 Spring (25SP)", "2026 Spring (26SP)"], fontweight="bold")
        ax.set_ylim(y_lim)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.axhline(0, color="black", lw=0.8)
        if m_col == "NSE":
            ax.legend(loc="lower left", frameon=True)
            
        for i, (b, t) in enumerate(zip(v_base, v_tofpw)):
            ax.text(i - width/2, b + (0.02 if b >= 0 else -0.3), f"{b:.2f}" if m_col=="NSE" else f"{b:.1f}%", ha="center", va="bottom" if b>=0 else "top", fontsize=8.5, fontweight="bold")
            ax.text(i + width/2, t + (0.02 if t >= 0 else -0.3), f"{t:.2f}" if m_col=="NSE" else f"{t:.1f}%", ha="center", va="bottom" if t>=0 else "top", fontsize=8.5, fontweight="bold")
            
    plt.tight_layout()
    fig3_path = FIG_OUT_DIR / "fig3_metrics_comparison_summary.png"
    plt.savefig(fig3_path)
    plt.close()
    print(f"  [OK] Saved Figure 3 to {fig3_path}")


def main():
    print("==================== COMPUTING TOFPW IMPACT FOR BEST125 ====================")
    df25 = parse_season_data("25SP")
    df26 = parse_season_data("26SP")
    
    rows = []
    for sid, df_s in [("25SP (Spring 2025)", df25), ("26SP (Spring 2026)", df26)]:
        obs_f = df_s["OBS_FRESH_CUM"].to_numpy(float)
        
        st_base = calc_stats(obs_f, df_s["SIM_FRESH_BASE"].to_numpy(float))
        st_base["Season"] = sid
        st_base["Scheme"] = "Baseline (CHFPW)"
        st_base["Variable"] = "Fresh Yield"
        rows.append(st_base)
        
        st_mtfpw = calc_stats(obs_f, df_s["SIM_FRESH_PLUS_MTFPW"].to_numpy(float))
        st_mtfpw["Season"] = sid
        st_mtfpw["Scheme"] = "With MTFPW (Mature Fruit on plant)"
        st_mtfpw["Variable"] = "Fresh Yield"
        rows.append(st_mtfpw)
        
        st_tofpw = calc_stats(obs_f, df_s["SIM_FRESH_PLUS_TOFPW"].to_numpy(float))
        st_tofpw["Season"] = sid
        st_tofpw["Scheme"] = "With TOFPW (CHFPW+TOFPW)"
        st_tofpw["Variable"] = "Fresh Yield"
        rows.append(st_tofpw)
        
    df_stats = pd.DataFrame(rows)
    cols_order = ["Season", "Scheme", "Variable", "n", "R2", "NSE", "d_idx", "RRMSE_%", "PBIAS_%", "RMSE", "MAE"]
    df_stats = df_stats.rename(columns={
        "r2": "R2", "nse": "NSE", "d_idx": "d_idx", "rrmse_pct": "RRMSE_%", 
        "pbias_pct": "PBIAS_%", "rmse": "RMSE", "mae": "MAE"
    })[cols_order]
    
    stats_csv = FIG_OUT_DIR / "tofpw_impact_metrics_scorecard.csv"
    data25_csv = FIG_OUT_DIR / "25SP_treatment_tofpw_breakdown.csv"
    data26_csv = FIG_OUT_DIR / "26SP_treatment_tofpw_breakdown.csv"
    
    df_stats.to_csv(stats_csv, index=False)
    df25.to_csv(data25_csv, index=False)
    df26.to_csv(data26_csv, index=False)
    
    print("\n========================== TOFPW IMPACT SCORECARD ==========================")
    print(df_stats.to_string(index=False))
    
    generate_plots(df25, df26, df_stats)
    print(f"\n[OK] All calculations and figures saved to {FIG_OUT_DIR}")


if __name__ == "__main__":
    main()
