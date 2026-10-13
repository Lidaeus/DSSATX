#!/usr/bin/env python3
"""Run Comprehensive 3-Way Cross-Season Comparison:
1. Official Baseline (Vanilla DSSAT + best_calibration_parameters.csv)
2. Custom Stage R4 (CNC DSSAT + stage_r4_best_parameters.csv)
3. Custom Stage R4 Enhanced (CNC DSSAT + stage_r4_enhanced_parameters.csv)

Evaluates all 3 configurations across 26SP (Calibration), 25SP (Validation), and 25FA (Validation+Diagnostic).
Strictly isolated in subprojects/critical_n/.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.scripts.build_and_verify_dssat import check_production_safety
from subprojects.critical_n.scripts.cross_season_evaluator import (
    BIN_CNC,
    BIN_VANILLA,
    compute_metrics,
    run_full_cross_season_evaluation,
)


def parse_whitespace_line(line: str) -> list[str]:
    return line.strip().split()


def parse_dssat_out_file(file_path: Path) -> dict[int, list[dict[str, str]]]:
    """Parses multi-treatment DSSAT output file into {trt_no: [records]}."""
    if not file_path.exists():
        return {}

    lines = file_path.read_text(encoding="latin-1", errors="ignore").splitlines()
    data_by_trt: dict[int, list[dict[str, str]]] = {}
    current_trt = None
    headers: list[str] = []

    for line in lines:
        sline = line.strip()
        if not sline:
            continue
        if sline.startswith("*RUN"):
            parts = sline.split()
            try:
                current_trt = int(parts[1])
                data_by_trt[current_trt] = []
            except (ValueError, IndexError):
                current_trt = None
            headers = []
            continue
        if sline.startswith("@"):
            headers = [h.strip() for h in sline[1:].split()]
            continue
        if sline.startswith("*") or sline.startswith("!"):
            continue
        if current_trt is not None and headers:
            values = sline.split()
            if len(values) >= len(headers):
                rec = {headers[i]: values[i] for i in range(len(headers))}
                data_by_trt[current_trt].append(rec)
            elif len(values) > 0:
                rec = {headers[i]: values[i] for i in range(len(values))}
                data_by_trt[current_trt].append(rec)

    return data_by_trt


def audit_mass_balance(sandbox_dir: Path, season_id: str, config_id: str) -> list[dict[str, Any]]:
    """Audits PlantNBal.OUT and SoilNiBal.OUT for mass conservation."""
    records = []
    pnb_file = sandbox_dir / "PlantNBal.OUT"
    snb_file = sandbox_dir / "SoilNiBal.OUT"

    # Plant N balance
    if pnb_file.exists():
        lines = pnb_file.read_text(encoding="latin-1", errors="ignore").splitlines()
        curr_run = None
        curr_out = None
        for line in lines:
            if line.startswith("*RUN"):
                parts = line.split()
                try:
                    curr_run = int(parts[1])
                except (ValueError, IndexError):
                    pass
                curr_out = None
            elif "TOTAL N" in line and curr_run is not None:
                parts = line.split()
                try:
                    val = float(parts[-1])
                    if curr_out is None:
                        curr_out = val
                    else:
                        curr_in = val
                        delta = abs(curr_in - curr_out)
                        rel_err = (100.0 * delta / curr_in) if curr_in > 0 else 0.0
                        records.append({
                            "config_id": config_id,
                            "season_id": season_id,
                            "treatment": curr_run,
                            "balance_type": "PlantNBal",
                            "n_input_kgha": curr_in,
                            "n_output_kgha": curr_out,
                            "residual_kgha": delta,
                            "relative_error_pct": rel_err,
                            "status": "PASS" if delta < 0.25 else "FAIL",
                        })
                except (ValueError, IndexError):
                    pass

    # Soil N balance
    if snb_file.exists():
        lines = snb_file.read_text(encoding="latin-1", errors="ignore").splitlines()
        curr_run = None
        for line in lines:
            if line.startswith("*RUN"):
                parts = line.split()
                try:
                    curr_run = int(parts[1])
                except (ValueError, IndexError):
                    pass
            elif curr_run is not None and ("Balance" in line or "BAL" in line.upper()) and not line.startswith("@"):
                vals = line.split()
                if len(vals) >= 4:
                    try:
                        diff = float(vals[-1])
                        records.append({
                            "config_id": config_id,
                            "season_id": season_id,
                            "treatment": curr_run,
                            "balance_type": "SoilNiBal",
                            "n_input_kgha": float(vals[-3]) if len(vals) >= 3 else 0.0,
                            "n_output_kgha": float(vals[-2]) if len(vals) >= 2 else 0.0,
                            "residual_kgha": diff,
                            "relative_error_pct": 0.0,
                            "status": "PASS" if abs(diff) < 0.05 else "FAIL",
                        })
                    except ValueError:
                        pass
    return records


def main():
    print("=" * 85)
    print("3-WAY CROSS-SEASON EVALUATION: OFFICIAL vs STAGE R4 vs STAGE R4 ENHANCED")
    print("=" * 85)
    check_production_safety()

    comp_cat_path = PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv"
    assert comp_cat_path.exists(), f"Missing comparison catalog: {comp_cat_path}"

    official_params_path = PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/best_calibration_parameters.csv"
    r4_params_path = CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv"
    enhanced_params_path = CRITICAL_N_DIR / "reports/stage_r4_enhanced_parameters.csv"

    assert official_params_path.exists(), f"Missing official params: {official_params_path}"
    assert r4_params_path.exists(), f"Missing R4 params: {r4_params_path}"
    assert enhanced_params_path.exists(), f"Missing enhanced params: {enhanced_params_path}"

    p_off = dict(zip(pd.read_csv(official_params_path)["name"], pd.read_csv(official_params_path)["value"]))
    p_r4 = dict(zip(pd.read_csv(r4_params_path)["name"], pd.read_csv(r4_params_path)["value"]))
    p_enh = dict(zip(pd.read_csv(enhanced_params_path)["name"], pd.read_csv(enhanced_params_path)["value"]))

    eval_root = CRITICAL_N_DIR / "runs/cross_season_eval"
    reports_dir = CRITICAL_N_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    configs = [
        ("official_baseline", BIN_VANILLA, p_off, "Official Baseline (Vanilla DSSAT + best_calibration_parameters.csv)"),
        ("custom_stage_r4", BIN_CNC, p_r4, "Custom Stage R4 (CNC DSSAT + stage_r4_best_parameters.csv)"),
        ("custom_stage_r4_enhanced", BIN_CNC, p_enh, "Custom Stage R4 Enhanced (CNC DSSAT + stage_r4_enhanced_parameters.csv)"),
    ]

    metrics_list = []
    pairs_dict = {}

    for cfg_id, bin_p, p_dict, label in configs:
        print(f"\n[*] Executing {label} across 26SP, 25SP, and 25FA...")
        t0 = time.time()
        pairs_df, m_df = run_full_cross_season_evaluation(
            config_id=cfg_id,
            binary_path=bin_p,
            param_dict=p_dict,
            comparison_catalog_path=comp_cat_path,
            output_root=eval_root,
        )
        print(f"    Finished {cfg_id} in {time.time() - t0:.2f}s")
        metrics_list.append(m_df)
        pairs_dict[cfg_id] = pairs_df

    # 1. Merge metrics for 3-way side-by-side comparison
    print("\n[Step 1] Compiling 3-way side-by-side metrics table...")
    m_off = metrics_list[0].copy()
    m_r4 = metrics_list[1].copy()
    m_enh = metrics_list[2].copy()

    merged_3way = m_off.merge(
        m_r4,
        on=["season_id", "dataset_role", "variable", "unit"],
        suffixes=("_official", "_stage_r4"),
    ).merge(
        m_enh.rename(columns={c: f"{c}_enhanced" for c in m_enh.columns if c not in ["season_id", "dataset_role", "variable", "unit"]}),
        on=["season_id", "dataset_role", "variable", "unit"],
    )
    merged_3way.to_csv(reports_dir / "official_vs_stage_r4_vs_enhanced_metrics.csv", index=False)
    print(f"    Saved: {reports_dir / 'official_vs_stage_r4_vs_enhanced_metrics.csv'}")

    # 2. Extract treatment-by-treatment endpoint summaries across all 3 seasons
    print("\n[Step 2] Compiling treatment-by-treatment terminal summaries...")
    tmt_summary_rows = []
    for season_id in ["26SP", "25SP", "25FA"]:
        # Get terminal fresh & dry yield pairs
        for cfg_id in ["official_baseline", "custom_stage_r4", "custom_stage_r4_enhanced"]:
            pairs = pairs_dict[cfg_id]
            sub = pairs[pairs["season_id"] == season_id]
            # Fresh yield
            chfpw = sub[sub["variable"] == "CHFPW"].sort_values("date").groupby("trno").tail(1)
            chpdt = sub[sub["variable"] == "CHPDT"].sort_values("date").groupby("trno").tail(1)
            
            for trt in chfpw["trno"].unique():
                row_f = chfpw[chfpw["trno"] == trt].iloc[0]
                row_d = chpdt[chpdt["trno"] == trt].iloc[0] if len(chpdt[chpdt["trno"] == trt]) > 0 else {}
                
                tmt_summary_rows.append({
                    "season_id": season_id,
                    "config_id": cfg_id,
                    "treatment": trt,
                    "fresh_yield_obs_kgha": row_f["observed"],
                    "fresh_yield_sim_kgha": row_f["simulated"],
                    "fresh_yield_error_pct": 100.0 * (row_f["simulated"] - row_f["observed"]) / row_f["observed"],
                    "dry_yield_obs_kgha": row_d.get("observed", np.nan),
                    "dry_yield_sim_kgha": row_d.get("simulated", np.nan),
                    "dry_yield_error_pct": 100.0 * (row_d.get("simulated", 0) - row_d.get("observed", 1)) / max(1.0, row_d.get("observed", 1)),
                })
    tmt_df = pd.DataFrame(tmt_summary_rows)
    tmt_df.to_csv(reports_dir / "cross_season_treatment_summary.csv", index=False)
    print(f"    Saved: {reports_dir / 'cross_season_treatment_summary.csv'}")

    # 3. Mass balance audit across all seasons & configurations
    print("\n[Step 3] Running mass balance audit across all runs...")
    mb_records = []
    for cfg_id, _, _, _ in configs:
        for season_id in ["26SP", "25SP", "25FA"]:
            sb_dir = eval_root / cfg_id / season_id
            mb_records.extend(audit_mass_balance(sb_dir, season_id, cfg_id))
    mb_df = pd.DataFrame(mb_records)
    mb_df.to_csv(reports_dir / "cross_season_mass_balance_audit.csv", index=False)
    print(f"    Saved: {reports_dir / 'cross_season_mass_balance_audit.csv'} ({len(mb_df)} balance records)")

    # 4. Organ N dilution audit
    print("\n[Step 4] Running organ nitrogen dilution dynamics audit...")
    dil_records = []
    for cfg_id, _, _, _ in configs:
        for season_id in ["26SP", "25SP", "25FA"]:
            sb_dir = eval_root / cfg_id / season_id
            pn_file = sb_dir / "PlantN.OUT"
            pg_file = sb_dir / "PlantGro.OUT"
            if pn_file.exists() and pg_file.exists():
                pn = parse_dssat_out_file(pn_file)
                pg = parse_dssat_out_file(pg_file)
                for trt in sorted(pn.keys()):
                    p_recs = pn[trt]
                    g_recs = pg.get(trt, [])
                    if p_recs and g_recs:
                        # Extract first, middle, and last DAP
                        for idx_pt, pt_name in [(0, "early"), (len(p_recs)//2, "mid"), (-1, "late")]:
                            pr = p_recs[idx_pt]
                            gr = g_recs[min(idx_pt, len(g_recs)-1)]
                            dil_records.append({
                                "config_id": cfg_id,
                                "season_id": season_id,
                                "treatment": trt,
                                "phase": pt_name,
                                "dap": int(pr.get("DAP", 0)),
                                "aboveground_biomass_kgha": float(gr.get("CWAD", 0.0)),
                                "lai": float(gr.get("LAID", 0.0)),
                                "leaf_n_pct": float(pr.get("LN%D", 0.0)),
                                "stem_n_pct": float(pr.get("SN%D", 0.0)),
                                "fruit_n_pct": float(pr.get("GN%D", 0.0)),
                            })
    dil_df = pd.DataFrame(dil_records)
    dil_df.to_csv(reports_dir / "cross_season_nitrogen_dilution_audit.csv", index=False)
    print(f"    Saved: {reports_dir / 'cross_season_nitrogen_dilution_audit.csv'}")

    # 5. Extract daily trajectories for plotting & detailed reporting
    print("\n[Step 5] Compiling full daily trajectory records...")
    traj_records = []
    for cfg_id, _, _, _ in configs:
        for season_id in ["26SP", "25SP", "25FA"]:
            sb_dir = eval_root / cfg_id / season_id
            pg = parse_dssat_out_file(sb_dir / "PlantGro.OUT")
            pn = parse_dssat_out_file(sb_dir / "PlantN.OUT")
            fw = parse_dssat_out_file(sb_dir / "FreshWt.OUT")
            sw = parse_dssat_out_file(sb_dir / "SoilWat.OUT")

            for trt in sorted(pg.keys()):
                pg_recs = pg[trt]
                pn_recs = pn.get(trt, [])
                fw_recs = fw.get(trt, [])
                sw_recs = sw.get(trt, [])

                # Map by DAP
                pn_by_dap = {r.get("DAP"): r for r in pn_recs}
                fw_by_dap = {r.get("DAP"): r for r in fw_recs}
                sw_by_dap = {r.get("DAP"): r for r in sw_recs}

                for r in pg_recs:
                    dap = r.get("DAP")
                    year = r.get("YEAR")
                    doy = r.get("DOY")
                    p_row = pn_by_dap.get(dap, {})
                    f_row = fw_by_dap.get(dap, {})
                    s_row = sw_by_dap.get(dap, {})

                    traj_records.append({
                        "config_id": cfg_id,
                        "season_id": season_id,
                        "treatment": trt,
                        "year": year,
                        "doy": doy,
                        "dap": int(dap) if dap is not None else 0,
                        "lai": float(r.get("LAID", 0.0)),
                        "height_m": float(r.get("CHTD", 0.0)),
                        "lwad_kgha": float(r.get("LWAD", 0.0)),
                        "swad_kgha": float(r.get("SWAD", 0.0)),
                        "cwad_kgha": float(r.get("CWAD", 0.0)),
                        "leaf_n_pct": float(p_row.get("LN%D", 0.0)),
                        "stem_n_pct": float(p_row.get("SN%D", 0.0)),
                        "dry_fruit_yield_kgha": float(f_row.get("CHPDT", 0.0)),
                        "fresh_fruit_yield_kgha": float(f_row.get("CHFPW", 0.0)),
                        "vwc_top": float(s_row.get("SW1D", 0.0)),
                        "vwc_sub": float(s_row.get("SW2D", 0.0)),
                    })
    traj_df = pd.DataFrame(traj_records)
    traj_df.to_csv(reports_dir / "cross_season_trajectories_all.csv", index=False)
    print(f"    Saved: {reports_dir / 'cross_season_trajectories_all.csv'} ({len(traj_df)} daily trajectory records)")

    # Print summary highlights
    print("\n" + "=" * 90)
    print("KEY PERFORMANCE INDICATORS: OFFICIAL vs STAGE R4 vs ENHANCED")
    print("=" * 90)

    for season in ["26SP", "25SP", "25FA"]:
        print(f"\n--- SEASON {season} ---")
        sub = merged_3way[merged_3way["season_id"] == season]
        for v in ["CHFPW", "CHPDT", "LAID", "LWAD", "SWAD", "LEAF_N_PCT", "STEM_N_PCT", "VWC"]:
            rows = sub[sub["variable"] == v]
            for _, r in rows.iterrows():
                role = r["dataset_role"]
                n = r["n_official"]
                print(
                    f"  {v:11s} [{role:10s}|n={n:3d}] | "
                    f"Off NRMSE: {r['nrmse_official']:6.2f}% (NSE:{r['nse_official']:6.3f}, d:{r['d_official']:5.3f}) | "
                    f"R4 NRMSE: {r['nrmse_stage_r4']:6.2f}% (NSE:{r['nse_stage_r4']:6.3f}, d:{r['d_stage_r4']:5.3f}) | "
                    f"Enh NRMSE: {r['nrmse_enhanced']:6.2f}% (NSE:{r['nse_enhanced']:6.3f}, d:{r['d_enhanced']:5.3f})"
                )

    check_production_safety()
    print("\n[OK] Full 3-way evaluation complete. Production DSCSM048.EXE safety verified.")


if __name__ == "__main__":
    main()
