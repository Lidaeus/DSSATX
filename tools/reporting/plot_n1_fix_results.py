#!/usr/bin/env python3
"""Plot diagnostic comparison figures for full_gen_13trt_n1_fix_200x6_20260924 (Real 24)
vs Baseline Real 80 across 25SP, 26SP, and 25FA.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")
ARTIFACT_DIR = Path(r"C:\Users\Lidaeus\.gemini\antigravity-cli\brain\06a22b3d-1374-436c-944f-90bd22502f7f\images")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# Load comparison table
comp_csv = PROJECT_ROOT / "workspace" / "experiments" / "compare_real81_and_optionb" / "grand_comparison_with_n1_fix.csv"
df = pd.read_csv(comp_csv)

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["font.size"] = 9

# Figure 1: 1:1 Scatter Plot
fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=300)

season_order = ["25SP", "26SP", "25FA"]
season_titles = {
    "25SP": "2025 Spring (Calibration/Valid, 11 trts)",
    "26SP": "2026 Spring (Calibration/Valid, 12 trts)",
    "25FA": "2025 Autumn (Independent Blind Test, 12 trts)"
}

colors = {"Real80": "#95a5a6", "Real24": "#27ae60"}

for ax, sname in zip(axes, season_order):
    sub = df[df["SEASON"] == sname]
    obs = sub["OBS_t_ha"]
    sim_old = sub["SIM_New_Real80_t_ha"]
    sim_new = sub["SIM_FixN1_Real24_t_ha"]
    
    # 1:1 line
    vmin = min(obs.min(), sim_old.min(), sim_new.min()) * 0.9
    vmax = max(obs.max(), sim_old.max(), sim_new.max()) * 1.1
    ax.plot([vmin, vmax], [vmin, vmax], "k--", lw=1.2, alpha=0.7, label="1:1 Reference")
    
    # Scatter points
    ax.scatter(obs, sim_old, color=colors["Real80"], alpha=0.7, s=55, marker="o", label="Pre-Fix (Real80)")
    ax.scatter(obs, sim_new, color=colors["Real24"], alpha=0.9, s=70, marker="^", label="N1-Fix Champion (Real24)")
    
    # Connect pairs with faint line
    for o, so, sn in zip(obs, sim_old, sim_new):
        ax.plot([o, o], [so, sn], color="#7f8c8d", alpha=0.4, lw=0.8)
        
    # Stats
    def get_stats(o, s):
        rmse = np.sqrt(np.mean((s - o)**2))
        nrmse = rmse / np.mean(o) * 100
        denom = np.sum((o - np.mean(o))**2)
        nse = 1.0 - np.sum((s - o)**2) / denom if denom else 0
        return nrmse, nse
        
    nrmse_old, nse_old = get_stats(obs, sim_old)
    nrmse_new, nse_new = get_stats(obs, sim_new)
    
    txt = (
        f"Pre-Fix:  NRMSE={nrmse_old:.2f}%, NSE={nse_old:+.3f}\n"
        f"Real24:  NRMSE={nrmse_new:.2f}%, NSE={nse_new:+.3f}"
    )
    ax.text(0.04, 0.94, txt, transform=ax.transAxes, va="top", ha="left",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bdc3c7", alpha=0.9), fontsize=8.5)
            
    ax.set_title(season_titles[sname], fontsize=10.5, fontweight="bold")
    ax.set_xlabel("Observed Fresh Yield (t/ha)", fontsize=9.5)
    ax.set_ylabel("Simulated Fresh Yield (t/ha)", fontsize=9.5)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.set_xlim(vmin, vmax)
    ax.set_ylim(vmin, vmax)
    if sname == "25SP":
        ax.legend(loc="lower right", fontsize=8.5)

plt.tight_layout()
p1 = ARTIFACT_DIR / "diagnostic_n1_fix_1to1_scatter.png"
fig.savefig(p1, dpi=300)
plt.close(fig)
print(f"Saved: {p1}")

# Figure 2: Nitrogen Response Ladders under W3, W2, W1 in 25SP & 26SP
fig, axes = plt.subplots(2, 3, figsize=(15, 9), dpi=300, sharey=False)

nitro_order = ["N0", "N1", "N2", "N3"]
water_levels = ["W3", "W2", "W1"]

for row_idx, sname in enumerate(["25SP", "26SP"]):
    for col_idx, wlevel in enumerate(water_levels):
        ax = axes[row_idx, col_idx]
        sub = df[(df["SEASON"] == sname) & (df["Trt_Label"].str.startswith(wlevel))].copy()
        
        # Extract N level from Trt_Label
        sub["N_Level"] = sub["Trt_Label"].apply(lambda x: x.split("-")[1] if "-" in x else "")
        sub = sub.sort_values(by="N_Level", key=lambda s: s.map({"N0": 0, "N1": 1, "N2": 2, "N3": 3}))
        
        if len(sub) == 0:
            ax.set_visible(False)
            continue
            
        x_vals = range(len(sub))
        n_labels = sub["N_Level"].tolist()
        obs = sub["OBS_t_ha"].tolist()
        old_sim = sub["SIM_New_Real80_t_ha"].tolist()
        new_sim = sub["SIM_FixN1_Real24_t_ha"].tolist()
        
        ax.plot(x_vals, obs, "o-", color="#2c3e50", lw=2.0, ms=7, label="Observed")
        ax.plot(x_vals, old_sim, "s--", color="#e74c3c", lw=1.5, ms=6, label="Pre-Fix Real80 (Inverted)")
        ax.plot(x_vals, new_sim, "^-", color="#27ae60", lw=2.2, ms=8, label="N1-Fix Real24 (Corrected)")
        
        # Highlight N1 point
        if "N1" in n_labels:
            n1_idx = n_labels.index("N1")
            ax.plot([x_vals[n1_idx]], [new_sim[n1_idx]], "^", color="#1e8449", ms=11, zorder=5)
            
        ax.set_xticks(x_vals)
        ax.set_xticklabels(n_labels, fontweight="bold")
        ax.set_title(f"{sname} - {wlevel} Irrigation (N Gradient)", fontsize=10, fontweight="bold")
        ax.set_xlabel("Nitrogen Level", fontsize=9)
        ax.set_ylabel("Fresh Fruit Yield (t/ha)", fontsize=9)
        ax.grid(True, linestyle=":", alpha=0.5)
        
        if row_idx == 0 and col_idx == 0:
            ax.legend(loc="lower right", fontsize=8.5)

plt.tight_layout()
p2 = ARTIFACT_DIR / "diagnostic_n1_fix_nitrogen_response_ladders.png"
fig.savefig(p2, dpi=300)
plt.close(fig)
print(f"Saved: {p2}")

# Figure 3: Residuals Forest Plot for 25SP & 26SP
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7), dpi=300)

for ax, sname in zip([ax1, ax2], ["25SP", "26SP"]):
    sub = df[df["SEASON"] == sname].copy()
    y_pos = np.arange(len(sub))
    
    err_old = sub["SIM_New_Real80_t_ha"] - sub["OBS_t_ha"]
    err_new = sub["SIM_FixN1_Real24_t_ha"] - sub["OBS_t_ha"]
    labels = sub["Trt_Label"].tolist()
    
    height = 0.38
    ax.barh(y_pos - height/2, err_old, height, color="#e74c3c", alpha=0.75, label="Pre-Fix Real80 Residual")
    ax.barh(y_pos + height/2, err_new, height, color="#27ae60", alpha=0.85, label="N1-Fix Real24 Residual")
    
    ax.axvline(0, color="black", lw=1.0, linestyle="--")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8.5, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlabel("Residual (Simulated - Observed, t/ha)", fontsize=9.5)
    ax.set_title(f"{sname} Treatment Residuals Comparison", fontsize=11, fontweight="bold")
    ax.grid(True, linestyle=":", alpha=0.5, axis="x")
    ax.legend(loc="lower right", fontsize=8.5)

plt.tight_layout()
p3 = ARTIFACT_DIR / "diagnostic_n1_fix_residuals_comparison.png"
fig.savefig(p3, dpi=300)
plt.close(fig)
print(f"Saved: {p3}")
