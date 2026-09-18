#!/usr/bin/env python3
"""Legacy filename; deterministic diagnostics only. Paper rendering belongs to paper/R.
No auto-selected run, candidate, iteration or posterior. Uncertainty is opt-in.
Unsupported historical spread/standing-fruit claims are intentionally retired.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from src.reporting.metrics import valid_pair_mask
from src.reporting.ies_plot_provenance import load_ies_plot_sources

RUN_DIR = MAPPING_CSV = OUT_DIR = None
NITROGEN_COLORS = {"N3": "#C0392B", "N2": "#E67E22", "N1": "#2980B9", "N0": "#707070"}
WATER_MARKERS = {"W3": "o", "W2": "s", "W1": "^", "CK": "D"}

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
    r2 = float(np.corrcoef(o, s)[0, 1] ** 2) if (n > 1 and np.std(o) > 0 and np.std(s) > 0) else np.nan
    denom_d = np.sum((np.abs(s - mean_o) + np.abs(o - mean_o)) ** 2)
    d_idx = float(1.0 - sse / denom_d) if denom_d > 0 else np.nan
    return {
        "n": n, "r2": round(r2, 4), "nse": round(nse, 4), "d_idx": round(d_idx, 4),
        "rrmse_pct": round(rrmse_pct, 2), "rmse": round(rmse, 2), "pbias_pct": round(pbias_pct, 2),
        "mae": round(mae, 2)
    }


def generate_fig3_pure_1to1():
    print("[diagnostic] Generating diagnostic scatter: 2-Row x 4-Col 1:1 Performance Grid (25SP vs 26SP, 4 Key Variables)...")
    mapping = pd.read_csv(MAPPING_CSV)
    
    # Load 25SP and 26SP data
    h25 = pd.read_csv(RUN_DIR / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    p25 = pd.read_csv(RUN_DIR / "_seasons/25SP/25SP_deterministic_process_compare.csv")
    h26 = pd.read_csv(RUN_DIR / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    p26 = pd.read_csv(RUN_DIR / "_seasons/26SP/26SP_deterministic_process_compare.csv")
    
    # Merge WxN mapping
    h25 = h25.merge(mapping[mapping["season_id"] == "25SP"][["treatment", "water_level", "nitrogen_level"]],
                    left_on="TN", right_on="treatment", how="left", validate="many_to_one")
    p25 = p25.merge(mapping[mapping["season_id"] == "25SP"][["treatment", "water_level", "nitrogen_level"]],
                    left_on="TN", right_on="treatment", how="left", validate="many_to_one")
    h26 = h26.merge(mapping[mapping["season_id"] == "26SP"][["treatment", "water_level", "nitrogen_level"]],
                    left_on="TN", right_on="treatment", how="left", validate="many_to_one")
    p26 = p26.merge(mapping[mapping["season_id"] == "26SP"][["treatment", "water_level", "nitrogen_level"]],
                    left_on="TN", right_on="treatment", how="left", validate="many_to_one")
    
    # 4 Key Variables (Excluding Leaf Biomass as requested to ensure optimal font size and breathing room)
    vars_def = [
        ("FRESH_CUM", "Cumulative Fresh Fruit", r"t ha$^{-1}$", "harvest", "OBS_FRESH_CUM", "SIM_FRESH_CUM", 1e-3),
        ("DRY_CUM", "Cumulative Dry Fruit", r"kg ha$^{-1}$", "harvest", "OBS_DRY_CUM", "SIM_DRY_CUM", 1.0),
        ("LAID", "Leaf Area Index (LAI)", r"m$^2$ m$^{-2}$", "process", "OBS_LAID", "SIM_LAID", 1.0),
        ("SWAD", "Stem Biomass", r"kg ha$^{-1}$", "process", "OBS_SWAD", "SIM_SWAD", 1.0),
    ]
    
    seasons_config = [
        ("25SP", "2025 Spring (25SP)", h25, p25, ["a", "b", "c", "d"]),
        ("26SP", "2026 Spring (26SP)", h26, p26, ["e", "f", "g", "h"]),
    ]
    
    fig, axes = plt.subplots(2, 4, figsize=(16.5, 8.6), dpi=300)
    
    for row_idx, (season_code, season_title, df_h, df_p, tags) in enumerate(seasons_config):
        for col_idx, (var_code, var_title, unit, var_type, obs_col, sim_col, scale) in enumerate(vars_def):
            ax = axes[row_idx, col_idx]
            tag = tags[col_idx]
            
            df_src = df_h if var_type == "harvest" else df_p
            obs_raw = df_src[obs_col].to_numpy(float)
            sim_raw = df_src[sim_col].to_numpy(float)
            
            ok = valid_pair_mask(obs_raw, sim_raw, value_kind="state")
            obs, sim = obs_raw[ok] * scale, sim_raw[ok] * scale
            df_valid = df_src[ok].copy()
            
            metrics = calc_metrics(obs, sim)
            
            # Determine 1:1 limits
            val_min = 0.0
            val_max = max(obs.max(), sim.max()) * 1.15 if len(obs) > 0 else 1.0
            lims = [val_min, val_max]
            
            # 1:1 diagonal and ±15% envelope
            ax.plot(lims, lims, color="#2C3E50", ls="--", lw=1.3, zorder=1, label="1:1 Perfect Fit")
            ax.fill_between(lims, [x * 0.85 for x in lims], [x * 1.15 for x in lims],
                            color="#EAEDED", alpha=0.55, zorder=0, label="±15% Tolerance Band")
            
            # Scatter points by WxN
            for _, row in df_valid.iterrows():
                o_val = row[obs_col] * scale
                s_val = row[sim_col] * scale
                w = str(row.get("water_level", "?"))
                n = str(row.get("nitrogen_level", "?"))
                
                c = NITROGEN_COLORS.get(n, "#555")
                m = WATER_MARKERS.get(w, "o")
                
                ax.scatter(o_val, s_val, color=c, marker=m, s=55, alpha=0.88, edgecolors="#1A1A1A", linewidths=0.55, zorder=4)
                
            # Linear Regression line
            if len(obs) > 2:
                poly = np.polyfit(obs, sim, 1)
                x_line = np.linspace(lims[0], lims[1], 100)
                ax.plot(x_line, np.polyval(poly, x_line), color="#C0392B", ls="-", lw=1.4, zorder=2)
                
            ax.set_xlim(lims)
            ax.set_ylim(lims)
            ax.set_aspect("equal", "box")
            ax.grid(True, linestyle=":", alpha=0.45)
            
            # Panel Title with tag and season
            ax.set_title(f"({tag}) {season_code} | {var_title}", fontweight="bold", fontsize=10.5, pad=6)
            ax.set_xlabel(f"Observed [{unit}]", fontsize=9.5, fontweight="bold")
            if col_idx == 0:
                ax.set_ylabel(f"{season_title}\nSimulated [{unit}]", fontsize=9.5, fontweight="bold")
            else:
                ax.set_ylabel(f"Simulated [{unit}]", fontsize=9.5)
                
            # Inset Metrics Box at Top-Left (completely clean of data points)
            txt = (f"n = {metrics['n']}\n"
                   f"R² = {metrics['r2']:.3f}\n"
                   f"RMSE = {metrics['rmse']:.1f} {unit}\n"
                   f"nRMSE = {metrics['rrmse_pct']:.1f}%\n"
                   f"NSE = {metrics['nse']:.3f}\n"
                   f"d = {metrics['d_idx']:.3f}")
            ax.text(0.04, 0.96, txt, transform=ax.transAxes, ha="left", va="top",
                    fontsize=8.2, fontfamily="monospace",
                    bbox=dict(boxstyle="round,pad=0.35", facecolor="#FDFEFE", edgecolor="#BDC3C7", alpha=0.92))
                    
    # Shared Legend
    legend_elements = [
        Line2D([0], [0], color="#2C3E50", ls="--", lw=1.3, label="1:1 Fit Line"),
        Line2D([0], [0], color="#C0392B", ls="-", lw=1.4, label="Linear Regression"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N3"], markeredgecolor="k", markersize=7.5, label="N3 (High N)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N2"], markeredgecolor="k", markersize=7.5, label="N2"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N1"], markeredgecolor="k", markersize=7.5, label="N1 (Low N)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS["N0"], markeredgecolor="k", markersize=7.5, label="N0 (Zero N)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#777", markeredgecolor="k", markersize=7.5, label="W3"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#777", markeredgecolor="k", markersize=7.5, label="W2"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#777", markeredgecolor="k", markersize=7.5, label="W1"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="#777", markeredgecolor="k", markersize=7.5, label="CK"),
    ]
    fig.legend(handles=legend_elements, loc="upper center", bbox_to_anchor=(0.5, 1.035), ncol=10, frameon=True, fontsize=9.0)
    
    fig.text(0.5, 0.002, "DIAGNOSTIC ONLY — not paper evidence; no posterior uncertainty inferred", ha="center", fontsize=9)
    plt.tight_layout(rect=[0, 0.025, 1, 0.97])
    out_file = OUT_DIR / "diagnostic_multipanel_1to1_performance_grid.png"
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.savefig(OUT_DIR / "diagnostic_multipanel_1to1_performance_grid.pdf", bbox_inches="tight")
    # Also overwrite the legacy name so all links work
    plt.close()
    print(f"  [OK] Saved diagnostic scatter (2-Row x 4-Col Grid) to {out_file}")



def draw_ies_diagnostics(prior, posterior):
    names = [n for n in posterior if posterior[n].std() > 0][:12]
    if not names:
        raise ValueError("No varying parameters available")
    fig, axes = plt.subplots(int(np.ceil(len(names) / 4)), 4,
                             figsize=(12, 2.8 * int(np.ceil(len(names) / 4))), squeeze=False)
    for ax, name in zip(axes.flat, names):
        bins = np.histogram_bin_edges(np.r_[prior[name], posterior[name]], bins=25)
        ax.hist(prior[name], bins=bins, density=True, color="grey", alpha=.5, label="IES prior")
        ax.hist(posterior[name], bins=bins, density=True, color="#2980B9", alpha=.5, label="IES posterior")
        ax.set_title(name)
    for ax in list(axes.flat)[len(names):]:
        ax.set_visible(False)
    axes.flat[0].legend()
    fig.suptitle("DIAGNOSTIC: same-batch IES parameter distributions")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "diagnostic_ies_parameter_distributions.png", dpi=200)
    plt.close(fig)
    corr = posterior[names].corr(method="spearman")
    corr.to_csv(OUT_DIR / "diagnostic_ies_spearman.csv")
    # Correlation is descriptive; it does not establish physiological compensation.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path, help="Explicit deterministic output directory")
    parser.add_argument("--mapping-csv", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path, help="New diagnostic output directory")
    parser.add_argument("--ies-run-dir", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--iteration", type=int)
    parser.add_argument("--prior-par-csv", type=Path)
    args = parser.parse_args()
    global RUN_DIR, MAPPING_CSV, OUT_DIR
    RUN_DIR, MAPPING_CSV, OUT_DIR = args.run_dir.resolve(), args.mapping_csv.resolve(), args.out_dir.resolve()
    if OUT_DIR.exists() and any(OUT_DIR.iterdir()):
        parser.error("Output directory must be empty; historical figures are retained")
    mapping = pd.read_csv(MAPPING_CSV)
    if mapping.duplicated(["season_id", "treatment"]).any():
        parser.error("Duplicate treatment mapping")
    inputs = [MAPPING_CSV]
    for season in ("25SP", "26SP"):
        meta = mapping[mapping.season_id == season].set_index("treatment")
        for kind in ("harvest", "process"):
            path = RUN_DIR / f"_seasons/{season}/{season}_deterministic_{kind}_compare.csv"
            data = pd.read_csv(path)
            if not set(data.TN).issubset(meta.index):
                parser.error(f"Missing explicit treatment mapping: {path}")
            if not meta.water_level.isin(WATER_MARKERS).all() or not meta.nitrogen_level.isin(NITROGEN_COLORS).all():
                parser.error(f"Unknown water/nitrogen mapping: {season}")
            inputs.append(path)
    ies = None
    if any(v is not None for v in (args.ies_run_dir, args.case, args.iteration, args.prior_par_csv)):
        if args.ies_run_dir is None or args.case is None or args.iteration is None:
            parser.error("Posterior requires explicit --ies-run-dir, --case and --iteration")
        try:
            ies = load_ies_plot_sources(args.ies_run_dir, args.case, args.iteration, prior=args.prior_par_csv)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        print("Posterior/uncertainty omitted: no explicit verified IES source requested.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_fig3_pure_1to1()
    if ies is not None:
        draw_ies_diagnostics(ies[0], ies[1])
    provenance = {
        "status": "diagnostic_only_not_paper_evidence",
        "deterministic_run_dir": str(RUN_DIR),
        "sources": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "ies": ies[2] if ies else None,
        "retired": ["spread_ratio", "unverified_standing_fruit_closure", "implicit_champion"],
    }
    (OUT_DIR / "diagnostic_manifest.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
