"""Comprehensive Profile Exploration Grid for 26SP Late Yield Bottlenecks.

Sweeps:
- Photosynthesis: PHTMAX, PGEFF, PARMAX
- Canopy & Phenology: TRIFL, LFMAX, LNGSH
- Fruit Partition & Timing: SFDUR, WTFSD, XFRMAX, PORPT, CMOBMX
- Nitrogen Response: NRMIN, NREXP, NSTFAC, NMOBMX
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)

CAL_DIR = ROOT / "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
MEMBER_153_CSV = CAL_DIR / "best_member_153_two_season_deterministic_20260829/best_member_153_params.csv"
EXP_DIR = ROOT / "workspace/reports/exploration_26sp_yield_profiles_20260829"

SEASONS = [
    {
        "season_id": "25SP",
        "excode": "XXQL2501",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "bundle": str((ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828").resolve()),
    },
    {
        "season_id": "26SP",
        "excode": "XXQL2601",
        "treatments": list(range(1, 13)),
        "bundle": str((ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828").resolve()),
    },
]


def load_base_params() -> pd.DataFrame:
    if MEMBER_153_CSV.exists():
        return pd.read_csv(MEMBER_153_CSV)
    par_csv = CAL_DIR / "e02_formal_yield_rebalanced_post_200x6_20260829.4.par.csv"
    df = pd.read_csv(par_csv)
    r_col = [c for c in df.columns if "real" in c.lower()][0]
    sub = df[df[r_col].astype(str) == "153"].drop(columns=[r_col])
    res = []
    for col in sub.columns:
        res.append({"name": col, "value": sub[col].values[0]})
    return pd.DataFrame(res)


def evaluate_param_set(params_df: pd.DataFrame, work_dir: Path) -> dict[str, float]:
    work_dir.mkdir(parents=True, exist_ok=True)
    param_file = work_dir / "params.csv"
    params_df.to_csv(param_file, index=False)

    design_payload = {
        "schema_version": 1,
        "design_id": "prof_eval",
        "cultivar_identity": "TM0008",
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_v31.csv",
        "group_policy": "configs/runs/e02_from_scratch_group_policy_v31.csv",
        "purpose": "deterministic exploration",
        "seasons": [
            {
                "season_id": s["season_id"],
                "experiment_code": s["excode"],
                "role": "calibration",
                "bundle_path": s["bundle"],
                "treatments": s["treatments"],
            }
            for s in SEASONS
        ],
    }
    design_json = work_dir / "design.json"
    design_json.write_text(json.dumps(design_payload, indent=2), encoding="utf-8")

    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_json.resolve()),
        "--param-csv", str(param_file.resolve()),
        "--prefix", "prof_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
    if res.returncode != 0:
        return {"error": 1.0}

    # Generate comparison CSVs inside work_dir/_seasons/<season_id>
    for season in SEASONS:
        sid = season["season_id"]
        season_dir = work_dir / "_seasons" / sid
        if not season_dir.exists():
            continue
        filex = next(season_dir.glob("*.TMX"))
        batch = season_dir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in season["treatments"]) + "\n",
            encoding="utf-8",
        )
        deterministic_process_compare(
            sid, str(batch),
            var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"],
            run_dir=str(season_dir),
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(season_dir))

    metrics_out: dict[str, float] = {}

    # 1. 26SP harvest metrics
    h26_csv = work_dir / "_seasons/26SP/26SP_deterministic_harvest_compare.csv"
    if h26_csv.exists():
        df_h26 = pd.read_csv(h26_csv)
        # H3 delta (increment at HNO 3)
        h3_sub = df_h26[df_h26["HNO"] == 3]
        if not h3_sub.empty:
            obs_inc = h3_sub["OBS_DRY_INC"].mean()
            sim_inc = h3_sub["SIM_DRY_INC"].mean()
            metrics_out["26SP_H3_obs_inc_mean"] = float(obs_inc)
            metrics_out["26SP_H3_sim_inc_mean"] = float(sim_inc)
            metrics_out["26SP_H3_inc_gap"] = float(sim_inc - obs_inc)

        # Terminal H5 yield
        h5_sub = df_h26.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        y = h5_sub["OBS_DRY_CUM"].to_numpy(float)
        p = h5_sub["SIM_DRY_CUM"].to_numpy(float)
        err = p - y
        rmse = float(np.sqrt(np.mean(err**2)))
        rrmse = float(100 * rmse / np.mean(y)) if np.mean(y) > 0 else np.nan
        metrics_out["26SP_term_dry_obs_mean"] = float(np.mean(y))
        metrics_out["26SP_term_dry_sim_mean"] = float(np.mean(p))
        metrics_out["26SP_term_dry_bias"] = float(np.mean(err))
        metrics_out["26SP_term_dry_rrmse_pct"] = rrmse

        # N0 (TN 9, 11, 12) vs N1 (TN 7, 8, 10) vs N3 (TN 1, 2, 3)
        n0_sub = h5_sub[h5_sub["TN"].isin([9, 11, 12])]
        n1_sub = h5_sub[h5_sub["TN"].isin([7, 8, 10])]
        n3_sub = h5_sub[h5_sub["TN"].isin([1, 2, 3])]
        if not n0_sub.empty:
            metrics_out["26SP_N0_sim_mean"] = float(n0_sub["SIM_DRY_CUM"].mean())
            metrics_out["26SP_N0_bias_pct"] = float(((n0_sub["SIM_DRY_CUM"] - n0_sub["OBS_DRY_CUM"]) / n0_sub["OBS_DRY_CUM"] * 100).mean())
        if not n1_sub.empty:
            metrics_out["26SP_N1_sim_mean"] = float(n1_sub["SIM_DRY_CUM"].mean())
        if not n3_sub.empty:
            metrics_out["26SP_N3_sim_mean"] = float(n3_sub["SIM_DRY_CUM"].mean())
        if not n0_sub.empty and not n1_sub.empty:
            metrics_out["26SP_N1_minus_N0_sim_gap"] = float(n1_sub["SIM_DRY_CUM"].mean() - n0_sub["SIM_DRY_CUM"].mean())

    # 2. 25SP harvest metrics
    h25_csv = work_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv"
    if h25_csv.exists():
        df_h25 = pd.read_csv(h25_csv)
        h_end25 = df_h25.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        y25 = h_end25["OBS_DRY_CUM"].to_numpy(float)
        p25 = h_end25["SIM_DRY_CUM"].to_numpy(float)
        err25 = p25 - y25
        rmse25 = float(np.sqrt(np.mean(err25**2)))
        rrmse25 = float(100 * rmse25 / np.mean(y25)) if np.mean(y25) > 0 else np.nan
        metrics_out["25SP_term_dry_obs_mean"] = float(np.mean(y25))
        metrics_out["25SP_term_dry_sim_mean"] = float(np.mean(p25))
        metrics_out["25SP_term_dry_bias"] = float(np.mean(err25))
        metrics_out["25SP_term_dry_rrmse_pct"] = rrmse25

    # 3. Process LAI / Biomass metrics
    for season in ("25SP", "26SP"):
        proc_csv = work_dir / f"_seasons/{season}/{season}_deterministic_process_compare.csv"
        if proc_csv.exists():
            df_p = pd.read_csv(proc_csv)
            for var in ("LAID", "LWAD", "SWAD"):
                if f"OBS_{var}" in df_p.columns and f"SIM_{var}" in df_p.columns:
                    y_v = pd.to_numeric(df_p[f"OBS_{var}"], errors="coerce").to_numpy(float)
                    p_v = pd.to_numeric(df_p[f"SIM_{var}"], errors="coerce").to_numpy(float)
                    ok = ~np.isnan(y_v) & ~np.isnan(p_v) & (y_v > -90) & (p_v > -90)
                    if ok.sum() > 3:
                        y_v = y_v[ok]
                        p_v = p_v[ok]
                        sst = float(np.sum((y_v - y_v.mean())**2))
                        metrics_out[f"{season}_{var}_NSE"] = float(1 - np.sum((p_v - y_v)**2) / sst) if sst > 0 else np.nan

    return metrics_out


def run_all() -> pd.DataFrame:
    base_df = load_base_params()
    EXP_DIR.mkdir(parents=True, exist_ok=True)

    profiles = {
        # Stage 1: Photosynthesis & Canopy
        "PHTMAX": [45.0, 55.0, 68.29, 75.0, 85.0],
        "PGEFF": [0.038, 0.048, 0.052, 0.060, 0.070],
        "PARMAX": [35.0, 42.0, 50.0, 60.0],
        "TRIFL": [0.50, 0.65, 0.772, 0.90, 1.10],
        "LFMAX": [1.30, 1.50, 1.70, 2.00],
        "LNGSH": [15.0, 20.0, 29.2, 40.0],
        # Stage 1: Fruit partition & duration
        "SFDUR": [35.0, 45.0, 50.0, 58.0, 65.0],
        "WTFSD": [0.40, 0.50, 0.60, 0.70],
        "XFRMAX": [0.085, 0.15, 0.22, 0.30],
        "PORPT": [0.18, 0.28, 0.35, 0.45],
        "CMOBMX": [0.001, 0.05, 0.10, 0.20],
        # Stage 2: Nitrogen response & uptake
        "NRMIN": [0.30, 0.50, 0.70, 0.80, 0.90],
        "NREXP": [0.20, 0.50, 0.80, 1.20],
        "NSTFAC": [0.60, 0.80, 0.95, 1.00],
        "NMOBMX": [0.02, 0.10, 0.20, 0.35],
    }

    records: list[dict[str, Any]] = []

    print("Running baseline anchor (Member 153)...", flush=True)
    m_base = evaluate_param_set(base_df, EXP_DIR / "anchor_153")
    m_base["param_group"] = "BASELINE"
    m_base["param_name"] = "ANCHOR_153"
    m_base["param_val"] = np.nan
    records.append(m_base)
    print(f"Anchor 153: 26SP RRMSE={m_base.get('26SP_term_dry_rrmse_pct', np.nan):.2f}%, 25SP RRMSE={m_base.get('25SP_term_dry_rrmse_pct', np.nan):.2f}%, 26SP_H3_gap={m_base.get('26SP_H3_inc_gap', np.nan):.1f}", flush=True)

    for p_name, p_vals in profiles.items():
        print(f"\n--- Running profile for {p_name}: {p_vals} ---", flush=True)
        for val in p_vals:
            work_dir = EXP_DIR / f"prof_{p_name}_{val}"
            df_cur = base_df.copy()
            idx = df_cur[df_cur["name"].str.upper() == p_name.upper()].index
            if not idx.empty:
                df_cur.loc[idx, "value"] = val
            else:
                df_cur = pd.concat([df_cur, pd.DataFrame([{"name": p_name.lower(), "value": val}])], ignore_index=True)

            m = evaluate_param_set(df_cur, work_dir)
            m["param_group"] = "PROFILE"
            m["param_name"] = p_name
            m["param_val"] = val
            records.append(m)
            print(f"  {p_name}={val:<6}: 26SP_H3_inc={m.get('26SP_H3_sim_inc_mean', 0):>6.1f} (gap={m.get('26SP_H3_inc_gap', 0):>6.1f}), 26SP_RRMSE={m.get('26SP_term_dry_rrmse_pct', 0):>5.1f}%, 25SP_RRMSE={m.get('25SP_term_dry_rrmse_pct', 0):>5.1f}%, 26SP_LAI_NSE={m.get('26SP_LAID_NSE', 0):>5.2f}", flush=True)

    df_all = pd.DataFrame(records)
    out_csv = EXP_DIR / "profile_experiment_results.csv"
    df_all.to_csv(out_csv, index=False)
    print(f"\nAll profile experiments completed! Saved to {out_csv}", flush=True)
    return df_all


if __name__ == "__main__":
    df_res = run_all()
