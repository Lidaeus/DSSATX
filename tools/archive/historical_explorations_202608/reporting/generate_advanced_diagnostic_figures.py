#!/usr/bin/env python3
"""Advanced Publication-Grade Diagnostic Figure Suite:
Implements the 5 modernized diagnostic figures:
  1. Cross-Season Metrics Forest Plot (diagnostic_metrics_forest.png) - replaces per-treatment heatmap
  2. Harvest Event Lollipop Plot (lollipop_harvest_events.png) - replaces crowded increment bar chart
  3. Multi-Panel Performance & Residual Composite Grid (diagnostic_multipanel_performance_grid.png) - top-journal 1:1 + residuals
  4. Parameter Posterior Contraction Ratio Bar Chart (diagnostic_parameter_contraction.png) - replaces unphysical scatters
  5. Spearman Parameter Compensation Correlation Heatmap (diagnostic_spearman_correlation_matrix.png) - replaces t-SNE

Can be run standalone on any completed calibration run or called by plot_dynamics.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.metrics import valid_pair_mask
from src.reporting.ies_plot_provenance import load_ies_plot_sources


def _verified_ensembles(path):
    match = re.fullmatch(r"(.+)\.(\d+)\.par\.csv", path.name)
    if not match:
        raise ValueError("Posterior must name an explicit case.iteration.par.csv")
    return load_ies_plot_sources(path.parent, match[1], int(match[2]))

# Publication-grade matplotlib typography & styling
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Helvetica", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 9.5
plt.rcParams["axes.labelsize"] = 10.5
plt.rcParams["axes.titlesize"] = 11.5
plt.rcParams["xtick.labelsize"] = 9
plt.rcParams["ytick.labelsize"] = 9
plt.rcParams["legend.fontsize"] = 8.5

NITROGEN_COLORS = {
    "N3": "#C0392B",  # Deep Red
    "N2": "#E67E22",  # Orange
    "N1": "#2980B9",  # Blue
    "N0": "#7F8C8D",  # Grey
    "?": "#34495E"
}

WATER_MARKERS = {
    "W3": "o",   # Circle
    "W2": "s",   # Square
    "W1": "^",   # Triangle
    "CK": "D",   # Diamond
    "?": "o"
}


def calc_metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    ok = valid_pair_mask(obs, sim, value_kind="state")
    o, s = obs[ok], sim[ok]
    n = len(o)
    if n == 0:
        return {"n": 0, "r2": np.nan, "nse": np.nan, "d_idx": np.nan, "rrmse_pct": np.nan, "rmse": np.nan, "pbias_pct": np.nan, "mae": np.nan}
    
    mean_o = np.mean(o)
    sst = np.sum((o - mean_o) ** 2)
    sse = np.sum((s - o) ** 2)
    
    nse = float(1.0 - sse / sst) if sst > 0 else np.nan
    rmse = float(np.sqrt(np.mean((s - o) ** 2)))
    rrmse_pct = float(100.0 * rmse / abs(mean_o)) if mean_o != 0 else np.nan
    pbias_pct = float(100.0 * np.sum(s - o) / np.sum(o)) if np.sum(o) != 0 else np.nan
    mae = float(np.mean(np.abs(s - o)))
    
    if n > 1 and np.std(o) > 0 and np.std(s) > 0:
        r2 = float(np.corrcoef(o, s)[0, 1] ** 2)
    else:
        r2 = np.nan
        
    denom_d = np.sum((np.abs(s - mean_o) + np.abs(o - mean_o)) ** 2)
    d_idx = float(1.0 - sse / denom_d) if denom_d > 0 else np.nan
    
    return {
        "n": n, "r2": round(r2, 4), "nse": round(nse, 4), "d_idx": round(d_idx, 4),
        "rrmse_pct": round(rrmse_pct, 2), "rmse": round(rmse, 2), "pbias_pct": round(pbias_pct, 2),
        "mae": round(mae, 2)
    }


# =========================================================================== #
# 1. Cross-Season Metrics Forest Plot (replaces metrics_heatmap_*.png)
# =========================================================================== #
def plot_metrics_forest(metrics_df: pd.DataFrame, out_png: Path) -> Path:
    """Generate a clean Forest Plot of model performance metrics across seasons and variables."""
    vars_order = ["FRESH_CUM", "DRY_CUM", "LAID", "LWAD", "SWAD"]
    var_labels = {
        "FRESH_CUM": "Fresh Fruit Yield (CHFPW)",
        "DRY_CUM": "Dry Fruit Yield (CHPDT)",
        "LAID": "Leaf Area Index (LAI)",
        "LWAD": "Leaf Biomass (LWAD)",
        "SWAD": "Stem Biomass (SWAD)"
    }
    
    df = metrics_df[metrics_df["variable"].isin(vars_order)].copy()
    if df.empty:
        return None
        
    seasons = [s for s in ["25SP", "26SP", "All"] if s in df["season"].unique()]
    n_vars = len(vars_order)
    
    fig, axes = plt.subplots(1, 3, figsize=(14, max(4.5, n_vars * 0.85 + 1.2)), dpi=300, sharey=True)
    
    y_pos = np.arange(n_vars)
    height = 0.26
    season_colors = {"25SP": "#2980B9", "26SP": "#27AE60", "All": "#8E44AD"}
    
    # Subplot 1: NSE & R²
    ax = axes[0]
    for i, s in enumerate(seasons):
        sub = df[df["season"] == s].set_index("variable").reindex(vars_order)
        offset = (i - (len(seasons)-1)/2.0) * height
        vals = sub["nse"].to_numpy(float)
        bars = ax.barh(y_pos + offset, vals, height, color=season_colors.get(s, "#555"), alpha=0.85, label=f"{s} (NSE)")
        for y, v in zip(y_pos + offset, vals):
            if np.isfinite(v):
                ax.text(max(v + 0.02, 0.05) if v >= 0 else 0.02, y, f"{v:.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=8, fontweight="bold")
    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(0.5, color="grey", ls="--", lw=0.7, alpha=0.7)
    ax.axvline(0.75, color="grey", ls=":", lw=0.7, alpha=0.7)
    ax.set_title("Nash-Sutcliffe Efficiency (NSE ↑)", fontweight="bold", fontsize=10.5)
    ax.set_xlabel("NSE (0.50 = Satisfactory, 0.75 = Good)")
    ax.set_yticks(y_pos)
    ax.set_yticklabels([var_labels.get(v, v) for v in vars_order], fontweight="bold")
    ax.set_xlim(-0.2, 1.05)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.legend(loc="lower left", frameon=True)
    
    # Subplot 2: RRMSE (%)
    ax = axes[1]
    for i, s in enumerate(seasons):
        sub = df[df["season"] == s].set_index("variable").reindex(vars_order)
        offset = (i - (len(seasons)-1)/2.0) * height
        vals = sub["rrmse_pct"].to_numpy(float)
        ax.barh(y_pos + offset, vals, height, color=season_colors.get(s, "#555"), alpha=0.85, label=f"{s} (nRMSE)")
        for y, v in zip(y_pos + offset, vals):
            if np.isfinite(v):
                ax.text(v + 0.5, y, f"{v:.1f}%", va="center", fontsize=8, fontweight="bold")
    ax.axvline(10.0, color="#27AE60", ls="--", lw=0.7, alpha=0.7)
    ax.axvline(20.0, color="#E67E22", ls="--", lw=0.7, alpha=0.7)
    ax.set_title("Relative RMSE (nRMSE % ↓)", fontweight="bold", fontsize=10.5)
    ax.set_xlabel("nRMSE (%) (<10% = Excellent, <20% = Good)")
    valid_rrmse = df["rrmse_pct"].dropna()
    ax.set_xlim(0, max(35.0, (valid_rrmse.max() * 1.15) if not valid_rrmse.empty else 35.0))
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    
    # Subplot 3: PBIAS (%) & d-index
    ax = axes[2]
    for i, s in enumerate(seasons):
        sub = df[df["season"] == s].set_index("variable").reindex(vars_order)
        offset = (i - (len(seasons)-1)/2.0) * height
        vals = sub["pbias_pct"].to_numpy(float)
        ax.barh(y_pos + offset, vals, height, color=season_colors.get(s, "#555"), alpha=0.85, label=s)
        for y, v in zip(y_pos + offset, vals):
            if np.isfinite(v):
                ax.text(v + (0.5 if v >= 0 else -0.5), y, f"{v:+.1f}%", va="center", ha="left" if v >= 0 else "right", fontsize=8, fontweight="bold")
    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(-10.0, color="grey", ls=":", lw=0.7, alpha=0.6)
    ax.axvline(10.0, color="grey", ls=":", lw=0.7, alpha=0.6)
    ax.set_title("Percent Bias (PBIAS % → 0)", fontweight="bold", fontsize=10.5)
    ax.set_xlabel("PBIAS (%) (±10% = Very Good, ±15% = Good)")
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    
    valid_pbias = df["pbias_pct"].dropna()
    p_max = max(15.0, (valid_pbias.abs().max() * 1.15) if not valid_pbias.empty else 15.0)
    ax.set_xlim(-p_max, p_max)
    
    fig.suptitle("Cross-Season Model Performance Diagnostic Forest", fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=300)
    plt.close()
    return out_png


# =========================================================================== #
# 2. Harvest Event Lollipop Plot (replaces crowded bar_dry_yield_increment.png)
# =========================================================================== #
def plot_harvest_lollipop(harvest_compare_df: pd.DataFrame, season_id: str, out_png: Path, mapping_df: pd.DataFrame = None) -> Path:
    """Generate a clean Lollipop Event plot for multi-harvest events by treatment."""
    df = harvest_compare_df.copy()
    if df.empty or "HNO" not in df.columns:
        return None
        
    df = df[np.isfinite(df["OBS_FRESH_INC"]) & (df["OBS_FRESH_INC"] >= 0)].copy()
    if df.empty:
        return None
        
    if mapping_df is not None and not mapping_df.empty:
        m_sub = mapping_df[mapping_df["season_id"] == season_id].set_index("treatment")
        df["Water"] = df["TN"].map(m_sub["water_level"]).fillna("?")
        df["Nitrogen"] = df["TN"].map(m_sub["nitrogen_level"]).fillna("?")
    else:
        df["Water"] = "?"
        df["Nitrogen"] = "?"
        
    treatments = sorted(df["TN"].unique())
    n_tmts = len(treatments)
    
    n_cols = 3 if n_tmts >= 9 else 2
    n_rows = int(np.ceil(n_tmts / n_cols))
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4.8 * n_cols, 2.8 * n_rows + 0.8), dpi=300, sharex=True, sharey=True)
    axes_flat = axes.flatten() if n_tmts > 1 else [axes]
    
    y_max = max(df["OBS_FRESH_INC"].max(), df["SIM_FRESH_INC"].max()) / 1000.0 * 1.18
    
    for idx, tn in enumerate(treatments):
        ax = axes_flat[idx]
        sub = df[df["TN"] == tn].sort_values("HNO").reset_index(drop=True)
        w, n = sub["Water"].iloc[0], sub["Nitrogen"].iloc[0]
        n_col = NITROGEN_COLORS.get(n, "#555")
        
        x = sub["HNO"].to_numpy(int)
        obs_y = sub["OBS_FRESH_INC"].to_numpy(float) / 1000.0
        sim_y = sub["SIM_FRESH_INC"].to_numpy(float) / 1000.0
        
        # Draw vertical lollipop stems
        for xi, oy, sy in zip(x, obs_y, sim_y):
            ax.plot([xi, xi], [0, max(oy, sy)], color="#BDC3C7", lw=1.2, zorder=1)
            ax.plot([xi, xi], [oy, sy], color="#E74C3C" if sy < oy else "#27AE60", lw=2.0, zorder=2)
            
        # Draw Observed points (solid filled circle)
        ax.scatter(x, obs_y, color=n_col, edgecolors="black", s=55, zorder=4, label="Observed" if idx==0 else "")
        
        # Draw Simulated points (open diamond)
        ax.scatter(x, sim_y, marker="D", facecolor="white", edgecolors="#2C3E50", linewidths=1.5, s=48, zorder=5, label="Simulated" if idx==0 else "")
        
        ax.set_title(f"TN {tn} ({w} × {n})", fontweight="bold", fontsize=9.5)
        ax.set_ylim(0, y_max)
        ax.grid(True, linestyle=":", alpha=0.4)
        if idx % n_cols == 0:
            ax.set_ylabel("Incremental Yield (t/ha)", fontsize=9)
        if idx >= (n_rows - 1) * n_cols:
            ax.set_xlabel("Harvest No. (HNO)", fontsize=9)
            
    for j in range(n_tmts, len(axes_flat)):
        axes_flat[j].axis("off")
        
    handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#2C3E50", markeredgecolor="black", markersize=7, label="Observed Harvest"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="white", markeredgecolor="#2C3E50", markeredgewidth=1.5, markersize=7, label="Simulated Harvest"),
        Line2D([0], [0], color="#E74C3C", lw=2, label="Underestimation"),
        Line2D([0], [0], color="#27AE60", lw=2, label="Overestimation")
    ]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=4, frameon=True, fontsize=8.5)
    fig.suptitle(f"{season_id} Incremental Fresh Yield Harvest Event Diagnostic (Lollipop)", fontsize=12, fontweight="bold", y=1.02)
    
    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=300)
    plt.close()
    return out_png


# =========================================================================== #
# 3. Multi-Panel Performance & Residual Grid (Top-Journal 1:1 + Residuals)
# =========================================================================== #
def plot_multipanel_performance_grid(all_season_data: dict, out_png: Path, mapping_df: pd.DataFrame = None) -> Path:
    """Generate top-tier 2-row x 5-column publication performance grid:
    Top Row: 1:1 Scatter plots for Fresh Yield, Dry Yield, LAI, LWAD, SWAD
    Bottom Row: Residuals (Sim - Obs vs Fitted) with error tolerance bands
    """
    specs = [
        ("FRESH_CUM", "Fresh Fruit Yield", "t ha$^{-1}$", 1000.0, "OBS_FRESH_CUM", "SIM_FRESH_CUM", "harv"),
        ("DRY_CUM", "Dry Fruit Yield", "kg ha$^{-1}$", 1.0, "OBS_DRY_CUM", "SIM_DRY_CUM", "harv"),
        ("LAID", "Leaf Area Index", "m$^2$ m$^{-2}$", 1.0, "OBS_LAID", "SIM_LAID", "proc"),
        ("LWAD", "Leaf Biomass", "kg ha$^{-1}$", 1.0, "OBS_LWAD", "SIM_LWAD", "proc"),
        ("SWAD", "Stem Biomass", "kg ha$^{-1}$", 1.0, "OBS_SWAD", "SIM_SWAD", "proc")
    ]
    
    fig, axes = plt.subplots(2, 5, figsize=(22, 8.8), dpi=300)
    
    for col_idx, (var, title, unit, scale, obs_col, sim_col, src_type) in enumerate(specs):
        ax_top = axes[0, col_idx]
        ax_bot = axes[1, col_idx]
        
        obs_all, sim_all, w_all, n_all, s_all = [], [], [], [], []
        
        for s, sdata in all_season_data.items():
            df_comp = sdata.get(f"compare_{src_type}")
            if df_comp is None or df_comp.empty:
                continue
            ok = valid_pair_mask(df_comp[obs_col], df_comp[sim_col], value_kind="state")
            sub = df_comp[ok].copy()
            if sub.empty:
                continue
                
            for _, r in sub.iterrows():
                tn = int(r["TN"])
                w, n_lvl = "?", "?"
                if mapping_df is not None and not mapping_df.empty:
                    m_sub = mapping_df[(mapping_df["season_id"] == s) & (mapping_df["treatment"] == tn)]
                    if not m_sub.empty:
                        w = m_sub["water_level"].values[0]
                        n_lvl = m_sub["nitrogen_level"].values[0]
                obs_all.append(float(r[obs_col]) / scale)
                sim_all.append(float(r[sim_col]) / scale)
                w_all.append(w)
                n_all.append(n_lvl)
                s_all.append(s)
                
        obs_arr = np.array(obs_all)
        sim_arr = np.array(sim_all)
        
        if len(obs_arr) == 0:
            ax_top.axis("off"); ax_bot.axis("off")
            continue
            
        st = calc_metrics(obs_arr, sim_arr)
        
        # ---------------- Top Row: 1:1 Scatter Plot ----------------
        v_min = min(obs_arr.min(), sim_arr.min())
        v_max = max(obs_arr.max(), sim_arr.max())
        pad = 0.06 * (v_max - v_min) if v_max > v_min else 1.0
        lims = [max(0.0, v_min - pad), v_max + pad]
        
        ax_top.plot(lims, lims, "k--", lw=1.2, alpha=0.7, label="1:1 Line")
        
        for o, s, w, n_lvl in zip(obs_arr, sim_arr, w_all, n_all):
            mk = WATER_MARKERS.get(w, "o")
            col = NITROGEN_COLORS.get(n_lvl, "#555")
            ax_top.scatter(o, s, marker=mk, color=col, edgecolors="black", s=46, alpha=0.85, linewidths=0.5)
            
        if len(obs_arr) > 1:
            z = np.polyfit(obs_arr, sim_arr, 1)
            p = np.poly1d(z)
            x_line = np.linspace(lims[0], lims[1], 100)
            ax_top.plot(x_line, p(x_line), color="#2C3E50", linestyle="-", lw=1.5, label=f"Fit (y={z[0]:.2f}x{z[1]:+.1f})")
            
        ax_top.set_xlim(lims)
        ax_top.set_ylim(lims)
        ax_top.set_aspect("equal", adjustable="box")
        ax_top.set_title(f"{title}", fontsize=11, fontweight="bold")
        ax_top.set_xlabel(f"Observed ({unit})", fontsize=9.5)
        ax_top.set_ylabel(f"Simulated ({unit})", fontsize=9.5)
        ax_top.grid(True, linestyle=":", alpha=0.45)
        
        stats_box = (
            f"n = {st['n']}\n"
            f"R² = {st['r2']:.3f}\n"
            f"NSE = {st['nse']:.3f}\n"
            f"nRMSE = {st['rrmse_pct']:.1f}%\n"
            f"d = {st['d_idx']:.3f}\n"
            f"PBIAS = {st['pbias_pct']:+.1f}%"
        )
        ax_top.text(0.04, 0.96, stats_box, transform=ax_top.transAxes, va="top", fontsize=8.2,
                    bbox=dict(boxstyle="round,pad=0.4", facecolor="#F8F9F9", edgecolor="#BDC3C7", alpha=0.92))
                    
        # ---------------- Bottom Row: Residual Plot ----------------
        res_arr = sim_arr - obs_arr
        r_max = float(np.nanmax(np.abs(res_arr))) * 1.15 if len(res_arr) > 0 else 1.0
        
        ax_bot.axhline(0, color="black", ls="--", lw=1.1, alpha=0.7)
        ax_bot.axhspan(-0.1 * (v_max - v_min), 0.1 * (v_max - v_min), color="#2ECC71", alpha=0.08, label="±10% Range")
        
        for o, r, w, n_lvl in zip(obs_arr, res_arr, w_all, n_all):
            mk = WATER_MARKERS.get(w, "o")
            col = NITROGEN_COLORS.get(n_lvl, "#555")
            ax_bot.scatter(o, r, marker=mk, color=col, edgecolors="black", s=46, alpha=0.85, linewidths=0.5)
            
        ax_bot.set_xlim(lims)
        ax_bot.set_ylim(-r_max, r_max)
        ax_bot.set_title(f"{title} Residuals", fontsize=10.5, fontweight="bold")
        ax_bot.set_xlabel(f"Observed ({unit})", fontsize=9.5)
        ax_bot.set_ylabel(f"Residual [Sim − Obs] ({unit})", fontsize=9.5)
        ax_bot.grid(True, linestyle=":", alpha=0.45)
        
        mbe = float(np.mean(res_arr))
        mae = float(np.mean(np.abs(res_arr)))
        ax_bot.text(0.04, 0.94, f"MBE = {mbe:+.2f}\nMAE = {mae:.2f}", transform=ax_bot.transAxes,
                    va="top", fontsize=8.2, bbox=dict(boxstyle="round,pad=0.4", facecolor="#F8F9F9", edgecolor="#BDC3C7", alpha=0.9))
                    
    handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N3"], markeredgecolor="k", label="N3 (High N)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N2"], markeredgecolor="k", label="N2 (Opt N)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N1"], markeredgecolor="k", label="N1 (Low N)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N0"], markeredgecolor="k", label="N0 (Zero N)"),
        Line2D([0], [0], marker=WATER_MARKERS["W3"], color="w", markerfacecolor="#7F8C8D", markeredgecolor="k", label="W3 (100% Ep)"),
        Line2D([0], [0], marker=WATER_MARKERS["W2"], color="w", markerfacecolor="#7F8C8D", markeredgecolor="k", label="W2 (80% Ep)"),
        Line2D([0], [0], marker=WATER_MARKERS["W1"], color="w", markerfacecolor="#7F8C8D", markeredgecolor="k", label="W1 (60% Ep)"),
        Line2D([0], [0], marker=WATER_MARKERS["CK"], color="w", markerfacecolor="#7F8C8D", markeredgecolor="k", label="CK (Trad)")
    ]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.995), ncol=8, frameon=True, fontsize=8.8)
    fig.suptitle("Multi-Variable Performance & Residual Diagnostic Grid", fontsize=13, fontweight="bold", y=1.025)
    
    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=300)
    plt.close()
    return out_png


# =========================================================================== #
# 4. Parameter Posterior Contraction Ratio Bar Chart (replaces unphysical scatters)
# =========================================================================== #
def plot_parameter_contraction(prior_bounds_csv: Path, posterior_par_csv: Path, out_png: Path) -> Path:
    """Quantifies and visualizes parameter shrinkage:
    Contraction Ratio = 1 - Post_IQR / actual_same_batch_prior_IQR.
    Negative values (expansion) are retained, not clipped.
    """
    if not prior_bounds_csv.exists() or not posterior_par_csv.exists():
        raise ValueError("Missing bounds or posterior source")

    df_prior, df_par, evidence = _verified_ensembles(posterior_par_csv)
    df_bounds = pd.read_csv(prior_bounds_csv)
    
    df_bounds = df_bounds[df_bounds["status"] == "active"].copy()
    if df_bounds.empty:
        return None
        
    domain_map = {
        "phenology": "#3498DB",
        "photosynthesis": "#2ECC71",
        "nitrogen": "#E74C3C",
        "partitioning": "#F39C12",
        "soil_water": "#9B59B6",
        "general": "#95A5A6"
    }
    
    results = []
    for _, r in df_bounds.iterrows():
        pname = str(r["name"]).strip()
        lower = float(r["lower"])
        upper = float(r["upper"])
        
        col_match = [c for c in df_par.columns if c.lower() == pname.lower()]
        if not col_match:
            continue
        actual_bounds = evidence["parameter_bounds"][col_match[0]]
        if not np.allclose([lower, upper], actual_bounds, rtol=1e-6, atol=1e-8):
            raise ValueError(f"Bounds CSV differs from this batch's PST for {pname}")
        p_vals = df_par[col_match[0]].to_numpy(float)
        p_vals = p_vals[np.isfinite(p_vals)]
        if len(p_vals) < 2:
            continue
            
        p_lo, p_med, p_hi = np.percentile(p_vals, [10, 50, 90])
        p_iqr = np.percentile(p_vals, 75) - np.percentile(p_vals, 25)
        
        prior_range = upper - lower
        prior_iqr = np.subtract(*np.percentile(df_prior[col_match[0]], [75, 25]))
        if prior_iqr <= 0:
            print(f"No prior variation for {pname}; contraction undefined, omitted")
            continue
        contraction = 1.0 - p_iqr / prior_iqr
        
        rel_pos = (p_med - lower) / prior_range if prior_range > 0 else 0.5
        hit_boundary = "Upper Hit" if rel_pos > 0.95 else ("Lower Hit" if rel_pos < 0.05 else "Interior")
        
        dom = "general"
        if any(k in pname.lower() for k in ["em-fl", "fl-sh", "fl-sd", "sd-pm", "fl-lf", "xmage"]):
            dom = "phenology"
        elif any(k in pname.lower() for k in ["lfmax", "pmax", "kcan", "parmax", "phtmax"]):
            dom = "photosynthesis"
        elif any(k in pname.lower() for k in ["prolf", "prost", "nvsmob", "nmobmx", "fnpgn"]):
            dom = "nitrogen"
        elif any(k in pname.lower() for k in ["xfrt", "sfdur", "slavr", "sizlf", "sdpdv"]):
            dom = "partitioning"
        elif any(k in pname.lower() for k in ["sbdm", "slpf", "ssks", "slcl", "slsi"]):
            dom = "soil_water"
            
        results.append({
            "name": pname, "domain": dom, "lower": lower, "upper": upper,
            "post_med": p_med, "post_p10": p_lo, "post_p90": p_hi,
            "contraction": contraction, "rel_pos": rel_pos, "hit": hit_boundary
        })
        
    df_res = pd.DataFrame(results)
    if df_res.empty:
        return None
        
    df_res = df_res.sort_values("contraction", ascending=True).reset_index(drop=True)
    n_params = len(df_res)
    
    fig, ax = plt.subplots(figsize=(10, max(5.0, n_params * 0.28 + 1.2)), dpi=300)
    
    y = np.arange(n_params)
    colors = [domain_map.get(d, "#95A5A6") for d in df_res["domain"]]
    
    bars = ax.barh(y, df_res["contraction"] * 100.0, height=0.65, color=colors, alpha=0.85, edgecolor="black", linewidth=0.4)
    
    for i, (_, r) in enumerate(df_res.iterrows()):
        c_val = r["contraction"] * 100.0
        ax.text(c_val + 1.2, i, f"{c_val:.1f}% ({r['hit']})", va="center", fontsize=7.5, fontweight="bold",
                color="#C0392B" if r["hit"] != "Interior" else "#2C3E50")
                
    ax.set_yticks(y)
    ax.set_yticklabels(df_res["name"], fontsize=8.5, fontweight="bold")
    ax.set_xlabel("IES IQR contraction (%) [negative = expansion]", fontweight="bold", fontsize=9.5)
    ax.set_title("Parameter Posterior Contraction & Boundary Hit Diagnostic", fontweight="bold", fontsize=11.5)
    ax.set_xlim(min(0, df_res["contraction"].min() * 100 - 10), 115)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    
    domain_handles = [Patch(facecolor=c, edgecolor="k", label=k.capitalize()) for k, c in domain_map.items()]
    ax.legend(handles=domain_handles, loc="lower right", frameon=True, fontsize=8, title="Domain", title_fontsize=8)
    
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=300)
    plt.close()
    return out_png


# =========================================================================== #
# 5. Spearman Parameter Compensation Correlation Heatmap (replaces t-SNE)
# =========================================================================== #
def plot_spearman_correlation(posterior_par_csv: Path, out_png: Path, top_n: int = 20) -> Path:
    """Compute and visualize Spearman rank correlation matrix across posterior parameter ensemble."""
    _, df_par, _ = _verified_ensembles(posterior_par_csv)
    
    drop_cols = [c for c in ["real_name", "name", "iteration", "phi"] if c in df_par.columns]
    df_clean = df_par.drop(columns=drop_cols)
    
    df_clean = df_clean.loc[:, df_clean.std() > 1e-6]
    if df_clean.shape[1] < 3:
        return None
        
    corr = df_clean.corr(method="spearman")
    
    abs_sum = (corr.abs().sum() - 1.0).sort_values(ascending=False)
    selected_params = abs_sum.head(top_n).index.tolist()
    sub_corr = corr.loc[selected_params, selected_params]
    
    fig, ax = plt.subplots(figsize=(10.5, 9.5), dpi=300)
    
    mask = np.triu(np.ones_like(sub_corr, dtype=bool))
    
    cmap = plt.get_cmap("RdBu_r")
    im = ax.imshow(np.ma.masked_array(sub_corr.to_numpy(), mask), cmap=cmap, vmin=-1.0, vmax=1.0)
    
    for i in range(len(selected_params)):
        for j in range(len(selected_params)):
            if i > j:
                val = sub_corr.iloc[i, j]
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=7.5,
                        color="white" if abs(val) > 0.55 else "black", fontweight="bold" if abs(val) > 0.4 else "normal")
                        
    ax.set_xticks(np.arange(len(selected_params)))
    ax.set_yticks(np.arange(len(selected_params)))
    ax.set_xticklabels(selected_params, rotation=45, ha="right", fontsize=8.5, fontweight="bold")
    ax.set_yticklabels(selected_params, fontsize=8.5, fontweight="bold")
    
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Spearman Rank Correlation (ρₛ)", fontsize=9.5, fontweight="bold")
    
    ax.set_title("Posterior Parameter Compensation & Trade-off Heatmap (Spearman ρₛ)", fontsize=12, fontweight="bold", pad=12)
    
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=300)
    plt.close()
    return out_png


# =========================================================================== #
# CLI Runner
# =========================================================================== #
def main():
    parser = argparse.ArgumentParser(description="Generate Modernized Publication-Grade Diagnostic Figures.")
    parser.add_argument("--run-dir", required=True, help="Path to deterministic run directory (containing _seasons/)")
    parser.add_argument("--out-dir", required=True, help="Output directory for generated diagnostic figures")
    parser.add_argument("--bounds-csv", default=None, help="Path to prior bounds CSV for contraction analysis")
    parser.add_argument("--par-csv", default=None, help="Path to posterior parameter ensemble CSV")
    parser.add_argument("--mapping-csv", default="configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv", help="Treatment WN mapping CSV")
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    mapping_df = pd.read_csv(args.mapping_csv) if Path(args.mapping_csv).exists() else None
    
    print(f"[1/5] Loading season simulation & comparison data from {run_dir}...")
    all_season_data = {}
    metrics_rows = []
    
    for s in ["25SP", "26SP"]:
        s_dir = run_dir / "_seasons" / s
        if not s_dir.exists():
            continue
        h_file = s_dir / f"{s}_deterministic_harvest_compare.csv"
        p_file = s_dir / f"{s}_deterministic_process_compare.csv"
        
        df_h = pd.read_csv(h_file) if h_file.exists() else None
        df_p = pd.read_csv(p_file) if p_file.exists() else None
        
        all_season_data[s] = {"compare_harv": df_h, "compare_proc": df_p}
        
        # Calculate variable metrics
        if df_h is not None and not df_h.empty:
            for v, col_o, col_s in [("FRESH_CUM", "OBS_FRESH_CUM", "SIM_FRESH_CUM"), ("DRY_CUM", "OBS_DRY_CUM", "SIM_DRY_CUM")]:
                st = calc_metrics(df_h[col_o].to_numpy(float), df_h[col_s].to_numpy(float))
                st["season"] = s; st["variable"] = v
                metrics_rows.append(st)
                
        if df_p is not None and not df_p.empty:
            for v in ["LAID", "LWAD", "SWAD"]:
                st = calc_metrics(df_p[f"OBS_{v}"].to_numpy(float), df_p[f"SIM_{v}"].to_numpy(float))
                st["season"] = s; st["variable"] = v
                metrics_rows.append(st)
                
    # Also calculate cross-season overall
    for v, src, col_o, col_s in [
        ("FRESH_CUM", "compare_harv", "OBS_FRESH_CUM", "SIM_FRESH_CUM"),
        ("DRY_CUM", "compare_harv", "OBS_DRY_CUM", "SIM_DRY_CUM"),
        ("LAID", "compare_proc", "OBS_LAID", "SIM_LAID"),
        ("LWAD", "compare_proc", "OBS_LWAD", "SIM_LWAD"),
        ("SWAD", "compare_proc", "OBS_SWAD", "SIM_SWAD"),
    ]:
        o_list, s_list = [], []
        for sdata in all_season_data.values():
            df_sub = sdata.get(src)
            if df_sub is not None and not df_sub.empty and col_o in df_sub.columns and col_s in df_sub.columns:
                ok = valid_pair_mask(df_sub[col_o], df_sub[col_s], value_kind="state")
                o_list.extend(df_sub.loc[ok, col_o].astype(float).tolist())
                s_list.extend(df_sub.loc[ok, col_s].astype(float).tolist())
        if o_list:
            st = calc_metrics(np.array(o_list), np.array(s_list))
            st["season"] = "All"; st["variable"] = v
            metrics_rows.append(st)
        
    df_metrics = pd.DataFrame(metrics_rows)
    df_metrics.to_csv(out_dir / "diagnostic_metrics_summary.csv", index=False)
    
    print("[2/5] Generating Diagnostic 1: Cross-Season Metrics Forest Plot...")
    p1 = plot_metrics_forest(df_metrics, out_dir / "diagnostic_metrics_forest.png")
    print(f"  -> Saved {p1}")
    
    print("[3/5] Generating Diagnostic 2: Harvest Event Lollipop Plots...")
    for s, sdata in all_season_data.items():
        if sdata["compare_harv"] is not None:
            p2 = plot_harvest_lollipop(sdata["compare_harv"], s, out_dir / f"{s}/lollipop_harvest_events.png", mapping_df)
            print(f"  -> Saved {p2}")
            
    print("[4/5] Generating Diagnostic 3: Multi-Panel Performance & Residual Grid...")
    p3 = plot_multipanel_performance_grid(all_season_data, out_dir / "diagnostic_multipanel_performance_grid.png", mapping_df)
    print(f"  -> Saved {p3}")
    
    if args.bounds_csv and args.par_csv:
        print("[5/5] Generating Diagnostics 4 & 5: Parameter Contraction and Spearman Heatmap...")
        p4 = plot_parameter_contraction(Path(args.bounds_csv), Path(args.par_csv), out_dir / "diagnostic_parameter_contraction.png")
        p5 = plot_spearman_correlation(Path(args.par_csv), out_dir / "diagnostic_spearman_correlation_matrix.png")
        print(f"  -> Saved {p4}")
        print(f"  -> Saved {p5}")
        
    print(f"\n[OK] All modernized diagnostic figures generated successfully under {out_dir}")


if __name__ == "__main__":
    main()
