"""Deterministic Evaluation of Fixed Multi-Arm Best Members across All 34 Treatments.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare

OUTPUT_DIR = ROOT / "workspace/reports/fixed_multi_arm_evaluation_20260828"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR = ROOT / "figture/fixed_multi_arm_exploration_20260828"
FIG_DIR.mkdir(parents=True, exist_ok=True)

TREATMENTS = {
    "25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    "26SP": list(range(1, 13)),
    "25FA": list(range(1, 13)),
}

MEMBERS = {
    "Arm_A_Fixed (Mem #71)": {
        "run_dir": ROOT / "workspace/runs/e02_arm_a_fixed_pgeff_20260828",
        "case": "e02_arm_a",
        "member_id": "71",
        "bundles": {
            "25SP": "data/user/experiments/xxql2501_from_scratch_0_4_60cm_20260827",
            "25SP_sha": "5cc7d9cd8c04ede8d362d70796fdb97719d3cc795592df0e5bc6254f35386f1c",
            "26SP": "data/user/experiments/xxql2601_from_scratch_0_4_60cm_20260827",
            "26SP_sha": "0797c4ef972dec19a9617dc3fdfa821322149a2b70e30275831fb58005b0e860",
            "25FA": "data/user/experiments/xxfa_from_scratch_0_4_60cm_20260827",
            "25FA_sha": "fc087a9b2ca171ad764909714c2fbe53e0e313dd2ddd14e144ed533db63874fa",
        }
    },
    "Arm_B_Fixed (Mem #9)": {
        "run_dir": ROOT / "workspace/runs/e02_arm_b_clean_measuredn_fixed_pgeff_20260828",
        "case": "e02_arm_b",
        "member_id": "9",
        "bundles": {
            "25SP": "data/user/experiments/xxql2501_clean_measuredn_0_4_60cm_20260828",
            "25SP_sha": "c8054ab71316360228308186f97913faf4be030936a74bf64a7fc439d5300c27",
            "26SP": "data/user/experiments/xxql2601_clean_measuredn_0_4_60cm_20260828",
            "26SP_sha": "646dd1a2c0b0624a88ba50824b5d7e4e8f6ea76ea8b1ccf167b9151423f72290",
            "25FA": "data/user/experiments/xxfa_clean_measuredn_0_4_60cm_20260828",
            "25FA_sha": "587dfcc3484454457ae5b0680e9156337823a61f4229c6888a57e805866e069c",
        }
    }
}

def evaluate_all_arms():
    all_metrics = []
    
    for arm_label, meta in MEMBERS.items():
        print(f"\nEvaluating {arm_label} across all 34 treatments...")
        eval_run_dir = OUTPUT_DIR / f"{meta['case']}_best_{meta['member_id']}_eval"
        if eval_run_dir.exists():
            shutil.rmtree(eval_run_dir)
        eval_run_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract parameter row
        par_df = pd.read_csv(meta["run_dir"] / f"{meta['case']}.5.par.csv")
        r_col = [c for c in par_df.columns if c in ['real_name', 'realization']][0]
        best_row = par_df[par_df[r_col].astype(str) == str(meta["member_id"])].iloc[0]
        
        param_cols = [c for c in par_df.columns if c not in ['real_name', 'realization', 'iteration']]
        params_data = [{'name': p.upper(), 'value': float(best_row[p])} for p in param_cols]
        param_csv = eval_run_dir / "params.csv"
        pd.DataFrame(params_data).to_csv(param_csv, index=False)
        
        # Build evaluation design with all 3 seasons marked calibration for execution
        design_data = {
            "schema_version": 1,
            "status": "eval",
            "design_id": f"{meta['case']}_eval",
            "stage": "EVAL",
            "purpose": f"Evaluate {arm_label}",
            "cultivar_identity": "TM0008",
            "shared_parameter_scope": "full",
            "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
            "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
            "initial_condition_policy": "0-4cm and 4-60cm two-layer soil scheme",
            "seasons": [
                {
                    "season_id": "25SP",
                    "experiment_code": "XXQL2501",
                    "bundle_path": meta["bundles"]["25SP"],
                    "bundle_manifest_sha256": meta["bundles"]["25SP_sha"],
                    "role": "calibration",
                    "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
                },
                {
                    "season_id": "26SP",
                    "experiment_code": "XXQL2601",
                    "bundle_path": meta["bundles"]["26SP"],
                    "bundle_manifest_sha256": meta["bundles"]["26SP_sha"],
                    "role": "calibration",
                    "treatments": list(range(1, 13))
                },
                {
                    "season_id": "25FA",
                    "experiment_code": "XXQL2502",
                    "bundle_path": meta["bundles"]["25FA"],
                    "bundle_manifest_sha256": meta["bundles"]["25FA_sha"],
                    "role": "calibration",
                    "treatments": list(range(1, 13))
                }
            ]
        }
        design_file = eval_run_dir / "eval_design.json"
        design_file.write_text(json.dumps(design_data, indent=2), encoding="utf-8")
        
        cmd = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(design_file),
            "--param-csv", str(param_csv),
            "--prefix", f"{meta['case']}_eval",
            "--harvest-var", "CHPDT"
        ]
        completed = subprocess.run(cmd, cwd=eval_run_dir, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"deterministic DSSAT evaluation failed for {arm_label}: "
                f"{completed.stderr or completed.stdout}"
            )
        
        # Analyze process and harvest across all 3 seasons
        for sid, tns in TREATMENTS.items():
            sdir = eval_run_dir / "_seasons" / sid
            filex = next(sdir.glob("*.TMX"))
            batch = sdir / "analysis_batch.v48"
            batch.write_text("\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in tns) + "\n", encoding="utf-8")
            
            deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir))
            deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
            
            # Process metrics
            proc_file = sdir / f"{sid}_deterministic_process_compare.csv"
            if proc_file.exists() and proc_file.stat().st_size > 10:
                df_p = pd.read_csv(proc_file)
                for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
                    if f"OBS_{var}" not in df_p.columns:
                        continue
                    obs = df_p[f"OBS_{var}"].to_numpy(float)
                    sim = df_p[f"SIM_{var}"].to_numpy(float)
                    valid = np.isfinite(obs) & np.isfinite(sim) & (obs > -90) & (sim > -90)
                    if not np.any(valid):
                        continue
                    e = sim[valid] - obs[valid]
                    sst = np.sum((obs[valid] - np.mean(obs[valid]))**2)
                    nse = 1.0 - np.sum(e**2)/sst if sst > 0 else np.nan
                    d_idx = 1.0 - np.sum(e**2) / np.sum((np.abs(sim[valid] - np.mean(obs[valid])) + np.abs(obs[valid] - np.mean(obs[valid])))**2) if sst > 0 else np.nan
                    bias = np.mean(e)
                    rmse = np.sqrt(np.mean(e**2))
                    nrmse = rmse / np.mean(obs[valid]) * 100.0
                    
                    all_metrics.append({
                        "Arm": arm_label,
                        "Season": sid,
                        "Variable": var,
                        "Role": "Mixed calibration+diagnostic" if sid != "25FA" else "Validation",
                        "NSE": nse,
                        "d_index": d_idx,
                        "Bias": bias,
                        "RMSE": rmse,
                        "NRMSE_pct": nrmse
                    })
                    
            # Harvest metrics
            harv_file = sdir / f"{sid}_deterministic_harvest_compare.csv"
            if harv_file.exists() and harv_file.stat().st_size > 10:
                df_h = pd.read_csv(harv_file)
                df_term = df_h.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
                obs_y = df_term["OBS_DRY_CUM"].to_numpy(float)
                sim_y = df_term["SIM_DRY_CUM"].to_numpy(float)
                valid = np.isfinite(obs_y) & np.isfinite(sim_y) & (obs_y > -90) & (sim_y > -90)
                if np.any(valid):
                    e = sim_y[valid] - obs_y[valid]
                    sst = np.sum((obs_y[valid] - np.mean(obs_y[valid]))**2)
                    nse = 1.0 - np.sum(e**2)/sst if sst > 0 else np.nan
                    d_idx = 1.0 - np.sum(e**2) / np.sum((np.abs(sim_y[valid] - np.mean(obs_y[valid])) + np.abs(obs_y[valid] - np.mean(obs_y[valid])))**2) if sst > 0 else np.nan
                    bias = np.mean(e)
                    rmse = np.sqrt(np.mean(e**2))
                    nrmse = rmse / np.mean(obs_y[valid]) * 100.0
                    
                    all_metrics.append({
                        "Arm": arm_label,
                        "Season": sid,
                        "Variable": "CHPDT (Yield)",
                        "Role": "Mixed calibration+diagnostic" if sid != "25FA" else "Validation",
                        "NSE": nse,
                        "d_index": d_idx,
                        "Bias": bias,
                        "RMSE": rmse,
                        "NRMSE_pct": nrmse
                    })

    df_out = pd.DataFrame(all_metrics)
    csv_path = OUTPUT_DIR / "fixed_multi_arm_34treatments_metrics_comparison_20260828.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\nAll metrics successfully exported to: {csv_path}")
    print(df_out.to_string())
    
    # ── Plot Comparison Figures ───────────────────────────────────────────────
    plot_comparison(df_out)
    return df_out

def plot_comparison(df):
    plt.rcParams.update({'font.sans-serif': ['Arial', 'SimHei', 'DejaVu Sans'], 'axes.unicode_minus': False})
    
    # 1. LAI NSE Comparison across Seasons
    df_lai = df[df['Variable'] == 'LAID']
    if not df_lai.empty:
        fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
        seasons = ['25SP', '26SP', '25FA']
        arms = df_lai['Arm'].unique()
        x = np.arange(len(seasons))
        width = 0.35
        
        for i, arm in enumerate(arms):
            sub = df_lai[df_lai['Arm'] == arm]
            sub_dict = dict(zip(sub['Season'], sub['NSE']))
            vals = [sub_dict.get(s, np.nan) for s in seasons]
            ax.bar(x + (i - 0.5)*width, vals, width, label=arm, alpha=0.85)
            
        ax.set_ylabel('LAI NSE (Nash-Sutcliffe Efficiency)', fontsize=12, fontweight='bold')
        ax.set_title('LAI Simulation Accuracy across 3 Seasons (Fixed Parameter Engine)', fontsize=13, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(['25SP (4 calib + diagnostics)', '26SP (4 calib + diagnostics)', '25FA (12 validation)'], fontsize=11)
        ax.axhline(0, color='gray', linestyle='--', linewidth=0.8)
        ax.axhline(0.5, color='green', linestyle=':', linewidth=0.8, label='Target Quality Gate (NSE > 0.5)')
        ax.legend(frameon=True)
        ax.grid(True, linestyle=':', alpha=0.6)
        plt.tight_layout()
        plt.savefig(FIG_DIR / "diagnostic_fixed_multi_arm_lai_nse_comparison.png")
        plt.close()
        
    # 2. Yield (CHPDT) NSE & d-index Comparison
    df_y = df[df['Variable'] == 'CHPDT (Yield)']
    if not df_y.empty:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), dpi=300)
        seasons = ['25SP', '26SP', '25FA']
        arms = df_y['Arm'].unique()
        x = np.arange(len(seasons))
        width = 0.35
        
        for i, arm in enumerate(arms):
            sub = df_y[df_y['Arm'] == arm]
            sub_dict_nse = dict(zip(sub['Season'], sub['NSE']))
            sub_dict_d = dict(zip(sub['Season'], sub['d_index']))
            ax1.bar(x + (i - 0.5)*width, [sub_dict_nse.get(s, np.nan) for s in seasons], width, label=arm, alpha=0.85)
            ax2.bar(x + (i - 0.5)*width, [sub_dict_d.get(s, np.nan) for s in seasons], width, label=arm, alpha=0.85)
            
        ax1.set_ylabel('Yield NSE', fontsize=12, fontweight='bold')
        ax1.set_title('Cumulative Yield NSE across 3 Seasons', fontsize=12, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(['25SP (mixed)', '26SP (mixed)', '25FA (validation)'], fontsize=11)
        ax1.axhline(0, color='gray', linestyle='--', linewidth=0.8)
        ax1.legend(frameon=True)
        ax1.grid(True, linestyle=':', alpha=0.6)
        
        ax2.set_ylabel('Yield d-index (Willmott)', fontsize=12, fontweight='bold')
        ax2.set_title('Cumulative Yield Agreement Index (d-index)', fontsize=12, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels(['25SP (mixed)', '26SP (mixed)', '25FA (validation)'], fontsize=11)
        ax2.set_ylim(0, 1.0)
        ax2.legend(frameon=True)
        ax2.grid(True, linestyle=':', alpha=0.6)
        
        plt.tight_layout()
        plt.savefig(FIG_DIR / "diagnostic_fixed_multi_arm_yield_metrics_comparison.png")
        plt.close()
        print(f"Summary figures saved to: {FIG_DIR}")

if __name__ == "__main__":
    evaluate_all_arms()
