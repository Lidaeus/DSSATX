#!/usr/bin/env python3
"""Comprehensive Summary & Diagnostic Analysis for Formal Final Calibration Champion Run.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "e02_formal_final_champion_200x6_20260829"
CASE = "e02_formal_final_champion_20260829"
RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / RUN_ID
DET_DIR = RUN_DIR / "best_member_41_two_season_deterministic_20260829"
REPORT_DIR = PROJECT_ROOT / "workspace" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def analyze_convergence() -> pd.DataFrame:
    phi_csv = RUN_DIR / f"{CASE}.phi.actual.csv"
    df = pd.read_csv(phi_csv)
    summary_cols = ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]
    conv_df = df[summary_cols].copy()
    conv_df.to_csv(REPORT_DIR / "formal_final_phi_convergence.csv", index=False)
    return conv_df


def analyze_parameters() -> pd.DataFrame:
    par_0_csv = RUN_DIR / f"{CASE}.0.par.csv"
    par_6_csv = RUN_DIR / f"{CASE}.6.par.csv"
    best_par_csv = DET_DIR / "best_member_41_params.csv"
    bounds_csv = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_e02_v32_formal_final_champion_bounds.csv"

    df_bounds = pd.read_csv(bounds_csv)
    df_bounds["name_upper"] = df_bounds["name"].str.upper()
    df_bounds = df_bounds.set_index("name_upper")

    df_best = pd.read_csv(best_par_csv)
    df_best["name_upper"] = df_best["name"].str.upper()
    df_best = df_best.set_index("name_upper")

    df_par6 = pd.read_csv(par_6_csv, index_col=0)
    df_par6.columns = [str(c).upper() for c in df_par6.columns]

    records = []
    for param in df_bounds.index:
        status = df_bounds.loc[param, "status"]
        lower = df_bounds.loc[param, "lower"]
        init = df_bounds.loc[param, "init"]
        upper = df_bounds.loc[param, "upper"]
        pargp = df_bounds.loc[param, "pargp"]
        val_best = df_best.loc[param, "value"] if param in df_best.index else np.nan

        ens_mean = np.nan
        ens_std = np.nan
        ens_min = np.nan
        ens_max = np.nan
        if param in df_par6.columns:
            ens_mean = float(df_par6[param].mean())
            ens_std = float(df_par6[param].std())
            ens_min = float(df_par6[param].min())
            ens_max = float(df_par6[param].max())

        # Touch boundary ratio
        span = upper - lower if upper > lower else 1.0
        pct_from_lower = (val_best - lower) / span * 100 if span > 0 else 50.0

        records.append({
            "parameter": param,
            "group": pargp,
            "status": status,
            "lower": lower,
            "init": init,
            "upper": upper,
            "best41_value": val_best,
            "best41_pos_pct": pct_from_lower,
            "ens_mean": ens_mean,
            "ens_std": ens_std,
            "ens_min": ens_min,
            "ens_max": ens_max,
        })

    df_par_summary = pd.DataFrame(records)
    df_par_summary.to_csv(REPORT_DIR / "formal_final_parameter_posteriors.csv", index=False)
    return df_par_summary


def analyze_harvest() -> dict[str, pd.DataFrame]:
    res = {}
    for season in ["25SP", "26SP"]:
        h_csv = DET_DIR / f"_seasons/{season}/{season}_deterministic_harvest_compare.csv"
        if h_csv.exists():
            df = pd.read_csv(h_csv)
            res[season] = df
            # Compute harvest summary by HNO
            hno_summary = df.groupby("HNO").agg({
                "OBS_DRY_INC": "mean",
                "SIM_DRY_INC": "mean",
                "OBS_DRY_CUM": "mean",
                "SIM_DRY_CUM": "mean",
                "OBS_FRESH_CUM": "mean",
                "SIM_FRESH_CUM": "mean",
            }).reset_index()
            hno_summary["BIAS_DRY_INC"] = hno_summary["SIM_DRY_INC"] - hno_summary["OBS_DRY_INC"]
            hno_summary["BIAS_DRY_CUM"] = hno_summary["SIM_DRY_CUM"] - hno_summary["OBS_DRY_CUM"]
            hno_summary.to_csv(REPORT_DIR / f"formal_final_{season}_harvest_by_hno.csv", index=False)

            # Compute terminal summary by Treatment
            t_summary = df.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
            t_summary["BIAS_DRY_CUM"] = t_summary["SIM_DRY_CUM"] - t_summary["OBS_DRY_CUM"]
            t_summary["BIAS_PCT_DRY"] = (t_summary["BIAS_DRY_CUM"] / t_summary["OBS_DRY_CUM"]) * 100
            t_summary.to_csv(REPORT_DIR / f"formal_final_{season}_terminal_by_treatment.csv", index=False)
    return res


def main() -> None:
    print("=== Analyzing Formal Final Calibration Champion Run ===")
    conv_df = analyze_convergence()
    print("\n--- Convergence Summary ---")
    print(conv_df.to_string())

    par_df = analyze_parameters()
    print("\n--- Key Physiological Parameters Posteriors ---")
    key_params = ["SFDUR", "WTFSD", "PORPT", "XFRMAX", "CMOBMX", "NSTFAC", "NMOBMX", "RTNO3", "SLPF_25SP", "SLPF_26SP", "PHTMAX", "LFMAX"]
    sub_par = par_df[par_df["parameter"].isin(key_params)][["parameter", "lower", "init", "upper", "best41_value", "best41_pos_pct", "ens_mean", "ens_std"]]
    print(sub_par.to_string(index=False))

    h_data = analyze_harvest()
    for season in ["25SP", "26SP"]:
        print(f"\n--- {season} Harvest Increment Profile (Mean across all treatments) ---")
        hno_file = REPORT_DIR / f"formal_final_{season}_harvest_by_hno.csv"
        if hno_file.exists():
            print(pd.read_csv(hno_file)[["HNO", "OBS_DRY_INC", "SIM_DRY_INC", "BIAS_DRY_INC", "OBS_DRY_CUM", "SIM_DRY_CUM", "BIAS_DRY_CUM"]].to_string(index=False))

    print("\nAnalysis complete! All tables exported to workspace/reports/")


if __name__ == "__main__":
    main()
