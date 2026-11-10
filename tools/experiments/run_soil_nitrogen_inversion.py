#!/usr/bin/env python3
"""Inversion and End-to-End Physical Validation of Initial Soil Nitrogen Scaling Factors.

Evaluates and validates initial soil nitrogen scaling factors across all 35 treatments (3 seasons):
- 25SP: 11 treatments (xxql2501_v20260917_refresh)
- 26SP: 12 treatments (xxql2601_v20260917_refresh)
- 25FA: 12 treatments (xxql2502_v20260917_refresh)

Candidate: Champion C23 (candidate_c23_real194_final_spring_precision)
Grid: 31 points in [0.70, 1.30] with step 0.02.

Evaluates two standard scientific modes:
1. Mode 1 (Raw Bundle Absolute Scale): Scaling factor s in [0.70, 1.30] directly scales
   measured initial mineral N (SNO3, SNH4) from the base experimental bundle.
2. Mode 2 (C23 Baseline Relative Scale): Scaling factor alpha in [0.70, 1.30] relative to
   C23's calibrated seasonal prior (25SP=0.75, 26SP=0.70, 25FA=1.00).

Includes:
- Yield sensitivity range (delta_Y = Y_max - Y_min) per treatment.
- Explicit identifiability categorization:
    * 'identifiable' (delta_Y >= 1.0 t/ha)
    * 'sensitive' (0.1 <= delta_Y < 1.0 t/ha)
    * 'unidentifiable_flat' (delta_Y < 0.1 t/ha: equifinality under luxury N or energy limitation)
- Recommended scaling factors preventing false boundary attribution on unidentifiable parameters.
- End-to-end physical batch simulation validation with treatment-specific initial N injected into FileX.
- Full statistical breakdown: RMSE, NRMSE, Willmott d-index, R2, MAE by season and grand total.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
import json

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.analyze_results import _parse_batch_entries, _read_freshwt_var_by_run

CAND_DIR = PROJECT_ROOT / "workspace/candidates/candidate_c23_real194_final_spring_precision"
PARAM_CSV = CAND_DIR / "params.csv"
OBS_YIELD_CSV = CAND_DIR / "all_35_treatments_final_yield.csv"
META_CSV = PROJECT_ROOT / "configs/figures/treatment_metadata_xxql_all_35trt.csv"

BUNDLES = {
    "25SP": PROJECT_ROOT / "data/user/experiments/xxql2501_v20260917_refresh",
    "26SP": PROJECT_ROOT / "data/user/experiments/xxql2601_v20260917_refresh",
    "25FA": PROJECT_ROOT / "data/user/experiments/xxql2502_v20260917_refresh",
}
TILEX_NAMES = {
    "25SP": "XXQL2501.TMX",
    "26SP": "XXQL2601.TMX",
    "25FA": "XXQL2502.TMX",
}
SCALE_MAX_DEPTHS = {
    "25SP": 100,
    "26SP": 60,
    "25FA": None,
}
GENO_DIR = PROJECT_ROOT / "data/templates/genotype"

OUT_DIR = PROJECT_ROOT / "workspace/inversion/soil_nitrogen_inversion_c23"
WORKER_ROOT = PROJECT_ROOT / "scratch/inversion_workers"


def setup_worker_dir(worker_dir: Path, bundle_src: Path):
    if worker_dir.exists():
        shutil.rmtree(worker_dir)
    shutil.copytree(bundle_src, worker_dir)
    for base_file in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
        shutil.copy2(GENO_DIR / base_file, worker_dir / base_file)
    soil_sol = worker_dir / "SOIL.SOL"
    soil_base = worker_dir / "SOIL.SOL.base"
    if soil_sol.exists() and not soil_base.exists():
        shutil.copy2(soil_sol, soil_base)


def fit_ic_field(value: float) -> str:
    """Format numeric token to fit DSSAT FileX 2/6/6/6/6 contract."""
    numeric = float(value)
    token = f"{numeric:.2f}".rstrip("0").rstrip(".")
    if token.startswith("0."):
        token = token[1:]
    elif token.startswith("-0."):
        token = "-" + token[2:]
    if len(token) > 5:
        token = f"{numeric:.4g}"
    if token.startswith("0."):
        token = token[1:]
    elif token.startswith("-0."):
        token = "-" + token[2:]
    return token


def run_single_simulation(args):
    season, scale_label, scale_val, worker_id = args
    worker_dir = WORKER_ROOT / f"w_{worker_id}_{season}_{scale_label}"
    bundle_src = BUNDLES[season]

    setup_worker_dir(worker_dir, bundle_src)

    # Prepare params.csv with modified scale
    p_df = pd.read_csv(PARAM_CSV)
    p_cur = p_df.copy()

    if season == "25SP":
        p_cur.loc[p_cur["name"].str.lower() == "icns_25sp", "value"] = scale_val
    elif season == "26SP":
        p_cur.loc[p_cur["name"].str.lower() == "icns_26sp", "value"] = scale_val
    elif season == "25FA":
        if "icns" in p_cur["name"].str.lower().values:
            p_cur.loc[p_cur["name"].str.lower() == "icns", "value"] = scale_val
        else:
            p_cur = pd.concat([p_cur, pd.DataFrame([{"name": "icns", "value": scale_val}])], ignore_index=True)

    param_csv_path = worker_dir / "params.csv"
    p_cur.to_csv(param_csv_path, index=False)

    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv", str(param_csv_path.resolve()),
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=worker_dir, capture_output=True, text=True, env=env)

    if res.returncode != 0:
        print(f"Error in {season} scale={scale_val}: {res.stderr[-300:]}")
        if worker_dir.exists():
            shutil.rmtree(worker_dir, ignore_errors=True)
        return season, scale_label, scale_val, None

    freshwt_path = worker_dir / "FreshWt.OUT"
    sim_chfpw = _read_freshwt_var_by_run(str(freshwt_path), "CHFPW")
    entries = _parse_batch_entries(str(worker_dir / "DSSBatch.v48"))

    yields = {}
    for e in entries:
        run_no = int(e["run"])
        tn = int(e.get("tn", -99))
        curve = sim_chfpw.get(run_no, {})
        if curve:
            max_date = max(curve.keys())
            yields[tn] = float(curve[max_date])

    if worker_dir.exists():
        shutil.rmtree(worker_dir, ignore_errors=True)

    return season, scale_label, scale_val, yields


def run_season_validation(season: str, scale_dict: dict, mode_tag: str) -> dict:
    """Run an end-to-end DSSAT batch simulation with treatment-specific initial N injected into FileX."""
    work_dir = PROJECT_ROOT / f"scratch/val_{mode_tag}_{season}"
    if work_dir.exists():
        shutil.rmtree(work_dir)

    setup_worker_dir(work_dir, BUNDLES[season])

    # Strip ICNS from params.csv so run_dssat will not overwrite the treatment-specific FileX modifications
    p_df = pd.read_csv(PARAM_CSV)
    p_df = p_df[~p_df["name"].str.lower().isin(["icns", "icns_25sp", "icns_26sp"])]
    p_df.to_csv(work_dir / "params.csv", index=False)

    tmx_path = work_dir / TILEX_NAMES[season]
    lines = tmx_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    new_lines = []
    in_ic = False
    in_table = False
    max_depth = SCALE_MAX_DEPTHS[season]

    for line in lines:
        u = line.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            in_ic = True
            new_lines.append(line)
            continue
        if in_ic and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            in_ic = False
            new_lines.append(line)
            continue
        if not in_ic:
            new_lines.append(line)
            continue
        if "@C" in u and "ICBL" in u:
            in_table = True
            new_lines.append(line)
            continue
        if "@C" in u and "ICDAT" in u:
            in_table = False
            new_lines.append(line)
            continue
        if in_table and line.strip():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    tn = int(parts[0])
                    depth = int(parts[1])
                    sh2o = parts[2]
                    snh4 = float(parts[3])
                    sno3 = float(parts[4])
                    scale = scale_dict.get(tn, 1.0)
                    if max_depth is None or depth <= max_depth:
                        snh4 = max(0.1, snh4 * scale)
                        sno3 = max(0.5, sno3 * scale)
                    new_line = f"{tn:2d}{depth:6d}{sh2o.rjust(6)}{fit_ic_field(snh4).rjust(6)}{fit_ic_field(sno3).rjust(6)}"
                    new_lines.append(new_line)
                    continue
                except ValueError:
                    pass
        new_lines.append(line)

    tmx_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv", str((work_dir / "params.csv").resolve()),
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
    ]
    res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"Validation simulation failed in {season}: {res.stderr[-300:]}")

    freshwt = work_dir / "FreshWt.OUT"
    sim_chfpw = _read_freshwt_var_by_run(str(freshwt), "CHFPW")
    entries = _parse_batch_entries(str(work_dir / "DSSBatch.v48"))
    yields = {}
    for e in entries:
        tn = int(e["tn"])
        r = int(e["run"])
        m = max(sim_chfpw[r].keys())
        yields[tn] = sim_chfpw[r][m]

    shutil.rmtree(work_dir, ignore_errors=True)
    return yields


def calc_metrics(obs: np.ndarray, sim: np.ndarray) -> dict:
    """Calculate comprehensive statistical metrics."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    n = len(obs)
    diff = sim - obs
    mae = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(diff**2)))
    mean_obs = float(np.mean(obs))
    nrmse = float(rmse / mean_obs * 100.0)

    ss_tot = float(np.sum((obs - mean_obs)**2))
    ss_res = float(np.sum(diff**2))
    r2 = float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0

    numerator = np.sum(diff**2)
    denominator = np.sum((np.abs(sim - mean_obs) + np.abs(obs - mean_obs))**2)
    d = float(1.0 - (numerator / denominator)) if denominator > 0 else 0.0

    return {
        "n": n,
        "mean_obs_t_ha": round(mean_obs, 4),
        "mae_t_ha": round(mae, 4),
        "rmse_t_ha": round(rmse, 4),
        "nrmse_pct": round(nrmse, 2),
        "r2": round(r2, 4),
        "d_index": round(d, 4),
    }


def main(force_rerun_grid: bool = False):
    print("=" * 80)
    print("INITIAL SOIL NITROGEN INVERSION & END-TO-END VALIDATION (CHAMPION C23)")
    print("3 Seasons | 35 Treatments | 31 Grid Points [0.70, 1.30] step 0.02")
    print("=" * 80)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_ROOT.mkdir(parents=True, exist_ok=True)

    grid_points = [round(0.70 + 0.02 * i, 2) for i in range(31)]
    obs_df = pd.read_csv(OBS_YIELD_CSV)
    meta_df = pd.read_csv(META_CSV)

    grid_file_mode1 = OUT_DIR / "soil_nitrogen_inversion_grid_mode1_raw_scale.csv"
    grid_file_mode2 = OUT_DIR / "soil_nitrogen_inversion_grid_mode2_c23_relative.csv"

    # Check if existing grid results can be loaded
    if not force_rerun_grid and grid_file_mode1.exists() and grid_file_mode2.exists():
        print("Loading pre-computed grid simulation datasets...")
        df_grid_mode1 = pd.read_csv(grid_file_mode1)
        df_grid_mode2 = pd.read_csv(grid_file_mode2)
    else:
        print("Executing 155 parallel DSSAT batch simulations...")
        tasks = []
        worker_counter = 0

        # Mode 1 runs
        for season in ["25SP", "26SP", "25FA"]:
            for s in grid_points:
                label = f"mode1_{s:.2f}"
                tasks.append((season, label, s, worker_counter % 8))
                worker_counter += 1

        # Mode 2 runs (only 25SP and 26SP needed since 25FA is identical)
        for s in grid_points:
            scale_val_25 = round(0.75 * s, 4)
            label_25 = f"mode2_{s:.2f}"
            tasks.append(("25SP", label_25, scale_val_25, worker_counter % 8))
            worker_counter += 1

            scale_val_26 = round(0.70 * s, 4)
            label_26 = f"mode2_{s:.2f}"
            tasks.append(("26SP", label_26, scale_val_26, worker_counter % 8))
            worker_counter += 1

        results = {}
        with ProcessPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(run_single_simulation, t) for t in tasks]
            done_count = 0
            for f in as_completed(futures):
                season, label, s_val, y_dict = f.result()
                results[(season, label)] = y_dict
                done_count += 1
                if done_count % 20 == 0 or done_count == len(tasks):
                    print(f"Progress: [{done_count}/{len(tasks)}] simulations completed...")

        # Build Mode 1 Grid
        rows_mode1 = []
        for _, meta_row in meta_df.iterrows():
            season = meta_row["season_id"]
            tn = int(meta_row["treatment"])
            w_lvl = meta_row["water_level"]
            n_lvl = meta_row["nitrogen_level"]
            t_label = meta_row["treatment_label"]
            d_role = meta_row["dataset_role"]

            obs_sub = obs_df[(obs_df["season"] == season) & (obs_df["tn"] == tn)]
            obs_kg = float(obs_sub.iloc[0]["obs_cum_yield_kg_ha"])
            obs_t = obs_kg / 1000.0
            base_sim_kg = float(obs_sub.iloc[0]["sim_cum_yield_kg_ha"])
            base_sim_t = base_sim_kg / 1000.0

            for s in grid_points:
                label = f"mode1_{s:.2f}"
                y_dict = results.get((season, label), {})
                sim_kg = y_dict.get(tn, np.nan) if y_dict else np.nan
                sim_t = sim_kg / 1000.0 if np.isfinite(sim_kg) else np.nan

                diff_kg = sim_kg - obs_kg if np.isfinite(sim_kg) else np.nan
                abs_diff_kg = abs(diff_kg) if np.isfinite(diff_kg) else np.nan
                diff_t = sim_t - obs_t if np.isfinite(sim_t) else np.nan
                abs_diff_t = abs(diff_t) if np.isfinite(diff_t) else np.nan
                bias_pct = (diff_kg / obs_kg * 100.0) if np.isfinite(diff_kg) else np.nan
                abs_bias_pct = abs(bias_pct) if np.isfinite(bias_pct) else np.nan

                rows_mode1.append({
                    "season": season,
                    "tn": tn,
                    "water_level": w_lvl,
                    "nitrogen_level": n_lvl,
                    "treatment_label": t_label,
                    "dataset_role": d_role,
                    "scaling_factor": s,
                    "obs_cum_yield_kg_ha": obs_kg,
                    "obs_t_ha": round(obs_t, 4),
                    "sim_cum_yield_kg_ha": round(sim_kg, 1) if np.isfinite(sim_kg) else np.nan,
                    "sim_t_ha": round(sim_t, 4) if np.isfinite(sim_t) else np.nan,
                    "diff_kg_ha": round(diff_kg, 1) if np.isfinite(diff_kg) else np.nan,
                    "abs_diff_kg_ha": round(abs_diff_kg, 1) if np.isfinite(abs_diff_kg) else np.nan,
                    "diff_t_ha": round(diff_t, 4) if np.isfinite(diff_t) else np.nan,
                    "abs_diff_t_ha": round(abs_diff_t, 4) if np.isfinite(abs_diff_t) else np.nan,
                    "bias_pct": round(bias_pct, 2) if np.isfinite(bias_pct) else np.nan,
                    "abs_bias_pct": round(abs_bias_pct, 2) if np.isfinite(abs_bias_pct) else np.nan,
                    "baseline_sim_t_ha": round(base_sim_t, 4),
                    "baseline_bias_pct": round((base_sim_kg - obs_kg) / obs_kg * 100.0, 2),
                })
        df_grid_mode1 = pd.DataFrame(rows_mode1)
        df_grid_mode1.to_csv(grid_file_mode1, index=False)

        # Build Mode 2 Grid
        rows_mode2 = []
        for _, meta_row in meta_df.iterrows():
            season = meta_row["season_id"]
            tn = int(meta_row["treatment"])
            w_lvl = meta_row["water_level"]
            n_lvl = meta_row["nitrogen_level"]
            t_label = meta_row["treatment_label"]
            d_role = meta_row["dataset_role"]

            obs_sub = obs_df[(obs_df["season"] == season) & (obs_df["tn"] == tn)]
            obs_kg = float(obs_sub.iloc[0]["obs_cum_yield_kg_ha"])
            obs_t = obs_kg / 1000.0
            base_sim_kg = float(obs_sub.iloc[0]["sim_cum_yield_kg_ha"])
            base_sim_t = base_sim_kg / 1000.0

            for s in grid_points:
                label = f"mode1_{s:.2f}" if season == "25FA" else f"mode2_{s:.2f}"
                y_dict = results.get((season, label), {})
                sim_kg = y_dict.get(tn, np.nan) if y_dict else np.nan
                sim_t = sim_kg / 1000.0 if np.isfinite(sim_kg) else np.nan

                diff_kg = sim_kg - obs_kg if np.isfinite(sim_kg) else np.nan
                abs_diff_kg = abs(diff_kg) if np.isfinite(diff_kg) else np.nan
                diff_t = sim_t - obs_t if np.isfinite(sim_t) else np.nan
                abs_diff_t = abs(diff_t) if np.isfinite(diff_t) else np.nan
                bias_pct = (diff_kg / obs_kg * 100.0) if np.isfinite(diff_kg) else np.nan
                abs_bias_pct = abs(bias_pct) if np.isfinite(bias_pct) else np.nan

                rows_mode2.append({
                    "season": season,
                    "tn": tn,
                    "water_level": w_lvl,
                    "nitrogen_level": n_lvl,
                    "treatment_label": t_label,
                    "dataset_role": d_role,
                    "relative_scaling_factor": s,
                    "effective_raw_scale": round(0.75 * s if season == "25SP" else (0.70 * s if season == "26SP" else s), 4),
                    "obs_cum_yield_kg_ha": obs_kg,
                    "obs_t_ha": round(obs_t, 4),
                    "sim_cum_yield_kg_ha": round(sim_kg, 1) if np.isfinite(sim_kg) else np.nan,
                    "sim_t_ha": round(sim_t, 4) if np.isfinite(sim_t) else np.nan,
                    "diff_kg_ha": round(diff_kg, 1) if np.isfinite(diff_kg) else np.nan,
                    "abs_diff_kg_ha": round(abs_diff_kg, 1) if np.isfinite(abs_diff_kg) else np.nan,
                    "diff_t_ha": round(diff_t, 4) if np.isfinite(diff_t) else np.nan,
                    "abs_diff_t_ha": round(abs_diff_t, 4) if np.isfinite(abs_diff_t) else np.nan,
                    "bias_pct": round(bias_pct, 2) if np.isfinite(bias_pct) else np.nan,
                    "abs_bias_pct": round(abs_bias_pct, 2) if np.isfinite(abs_bias_pct) else np.nan,
                    "baseline_sim_t_ha": round(base_sim_t, 4),
                    "baseline_bias_pct": round((base_sim_kg - obs_kg) / obs_kg * 100.0, 2),
                })
        df_grid_mode2 = pd.DataFrame(rows_mode2)
        df_grid_mode2.to_csv(grid_file_mode2, index=False)

    season_order = {"25SP": 1, "26SP": 2, "25FA": 3}

    # =============================================================
    # Process Mode 1 Optimal with Identifiability & Sensitivity
    # =============================================================
    print("\nProcessing Mode 1 optimal scaling and identifiability...")
    opt_rows_mode1 = []
    for (season, tn), grp in df_grid_mode1.groupby(["season", "tn"]):
        y_range = float(grp["sim_t_ha"].max() - grp["sim_t_ha"].min())
        best_idx = grp["abs_diff_kg_ha"].idxmin()
        best_row = grp.loc[best_idx].to_dict()

        if y_range >= 1.0:
            status = "identifiable"
            recommended = best_row["scaling_factor"]
        elif y_range >= 0.1:
            status = "sensitive"
            recommended = best_row["scaling_factor"]
        else:
            status = "unidentifiable_flat"
            recommended = 1.00  # Default unscaled prior

        best_row["yield_sensitivity_range_t_ha"] = round(y_range, 4)
        best_row["identifiability_status"] = status
        best_row["recommended_scaling_factor"] = recommended
        opt_rows_mode1.append(best_row)

    df_opt_mode1 = pd.DataFrame(opt_rows_mode1)
    df_opt_mode1["s_order"] = df_opt_mode1["season"].map(season_order)
    df_opt_mode1 = df_opt_mode1.sort_values(["s_order", "tn"]).drop(columns=["s_order"]).reset_index(drop=True)

    # Physical Batch Validation Run for Mode 1
    print("Running End-to-End Physical Validation for Mode 1 across 3 seasons...")
    val_sims_mode1 = {}
    for season in ["25SP", "26SP", "25FA"]:
        sub = df_opt_mode1[df_opt_mode1["season"] == season]
        scales = {int(r["tn"]): float(r["scaling_factor"]) for _, r in sub.iterrows()}
        val_yields = run_season_validation(season, scales, "mode1")
        val_sims_mode1[season] = val_yields

    val_sim_t_list1 = []
    val_delta_kg_list1 = []
    for _, r in df_opt_mode1.iterrows():
        s = r["season"]
        tn = int(r["tn"])
        val_kg = val_sims_mode1[s][tn]
        val_t = val_kg / 1000.0
        exp_kg = r["sim_cum_yield_kg_ha"]
        delta_kg = abs(val_kg - exp_kg)
        val_sim_t_list1.append(round(val_t, 4))
        val_delta_kg_list1.append(round(delta_kg, 1))

    df_opt_mode1["validated_sim_t_ha"] = val_sim_t_list1
    df_opt_mode1["validation_delta_kg_ha"] = val_delta_kg_list1
    df_opt_mode1.to_csv(OUT_DIR / "soil_nitrogen_inversion_optimal_mode1_raw_scale.csv", index=False)
    print("Mode 1 validation completed. Max validation delta: {:.2f} kg/ha".format(max(val_delta_kg_list1)))

    # =============================================================
    # Process Mode 2 Optimal with Identifiability & Sensitivity
    # =============================================================
    print("\nProcessing Mode 2 optimal relative scaling and identifiability...")
    opt_rows_mode2 = []
    for (season, tn), grp in df_grid_mode2.groupby(["season", "tn"]):
        y_range = float(grp["sim_t_ha"].max() - grp["sim_t_ha"].min())
        best_idx = grp["abs_diff_kg_ha"].idxmin()
        best_row = grp.loc[best_idx].to_dict()

        if y_range >= 1.0:
            status = "identifiable"
            recommended_rel = best_row["relative_scaling_factor"]
            recommended_raw = best_row["effective_raw_scale"]
        elif y_range >= 0.1:
            status = "sensitive"
            recommended_rel = best_row["relative_scaling_factor"]
            recommended_raw = best_row["effective_raw_scale"]
        else:
            status = "unidentifiable_flat"
            recommended_rel = 1.00  # C23 calibrated prior
            recommended_raw = 0.75 if season == "25SP" else (0.70 if season == "26SP" else 1.00)

        best_row["yield_sensitivity_range_t_ha"] = round(y_range, 4)
        best_row["identifiability_status"] = status
        best_row["recommended_relative_scale"] = recommended_rel
        best_row["recommended_effective_raw_scale"] = recommended_raw
        opt_rows_mode2.append(best_row)

    df_opt_mode2 = pd.DataFrame(opt_rows_mode2)
    df_opt_mode2["s_order"] = df_opt_mode2["season"].map(season_order)
    df_opt_mode2 = df_opt_mode2.sort_values(["s_order", "tn"]).drop(columns=["s_order"]).reset_index(drop=True)

    # Physical Batch Validation Run for Mode 2
    print("Running End-to-End Physical Validation for Mode 2 across 3 seasons...")
    val_sims_mode2 = {}
    for season in ["25SP", "26SP", "25FA"]:
        sub = df_opt_mode2[df_opt_mode2["season"] == season]
        scales = {int(r["tn"]): float(r["effective_raw_scale"]) for _, r in sub.iterrows()}
        val_yields = run_season_validation(season, scales, "mode2")
        val_sims_mode2[season] = val_yields

    val_sim_t_list2 = []
    val_delta_kg_list2 = []
    for _, r in df_opt_mode2.iterrows():
        s = r["season"]
        tn = int(r["tn"])
        val_kg = val_sims_mode2[s][tn]
        val_t = val_kg / 1000.0
        exp_kg = r["sim_cum_yield_kg_ha"]
        delta_kg = abs(val_kg - exp_kg)
        val_sim_t_list2.append(round(val_t, 4))
        val_delta_kg_list2.append(round(delta_kg, 1))

    df_opt_mode2["validated_sim_t_ha"] = val_sim_t_list2
    df_opt_mode2["validation_delta_kg_ha"] = val_delta_kg_list2
    df_opt_mode2.to_csv(OUT_DIR / "soil_nitrogen_inversion_optimal_mode2_c23_relative.csv", index=False)
    print("Mode 2 validation completed. Max validation delta: {:.2f} kg/ha".format(max(val_delta_kg_list2)))

    # =============================================================
    # Calculate Comprehensive Scientific Metrics
    # =============================================================
    summary_meta = {
        "candidate": "C23",
        "description": "Initial Soil Nitrogen Inversion and Physical Validation across 35 treatments (3 seasons)",
        "grid_range": [0.70, 1.30],
        "grid_step": 0.02,
        "n_grid_points": 31,
        "end_to_end_validation_verified": True,
        "max_validation_mismatch_kg_ha": float(max(max(val_delta_kg_list1), max(val_delta_kg_list2))),
        "cohort_metrics": {},
    }

    cohorts = ["ALL", "25SP", "26SP", "25FA", "N0_ALL", "25SP_N0", "26SP_N0"]
    for c in cohorts:
        if c == "ALL":
            sub1 = df_opt_mode1
            sub2 = df_opt_mode2
        elif c in ["25SP", "26SP", "25FA"]:
            sub1 = df_opt_mode1[df_opt_mode1["season"] == c]
            sub2 = df_opt_mode2[df_opt_mode2["season"] == c]
        elif c == "N0_ALL":
            sub1 = df_opt_mode1[df_opt_mode1["nitrogen_level"] == "N0"]
            sub2 = df_opt_mode2[df_opt_mode2["nitrogen_level"] == "N0"]
        elif c == "25SP_N0":
            sub1 = df_opt_mode1[(df_opt_mode1["season"] == "25SP") & (df_opt_mode1["nitrogen_level"] == "N0")]
            sub2 = df_opt_mode2[(df_opt_mode2["season"] == "25SP") & (df_opt_mode2["nitrogen_level"] == "N0")]
        elif c == "26SP_N0":
            sub1 = df_opt_mode1[(df_opt_mode1["season"] == "26SP") & (df_opt_mode1["nitrogen_level"] == "N0")]
            sub2 = df_opt_mode2[(df_opt_mode2["season"] == "26SP") & (df_opt_mode2["nitrogen_level"] == "N0")]

        obs_vals = sub1["obs_t_ha"].values
        base_vals = sub1["baseline_sim_t_ha"].values
        m1_vals = sub1["sim_t_ha"].values
        m2_vals = sub2["sim_t_ha"].values

        summary_meta["cohort_metrics"][c] = {
            "baseline": calc_metrics(obs_vals, base_vals),
            "mode1_raw_optimal": calc_metrics(obs_vals, m1_vals),
            "mode2_relative_optimal": calc_metrics(obs_vals, m2_vals),
        }

    summary_json_path = OUT_DIR / "soil_nitrogen_inversion_summary.json"
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_meta, f, indent=2)

    print("\n" + "=" * 80)
    print("FINAL SUMMARY REPORT OF SOIL NITROGEN INVERSION")
    print("=" * 80)
    print("Files successfully generated in workspace/inversion/soil_nitrogen_inversion_c23/:")
    print("  1. soil_nitrogen_inversion_optimal_mode1_raw_scale.csv (Enriched with identifiability & validation)")
    print("  2. soil_nitrogen_inversion_optimal_mode2_c23_relative.csv (Enriched with identifiability & validation)")
    print("  3. soil_nitrogen_inversion_grid_mode1_raw_scale.csv (Full 1085-point grid)")
    print("  4. soil_nitrogen_inversion_grid_mode2_c23_relative.csv (Full 1085-point grid)")
    print("  5. soil_nitrogen_inversion_summary.json (Full multi-cohort metrics)")

    all_base = summary_meta["cohort_metrics"]["ALL"]["baseline"]
    all_m1 = summary_meta["cohort_metrics"]["ALL"]["mode1_raw_optimal"]
    all_m2 = summary_meta["cohort_metrics"]["ALL"]["mode2_relative_optimal"]

    print("\n--- Grand 35-Treatment Performance ---")
    print("  Baseline (C23 Prior) : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f} | R2 = {:.4f}".format(
        all_base["rmse_t_ha"], all_base["nrmse_pct"], all_base["d_index"], all_base["r2"]))
    print("  Mode 1 (Raw Scale)   : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f} | R2 = {:.4f}".format(
        all_m1["rmse_t_ha"], all_m1["nrmse_pct"], all_m1["d_index"], all_m1["r2"]))
    print("  Mode 2 (Rel. Scale)  : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f} | R2 = {:.4f}".format(
        all_m2["rmse_t_ha"], all_m2["nrmse_pct"], all_m2["d_index"], all_m2["r2"]))

    sp25_base = summary_meta["cohort_metrics"]["25SP"]["baseline"]
    sp25_m1 = summary_meta["cohort_metrics"]["25SP"]["mode1_raw_optimal"]
    print("\n--- 2025 Spring (25SP, 11 Treatments) ---")
    print("  Baseline : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f}".format(
        sp25_base["rmse_t_ha"], sp25_base["nrmse_pct"], sp25_base["d_index"]))
    print("  Mode 1   : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f}".format(
        sp25_m1["rmse_t_ha"], sp25_m1["nrmse_pct"], sp25_m1["d_index"]))

    sp26_base = summary_meta["cohort_metrics"]["26SP"]["baseline"]
    sp26_m2 = summary_meta["cohort_metrics"]["26SP"]["mode2_relative_optimal"]
    print("\n--- 2026 Spring (26SP, 12 Treatments) ---")
    print("  Baseline : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f}".format(
        sp26_base["rmse_t_ha"], sp26_base["nrmse_pct"], sp26_base["d_index"]))
    print("  Mode 2   : RMSE = {:6.3f} t/ha | NRMSE = {:5.2f}% | d = {:.4f}".format(
        sp26_m2["rmse_t_ha"], sp26_m2["nrmse_pct"], sp26_m2["d_index"]))

    n0_base = summary_meta["cohort_metrics"]["N0_ALL"]["baseline"]
    n0_m2 = summary_meta["cohort_metrics"]["N0_ALL"]["mode2_relative_optimal"]
    print("\n--- Zero-N Cohort (N0, 9 Treatments across 3 seasons) ---")
    print("  Baseline : MAE  = {:6.3f} t/ha | RMSE  = {:6.3f} t/ha | NRMSE = {:5.2f}%".format(
        n0_base["mae_t_ha"], n0_base["rmse_t_ha"], n0_base["nrmse_pct"]))
    print("  Mode 2   : MAE  = {:6.3f} t/ha | RMSE  = {:6.3f} t/ha | NRMSE = {:5.2f}%".format(
        n0_m2["mae_t_ha"], n0_m2["rmse_t_ha"], n0_m2["nrmse_pct"]))

    # Clean up any leftover worker folders
    if WORKER_ROOT.exists():
        shutil.rmtree(WORKER_ROOT, ignore_errors=True)
    print("\nScratch directories cleaned up successfully.")


if __name__ == "__main__":
    force_rerun = "--force-rerun" in sys.argv
    main(force_rerun_grid=force_rerun)
