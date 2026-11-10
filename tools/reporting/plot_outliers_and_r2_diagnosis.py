#!/usr/bin/env python3
"""Generate publication-quality diagnostic figure for:
1. Recurring outlier treatments across recent calibration rounds (26SP & 25SP).
2. Soil initial conditions (Water, Mineral N, Organic Carbon) comparison of outliers vs normal treatments.
3. 26SP R^2 Leverage Analysis: scatter plot highlighting the R^2 suppressors and LOO delta R^2.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sys
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
ARTIFACT_IMG_DIR = Path(r"C:\Users\Lidaeus\.gemini\antigravity-cli\brain\06a22b3d-1374-436c-944f-90bd22502f7f\images")

from tools.reporting.diagnose_error_patterns_and_soil import df_prof26, df, sp26, models

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9.5,
    "axes.labelsize": 10.5,
    "axes.titlesize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 8.5,
    "figure.dpi": 300,
})

fig = plt.figure(figsize=(16, 11))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.1], hspace=0.32, wspace=0.22)

# -------------------------------------------------------------
# Panel A: 26SP Mean Absolute Errors across recent models
# -------------------------------------------------------------
ax_a = fig.add_subplot(gs[0, 0])
s26 = df[df["SEASON"] == "26SP"].sort_values("mean_abs_err", ascending=True)
y_pos = np.arange(len(s26))

bars = ax_a.barh(y_pos, s26["mean_abs_err"], color="#e74c3c", alpha=0.8, edgecolor="black", height=0.65)
ax_a.set_yticks(y_pos)
ax_a.set_yticklabels([f"{r.Trt_Label} (T{int(r.TN)})" for _, r in s26.iterrows()])
ax_a.set_xlabel("Mean Absolute Yield Error |Err| (t/ha)")
ax_a.set_title("A. 26SP Treatments Ranked by Mean |Error| Across Recent Models", fontweight="bold")
ax_a.grid(axis="x", linestyle=":", alpha=0.6)

# Add text labels on bars
for bar, (_, r) in zip(bars, s26.iterrows()):
    w = bar.get_width()
    bias = r["mean_signed_err"]
    sign = "+" if bias > 0 else ""
    ax_a.text(w + 0.25, bar.get_y() + bar.get_height()/2, f"{w:.1f} t/ha (Bias {sign}{bias:.1f})",
              va="center", fontsize=8, color="#333333", fontweight="bold")
ax_a.set_xlim(0, 16.5)

# -------------------------------------------------------------
# Panel B: Initial Soil Water & Organic Carbon vs Errors (26SP)
# -------------------------------------------------------------
ax_b = fig.add_subplot(gs[0, 1])
# Merge df_prof26 with s26
p26 = df_prof26.sort_values("TN").copy()

# Double bar chart: Top 40cm Water vs Organic Carbon
x = np.arange(len(p26))
w = 0.38

color_w = "#3498db"
color_oc = "#f39c12"

rects1 = ax_b.bar(x - w/2, p26["water_top40_mm"], w, label="Top 40cm Water (mm)", color=color_w, edgecolor="black", alpha=0.85)
ax_b.set_ylabel("Initial Water in 0-40cm (mm)", color=color_w, fontweight="bold")
ax_b.tick_params(axis="y", labelcolor=color_w)
ax_b.set_xticks(x)
ax_b.set_xticklabels([f"{r.Label}\n(T{int(r.TN)})" for _, r in p26.iterrows()], fontsize=8)
ax_b.set_title("B. Initial Soil Topsoil Water & Organic Carbon (26SP)", fontweight="bold")
ax_b.grid(axis="y", linestyle=":", alpha=0.5)

# Secondary axis for Organic Carbon
ax_b2 = ax_b.twinx()
rects2 = ax_b2.bar(x + w/2, p26["mean_top30_oc_pct"], w, label="Top 30cm Organic C (%)", color=color_oc, edgecolor="black", alpha=0.85)
ax_b2.set_ylabel("Soil Organic Carbon SAOC (%)", color="#d35400", fontweight="bold")
ax_b2.tick_params(axis="y", labelcolor="#d35400")
ax_b2.set_ylim(0.65, 1.08)

# Highlight outlier treatments W1N0 and W1N1
for idx in [9, 11]: # T10 and T12 (0-indexed 9 and 11)
    ax_b.get_xticklabels()[idx].set_color("red")
    ax_b.get_xticklabels()[idx].set_fontweight("bold")

# Combine legends
lines1, labels1 = ax_b.get_legend_handles_labels()
lines2, labels2 = ax_b2.get_legend_handles_labels()
ax_b.legend(lines1 + lines2, labels1 + labels2, loc="upper left", framealpha=0.9)

# -------------------------------------------------------------
# Panel C: Leave-One-Out Impact on 26SP R^2 (Delta R^2)
# -------------------------------------------------------------
ax_c = fig.add_subplot(gs[1, 0])
# Compute LOO for C27
o = sp26["OBS_t_ha"].to_numpy()
s = sp26["C27"].to_numpy()
r2_full = (np.corrcoef(o, s)[0, 1])**2

loo_items = []
for i in range(len(sp26)):
    mask = np.ones(len(sp26), dtype=bool)
    mask[i] = False
    r2_sub = (np.corrcoef(o[mask], s[mask])[0, 1])**2
    loo_items.append({
        "TN": sp26.iloc[i]["TN"],
        "Label": sp26.iloc[i]["Trt_Label"],
        "Delta_R2": r2_sub - r2_full,
        "R2_without": r2_sub
    })
df_loo_c27 = pd.DataFrame(loo_items).sort_values("Delta_R2", ascending=True)

y_pos_c = np.arange(len(df_loo_c27))
colors_c = ["#2ecc71" if d > 0.02 else ("#95a5a6" if d >= 0 else "#e67e22") for d in df_loo_c27["Delta_R2"]]

bars_c = ax_c.barh(y_pos_c, df_loo_c27["Delta_R2"], color=colors_c, edgecolor="black", height=0.65)
ax_c.axvline(0, color="black", lw=1.0)
ax_c.set_yticks(y_pos_c)
ax_c.set_yticklabels([f"{r.Label} (T{int(r.TN)})" for _, r in df_loo_c27.iterrows()])
ax_c.set_xlabel(r"Change in $R^2$ when Treatment Excluded ($\Delta R^2$)")
ax_c.set_title(r"C. Leave-One-Out $R^2$ Sensitivity (Which Treatments Suppress $R^2$?)", fontweight="bold")
ax_c.grid(axis="x", linestyle=":", alpha=0.6)

for bar, (_, r) in zip(bars_c, df_loo_c27.iterrows()):
    d = r["Delta_R2"]
    if d > 0:
        ax_c.text(d + 0.003, bar.get_y() + bar.get_height()/2, f"+{d:.3f} (R²→{r['R2_without']:.3f})", va="center", fontsize=8, fontweight="bold", color="#27ae60")
    else:
        ax_c.text(d - 0.003, bar.get_y() + bar.get_height()/2, f"{d:.3f}", va="center", ha="right", fontsize=8, color="#555555")
ax_c.set_xlim(-0.12, 0.22)

# -------------------------------------------------------------
# Panel D: 26SP 1:1 Scatter Plot Highlighting the 3 Outlier Disruptors
# -------------------------------------------------------------
ax_d = fig.add_subplot(gs[1, 1])
lims = [48, 76]

ax_d.plot(lims, lims, "k-", lw=1.2, label="1:1 Line", zorder=1)
ax_d.plot(lims, [lims[0]*1.1, lims[1]*1.1], "k--", lw=0.8, alpha=0.5, label="±10% Envelope", zorder=1)
ax_d.plot(lims, [lims[0]*0.9, lims[1]*0.9], "k--", lw=0.8, alpha=0.5, zorder=1)
ax_d.fill_between(lims, [lims[0]*0.9, lims[1]*0.9], [lims[0]*1.1, lims[1]*1.1], color="gray", alpha=0.08)

# Reg line for full 12 trts
fit_full = np.polyfit(o, s, 1)
x_line = np.linspace(50, 75, 100)
ax_d.plot(x_line, np.polyval(fit_full, x_line), "r-.", lw=1.5, label=f"Full 12 Trts (R²={r2_full:.3f})")

# Reg line excluding top 3 suppressors: W3-N0 (T9), W3-N1 (T7), W1-N1 (T10)
mask_9 = ~sp26["Trt_Label"].isin(["W3-N0", "W3-N1", "W1-N1"])
fit_9 = np.polyfit(o[mask_9], s[mask_9], 1)
r2_9 = (np.corrcoef(o[mask_9], s[mask_9])[0, 1])**2
ax_d.plot(x_line, np.polyval(fit_9, x_line), "g-", lw=2.0, label=f"Excluding T9+T7+T10 (R²={r2_9:.3f})")

# Scatter points: normal vs 3 disruptors
disruptors = ["W3-N0", "W3-N1", "W1-N1"]
for _, r in sp26.iterrows():
    is_disruptor = r["Trt_Label"] in disruptors
    is_w1n0 = r["Trt_Label"] == "W1-N0"
    
    if is_disruptor:
        ax_d.scatter(r["OBS_t_ha"], r["C27"], s=95, c="#e74c3c", marker="X", edgecolor="black", zorder=5)
        ax_d.annotate(f"{r['Trt_Label']} (Disruptor)", (r["OBS_t_ha"], r["C27"]),
                      xytext=(6, -6), textcoords="offset points", fontsize=8.5, fontweight="bold", color="#c0392b")
    elif is_w1n0:
        ax_d.scatter(r["OBS_t_ha"], r["C27"], s=85, c="#e67e22", marker="D", edgecolor="black", zorder=5)
        ax_d.annotate(f"{r['Trt_Label']} (High Leverage)", (r["OBS_t_ha"], r["C27"]),
                      xytext=(6, 4), textcoords="offset points", fontsize=8.5, fontweight="bold", color="#d35400")
    else:
        ax_d.scatter(r["OBS_t_ha"], r["C27"], s=65, c="#2980b9", marker="o", edgecolor="black", zorder=4)
        ax_d.annotate(r["Trt_Label"], (r["OBS_t_ha"], r["C27"]),
                      xytext=(4, 4), textcoords="offset points", fontsize=7.5, color="#2c3e50")

ax_d.set_xlim(lims)
ax_d.set_ylim(lims)
ax_d.set_xlabel("Observed Yield (t/ha)")
ax_d.set_ylabel("C27 Simulated Yield (t/ha)")
ax_d.set_title("D. 26SP 1:1 Scatter: Three Disruptor Treatments (X) Suppressing Correlation", fontweight="bold")
ax_d.grid(True, linestyle=":", alpha=0.5)
ax_d.legend(loc="upper left", framealpha=0.92, fontsize=8)

plt.tight_layout()
out_img = ARTIFACT_IMG_DIR / "diagnostic_outliers_and_r2_diagnosis.png"
fig.savefig(out_img, dpi=300)
cand_img = PROJECT_ROOT / "workspace/candidates/candidate_c27_real24_root140_sasc092/diagnostic_outliers_and_r2_diagnosis.png"
fig.savefig(cand_img, dpi=300)
plt.close(fig)
print(f"Saved diagnostic figure to {out_img} and {cand_img}")
