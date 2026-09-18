#!/usr/bin/env python3
"""Aggregate and plot results from all nitrogen stress experiments.
"""

from __future__ import annotations

import re
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = PROJECT_ROOT / "workspace" / "experiments" / "nitrogen_response_small_exp_20260829"


def parse_plantgro_out(pg_path: Path) -> dict[str, float]:
    out = {
        "max_LAID": 0.0,
        "max_CWAD": 0.0,
        "max_SWAD": 0.0,
        "max_LWAD": 0.0,
        "mean_NSTD": 0.0,
        "max_NSTD": 0.0,
        "mean_LN_pct": 0.0,
        "min_LN_pct": 0.0,
    }
    if not pg_path.exists():
        return out

    lines = pg_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_line = None
    data_rows = []
    
    for l in lines:
        if l.startswith("@YEAR") or l.startswith("@ YEAR"):
            header_line = l.replace("@", "").split()
        elif header_line and l.strip() and not l.startswith("*") and not l.startswith("!"):
            parts = l.split()
            if len(parts) >= len(header_line):
                data_rows.append(parts[:len(header_line)])

    if header_line and data_rows:
        df = pd.DataFrame(data_rows, columns=header_line)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        if "LAID" in df.columns:
            out["max_LAID"] = float(df["LAID"].max())
        if "CWAD" in df.columns:
            out["max_CWAD"] = float(df["CWAD"].max())
        if "SWAD" in df.columns:
            out["max_SWAD"] = float(df["SWAD"].max())
        if "LWAD" in df.columns:
            out["max_LWAD"] = float(df["LWAD"].max())
        if "NSTD" in df.columns:
            out["mean_NSTD"] = float(df["NSTD"].mean())
            out["max_NSTD"] = float(df["NSTD"].max())
        if "LN%D" in df.columns:
            out["mean_LN_pct"] = float(df["LN%D"].mean())
            out["min_LN_pct"] = float(df["LN%D"].min())
    return out


def main() -> None:
    results = []
    for d in EXP_DIR.iterdir():
        if d.is_dir() and "_SNO3_" in d.name:
            cfg_name, sno3_str = d.name.split("_SNO3_")
            sno3 = float(sno3_str)
            pg_file = d / "PlantGro.OUT"
            data = parse_plantgro_out(pg_file)
            data["config"] = cfg_name
            data["sno3_mg_kg"] = sno3
            results.append(data)

    df = pd.DataFrame(results)
    df = df.sort_values(["config", "sno3_mg_kg"]).reset_index(drop=True)
    csv_path = EXP_DIR / "aggregated_nitrogen_experiment_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"Aggregated {len(df)} experiment runs to {csv_path}")

    # Plot
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    
    # Define clean label mapping and styles
    style_map = {
        "Baseline": {"label": "Baseline (Default TMGRO048)", "color": "#7f7f7f", "marker": "o", "ls": "--"},
        "ExpA_Broaden_Protein_Min": {"label": "Exp A: Broaden Protein Min (PROLFF/PROSTF)", "color": "#1f77b4", "marker": "s", "ls": "-"},
        "ExpB_Smooth_LeafN_Curve": {"label": "Exp B: Smooth Leaf N-Photo Curve (FNPGN/LNREF/NSLOPE)", "color": "#ff7f0e", "marker": "^", "ls": "-"},
        "ExpC_Enhanced_N_Buffer": {"label": "Exp C: Enhanced N Buffer (NMOBMX/NVSMOB/NSTFAC)", "color": "#2ca02c", "marker": "d", "ls": "-"},
        "ExpD_Full_Synergy": {"label": "Exp D: Full Synergy (A+B+C Combined)", "color": "#d62728", "marker": "v", "ls": "-", "lw": 2.2},
    }

    # Filter to standard 9 levels for clean plot
    std_levels = [1.0, 3.0, 6.0, 10.0, 15.0, 22.0, 32.0, 45.0, 60.0]
    df_plot = df[df["sno3_mg_kg"].isin(std_levels)]

    for cfg, group in df_plot.groupby("config"):
        if cfg not in style_map:
            continue
        st = style_map[cfg]
        lw = st.get("lw", 1.6)
        axes[0, 0].plot(group["sno3_mg_kg"], group["mean_NSTD"], label=st["label"], color=st["color"], marker=st["marker"], linestyle=st["ls"], linewidth=lw)
        axes[0, 1].plot(group["sno3_mg_kg"], group["max_LAID"], label=st["label"], color=st["color"], marker=st["marker"], linestyle=st["ls"], linewidth=lw)
        axes[1, 0].plot(group["sno3_mg_kg"], group["max_CWAD"], label=st["label"], color=st["color"], marker=st["marker"], linestyle=st["ls"], linewidth=lw)
        axes[1, 1].plot(group["sno3_mg_kg"], group["max_NSTD"], label=st["label"], color=st["color"], marker=st["marker"], linestyle=st["ls"], linewidth=lw)

    axes[0, 0].set_title("(a) Mean Nitrogen Stress Index (NSTD: 0=none, 1=max)", fontsize=11, fontweight="bold")
    axes[0, 0].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[0, 0].set_ylabel("Mean Seasonal NSTD (Growth Stress)")
    axes[0, 0].grid(True, linestyle="--", alpha=0.5)
    axes[0, 0].legend(fontsize=8, loc="upper right")

    axes[0, 1].set_title("(b) Maximum Canopy LAI Response", fontsize=11, fontweight="bold")
    axes[0, 1].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[0, 1].set_ylabel("Max LAI (m2/m2)")
    axes[0, 1].grid(True, linestyle="--", alpha=0.5)

    axes[1, 0].set_title("(c) Canopy Biomass Accumulation (CWAD)", fontsize=11, fontweight="bold")
    axes[1, 0].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[1, 0].set_ylabel("Max Canopy Dry Biomass (kg/ha)")
    axes[1, 0].grid(True, linestyle="--", alpha=0.5)

    axes[1, 1].set_title("(d) Peak Nitrogen Stress (Max Daily NSTD)", fontsize=11, fontweight="bold")
    axes[1, 1].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[1, 1].set_ylabel("Peak Daily NSTD")
    axes[1, 1].grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig_path = EXP_DIR / "nitrogen_stress_smoothing_curves.png"
    plt.savefig(fig_path, dpi=300)
    print(f"Saved plot to {fig_path}")


if __name__ == "__main__":
    main()
