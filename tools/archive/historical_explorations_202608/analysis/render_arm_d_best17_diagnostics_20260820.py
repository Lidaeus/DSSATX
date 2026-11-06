"""Robust deterministic comparison generator and diagnostic plotter for Arm D Best Member #17."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DET_ROOT = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17"
OUT_ROOT = ROOT / "figture/e02_arm_d_full_synergy_best17_two_season_20260820"
REGISTRY_CSV = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/e02_arm_d_full_synergy_50x3_20260820_observation_registry.csv"
MAPPING_CSV = DET_ROOT / "two_season_water_n_mapping_from_filex.csv"

import sys
sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    _parse_batch_entries,
    _read_freshwt_var_by_run,
    _read_plantgro_vars_by_run,
    _read_tmt_harvest_obs,
    _read_tmt_process_obs,
    _yyddd_add_days,
    _yyddd_day_difference,
    _nearest_on_or_before,
)


def compute_metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float | int]:
    valid = ~np.isnan(obs) & ~np.isnan(sim) & (obs != -99) & (sim != -99)
    if valid.sum() == 0:
        return {"rmse": np.nan, "rrmse_pct": np.nan, "mae": np.nan, "bias": np.nan, "nse": np.nan, "d_index": np.nan, "r2": np.nan}
    o = obs[valid]
    s = sim[valid]
    err = s - o
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    mean_obs = float(np.mean(o))
    rrmse = float(100.0 * rmse / mean_obs) if mean_obs > 0 else np.nan
    bias = float(np.mean(err))
    
    sst = float(np.sum((o - mean_obs)**2))
    nse = float(1.0 - (np.sum(err**2) / sst)) if sst > 0 else np.nan
    
    denom_d = float(np.sum((np.abs(s - mean_obs) + np.abs(o - mean_obs))**2))
    d_index = float(1.0 - (np.sum(err**2) / denom_d)) if denom_d > 0 else np.nan
    
    r2 = float(np.corrcoef(o, s)[0, 1]**2) if len(o) > 1 and o.std() > 0 and s.std() > 0 else np.nan
    return {"rmse": rmse, "rrmse_pct": rrmse, "mae": mae, "bias": bias, "nse": nse, "d_index": d_index, "r2": r2}


def get_run_to_tn_map(sdir: Path) -> dict[int, int]:
    pg_file = sdir / "PlantGro.OUT"
    if not pg_file.exists():
        return {}
    run_to_tn = {}
    for line in pg_file.read_text(errors="ignore").splitlines():
        if line.startswith("*RUN"):
            m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", line)
            if m:
                run_to_tn[int(m.group(1))] = int(m.group(2))
    return run_to_tn


def build_season_harvest_compare(sdir: Path, season_id: str) -> pd.DataFrame:
    excode = "XXQL2501" if season_id == "25SP" else ("XXQL2502" if season_id == "25FA" else "XXQL2601")
    tmt_path = sdir / f"{excode}.TMT"
    freshwt_path = sdir / "FreshWt.OUT"
    
    run_to_tn = get_run_to_tn_map(sdir)
    obs_by_tn = _read_tmt_harvest_obs(str(tmt_path))
    sim_chpdt = _read_freshwt_var_by_run(str(freshwt_path), "CHPDT")
    sim_chfpw = _read_freshwt_var_by_run(str(freshwt_path), "CHFPW")
    
    rows = []
    for run_no, tn in sorted(run_to_tn.items()):
        obs_events = obs_by_tn.get(tn, [])
        prev_sim_dry = None
        prev_sim_fresh = None
        for ev in obs_events:
            date = int(ev["DATE"])
            sim_date = _yyddd_add_days(date, 1)
            sim_dry_cum = _nearest_on_or_before(sim_chpdt.get(run_no, {}), sim_date)
            sim_fresh_cum = _nearest_on_or_before(sim_chfpw.get(run_no, {}), sim_date)
            sim_dry_cum = float(sim_dry_cum) if sim_dry_cum is not None else np.nan
            sim_fresh_cum = float(sim_fresh_cum) if sim_fresh_cum is not None else np.nan

            if prev_sim_dry is None or np.isnan(prev_sim_dry):
                sim_dry_inc = sim_dry_cum
            elif np.isnan(sim_dry_cum):
                sim_dry_inc = np.nan
            else:
                sim_dry_inc = sim_dry_cum - prev_sim_dry

            if prev_sim_fresh is None or np.isnan(prev_sim_fresh):
                sim_fresh_inc = sim_fresh_cum
            elif np.isnan(sim_fresh_cum):
                sim_fresh_inc = np.nan
            else:
                sim_fresh_inc = sim_fresh_cum - prev_sim_fresh

            prev_sim_dry = sim_dry_cum
            prev_sim_fresh = sim_fresh_cum

            rows.append(
                {
                    "RUN": run_no,
                    "TN": tn,
                    **ev,
                    "SIM_DRY_CUM": sim_dry_cum,
                    "SIM_DRY_INC": sim_dry_inc,
                    "SIM_FRESH_CUM": sim_fresh_cum,
                    "SIM_FRESH_INC": sim_fresh_inc,
                }
            )
    df = pd.DataFrame(rows)
    out_csv = sdir / f"{season_id}_deterministic_harvest_compare.csv"
    df.to_csv(out_csv, index=False)
    return df


def build_season_process_compare(sdir: Path, season_id: str) -> pd.DataFrame:
    excode = "XXQL2501" if season_id == "25SP" else ("XXQL2502" if season_id == "25FA" else "XXQL2601")
    tmt_path = sdir / f"{excode}.TMT"
    plantgro_path = sdir / "PlantGro.OUT"
    
    run_to_tn = get_run_to_tn_map(sdir)
    vars_list = ["LAID", "LWAD", "SWAD", "CHTD"]
    obs_by_tn = _read_tmt_process_obs(str(tmt_path), vars_list)
    sim_by_run = _read_plantgro_vars_by_run(str(plantgro_path), vars_list)
    
    rows = []
    for run_no, tn in sorted(run_to_tn.items()):
        obs_pts = obs_by_tn.get(tn, [])
        sim_candidates = sim_by_run.get(run_no, {})
        sim_dates_sorted = sorted(sim_candidates.keys())

        for p in obs_pts:
            date = int(p["DATE"])
            sim_day = None
            sim_date_used = None
            if date in sim_candidates:
                sim_day = sim_candidates[date]
                sim_date_used = date
            else:
                prev_dates = [d for d in sim_dates_sorted if d <= date]
                if prev_dates:
                    sim_date_used = prev_dates[-1]
                    sim_day = sim_candidates[sim_date_used]

            row = {
                "RUN": run_no, "TN": tn, "DATE": date,
                "SIM_DATE": sim_date_used,
                "SIM_DATE_GAP_DAYS": (
                    _yyddd_day_difference(sim_date_used, date)
                    if sim_date_used is not None else np.nan
                ),
            }
            for v in vars_list:
                row[f"OBS_{v}"] = float(p.get(f"OBS_{v}", -99.0))
                if sim_day is None:
                    row[f"SIM_{v}"] = np.nan
                else:
                    row[f"SIM_{v}"] = float(sim_day.get(v, np.nan))
            rows.append(row)

    df = pd.DataFrame(rows)
    out_csv = sdir / f"{season_id}_deterministic_process_compare.csv"
    df.to_csv(out_csv, index=False)
    return df


def run_diagnostics():
    print(f"Building comparison files for {DET_ROOT}...")
    metrics_rows = []
    
    for season in ["25SP", "26SP"]:
        sdir = DET_ROOT / "_seasons" / season
        print(f"Processing {season} in {sdir}...")
        
        # 1. Harvest compare
        h_compare = build_season_harvest_compare(sdir, season)
        print(f"  Wrote {season}_deterministic_harvest_compare.csv ({len(h_compare)} rows)")
        for vcol in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
            obs_c = f"OBS_{vcol}"
            sim_c = f"SIM_{vcol}"
            if obs_c in h_compare.columns and sim_c in h_compare.columns:
                m = compute_metrics(h_compare[obs_c].to_numpy(float), h_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "harvest", "variable": vcol, "n": len(h_compare)})
                metrics_rows.append(m)

        # 2. Process compare
        p_compare = build_season_process_compare(sdir, season)
        print(f"  Wrote {season}_deterministic_process_compare.csv ({len(p_compare)} rows)")
        for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
            obs_c = f"OBS_{var}"
            sim_c = f"SIM_{var}"
            if obs_c in p_compare.columns and sim_c in p_compare.columns:
                m = compute_metrics(p_compare[obs_c].to_numpy(float), p_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "process", "variable": var, "n": len(p_compare)})
                metrics_rows.append(m)

    # Save metrics summary
    metrics_df = pd.DataFrame(metrics_rows)
    metrics_path = DET_ROOT / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print(f"\nSaved metrics summary to: {metrics_path}")
    print(metrics_df[["season", "kind", "variable", "n", "rmse", "mae", "nse", "d_index", "r2"]].to_string(index=False))

    # Render plots
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(DET_ROOT),
        "--out-root", str(OUT_ROOT),
        "--seasons", "25SP,26SP",
        "--registry-csv", str(REGISTRY_CSV),
        "--include-all-treatments",
        "--mapping-csv", str(MAPPING_CSV)
    ]
    print(f"\nRendering diagnostic plots to: {OUT_ROOT}...")
    subprocess.run(cmd_plot, cwd=ROOT, check=True)
    print("Diagnostic plots generated successfully in:", OUT_ROOT)


if __name__ == "__main__":
    run_diagnostics()
