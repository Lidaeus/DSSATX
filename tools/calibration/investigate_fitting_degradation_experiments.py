#!/usr/bin/env python3
"""Investigate and verify why member fitting ability appeared to degrade across iterations.

Three Quantitative Experiments:
1. Representative Member Decomposition (Iter 1 #54, Iter 3 #137, Iter 6 #1, Iter 6 #45, Iter 0 #37).
2. Ensemble Pareto Front & Carbon Allocation Trade-off Analysis (all 1,393 realizations).
3. Mechanistic Parameter Perturbation DSSAT Replay (replaying Iter 6 #45 with key parameter shifts).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v36_fresh_yield_constrained_fix1_200x6_20260829"
PREFIX = "e02_formal_v36_fresh_yield_fix1_20260829"
OUT_DIR = PROJECT_ROOT / "workspace/reports/degradation_investigation"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _metrics(observed: np.ndarray, simulated: np.ndarray) -> dict[str, float]:
    ok = np.isfinite(observed) & np.isfinite(simulated)
    observed, simulated = observed[ok], simulated[ok]
    if not len(observed):
        return {"rrmse_pct": np.nan, "pbias_pct": np.nan, "nse": np.nan}
    error = simulated - observed
    mean_abs = float(np.mean(np.abs(observed)))
    sst = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "rrmse_pct": 100.0 * float(np.sqrt(np.mean(error ** 2))) / mean_abs,
        "pbias_pct": 100.0 * float(np.sum(error)) / float(np.sum(observed)),
        "nse": 1.0 - float(np.sum(error ** 2)) / sst if sst > 0 else np.nan,
    }


def _raw_simulated(registry: pd.DataFrame, simulations: pd.Series) -> np.ndarray:
    values = np.array(
        [pd.to_numeric(simulations.get(str(name).lower()), errors="coerce") for name in registry["obsnme"]],
        dtype=float,
    )
    log_mask = registry["transform"].astype(str).str.lower().eq("log").to_numpy()
    offsets = pd.to_numeric(registry["transform_offset"], errors="coerce").fillna(0).to_numpy(float)
    values[log_mask] = np.exp(values[log_mask]) - offsets[log_mask]
    return values


def experiment_1_member_decomposition():
    print("\n" + "="*70)
    print("EXPERIMENT 1: Representative Member Decomposition & Multi-Objective Breakdown")
    print("="*70)

    registry = pd.read_csv(RUN_DIR / f"{PREFIX}_observation_registry.csv")
    registry["obgnme_upper"] = registry["obgnme"].str.upper()
    group_map = registry.drop_duplicates("obgnme_upper").set_index("obgnme_upper")

    phi_group = pd.read_csv(RUN_DIR / f"{PREFIX}.phi.group.csv")
    candidates_audit = pd.read_csv(PROJECT_ROOT / "workspace/reports/e02_formal_v36_fresh_candidate_audit.csv")

    target_members = [
        {"iter": 0, "member": "37", "label": "Iter 0 #37 (Prior)"},
        {"iter": 1, "member": "54", "label": "Iter 1 #54 (High Yield, Low LAI)"},
        {"iter": 3, "member": "137", "label": "Iter 3 #137 (Intermediate Balanced)"},
        {"iter": 6, "member": "1", "label": "Iter 6 #1 (Near-Gate Best Balanced)"},
        {"iter": 6, "member": "45", "label": "Iter 6 #45 (Global Min Phi)"},
    ]

    decomp_rows = []
    for tm in target_members:
        it, mem = tm["iter"], tm["member"]
        audit_row = candidates_audit[(candidates_audit["iteration"] == it) & (candidates_audit["member"].astype(str) == str(mem))].iloc[0]

        # Get phi groups for this member
        pg_sub = phi_group[(phi_group["iteration"] == it) & (phi_group["par_realization"].astype(str).str.replace(r"\.0$", "", regex=True) == str(mem))]
        if pg_sub.empty:
            continue
        pg_vals = pg_sub.iloc[0].drop(labels=["iteration", "total_runs", "obs_realization", "par_realization", "model_runs_completed"], errors="ignore")

        # Aggregate phi by category
        phi_fresh_term = 0.0
        phi_fresh_inc = 0.0
        phi_fresh_trend = 0.0
        phi_lai = 0.0
        phi_lwad = 0.0
        phi_swad = 0.0
        phi_soil = 0.0
        phi_nw_resp = 0.0

        for col, val in pg_vals.items():
            if not isinstance(val, (int, float, np.number)) or np.isnan(val):
                continue
            cu = str(col).upper()
            sim_token = group_map.loc[cu, "sim_token"] if cu in group_map.index else ""
            if sim_token == "CHFPWS":
                phi_fresh_term += float(val)
            elif sim_token == "HFPOWS":
                phi_fresh_inc += float(val)
            elif sim_token == "CHFPWS_T":
                phi_fresh_trend += float(val)
            elif sim_token in ["LAIDS", "LAIDDS", "LAIETS"]:
                phi_lai += float(val)
            elif sim_token in ["LWADS", "LWADDS", "LWETS"]:
                phi_lwad += float(val)
            elif sim_token in ["SWADS", "SWADDS", "SWETS"]:
                phi_swad += float(val)
            elif "SW00" in sim_token:
                phi_soil += float(val)
            elif sim_token in ["NRESPS", "WRESPS"]:
                phi_nw_resp += float(val)

        phi_vegetative = phi_lai + phi_lwad + phi_swad
        phi_fresh_total = phi_fresh_term + phi_fresh_inc + phi_fresh_trend

        decomp_rows.append({
            "Member": tm["label"],
            "Total_Phi": float(audit_row["phi"]),
            "Phi_Fresh_Yield": phi_fresh_total,
            "Phi_Vegetative": phi_vegetative,
            "Phi_LAI": phi_lai,
            "Phi_LeafMass": phi_lwad,
            "Phi_StemMass": phi_swad,
            "Phi_NW_Resp": phi_nw_resp,
            "25SP_Fresh_RRMSE": float(audit_row["25SP_terminal_rrmse_pct"]),
            "25SP_Fresh_PBIAS": float(audit_row["25SP_terminal_pbias_pct"]),
            "25SP_Fresh_NSE": float(audit_row["25SP_fresh_cumulative_nse"]),
            "25SP_LAI_NSE": float(audit_row["25SP_lai_nse"]),
            "26SP_Fresh_RRMSE": float(audit_row["26SP_terminal_rrmse_pct"]),
            "26SP_Fresh_PBIAS": float(audit_row["26SP_terminal_pbias_pct"]),
            "26SP_Fresh_NSE": float(audit_row["26SP_fresh_cumulative_nse"]),
            "26SP_LAI_NSE": float(audit_row["26SP_lai_nse"]),
        })

    df_decomp = pd.DataFrame(decomp_rows)
    df_decomp.to_csv(OUT_DIR / "exp1_member_decomposition.csv", index=False)
    print(df_decomp[["Member", "Total_Phi", "Phi_Fresh_Yield", "Phi_Vegetative", "25SP_Fresh_RRMSE", "26SP_Fresh_RRMSE", "25SP_LAI_NSE", "26SP_LAI_NSE"]].to_string(index=False))


def experiment_2_pareto_carbon_tradeoff():
    print("\n" + "="*70)
    print("EXPERIMENT 2: Pareto Front & Biomass vs Yield Trade-off Across 1,393 Realizations")
    print("="*70)

    registry = pd.read_csv(RUN_DIR / f"{PREFIX}_observation_registry.csv")
    registry["obgnme_upper"] = registry["obgnme"].str.upper()
    group_map = registry.drop_duplicates("obgnme_upper").set_index("obgnme_upper")

    phi_group = pd.read_csv(RUN_DIR / f"{PREFIX}.phi.group.csv")
    audit_df = pd.read_csv(PROJECT_ROOT / "workspace/reports/e02_formal_v36_fresh_candidate_audit.csv")

    records = []
    for _, row in phi_group.iterrows():
        it = int(row["iteration"])
        real = str(row["par_realization"]).replace(".0", "")
        pg_vals = row.drop(labels=["iteration", "total_runs", "obs_realization", "par_realization", "model_runs_completed"], errors="ignore")

        phi_veg = 0.0
        phi_fresh = 0.0
        for col, val in pg_vals.items():
            if not isinstance(val, (int, float, np.number)) or np.isnan(val):
                continue
            cu = str(col).upper()
            sim_token = group_map.loc[cu, "sim_token"] if cu in group_map.index else ""
            if sim_token in ["CHFPWS", "HFPOWS", "CHFPWS_T"]:
                phi_fresh += float(val)
            elif sim_token in ["LAIDS", "LAIDDS", "LAIETS", "LWADS", "LWADDS", "LWETS", "SWADS", "SWADDS", "SWETS"]:
                phi_veg += float(val)

        records.append({"iteration": it, "member": real, "phi_veg": phi_veg, "phi_fresh": phi_fresh})

    df_veg_fresh = pd.DataFrame(records)
    audit_df["member"] = audit_df["member"].astype(str)
    df_veg_fresh["member"] = df_veg_fresh["member"].astype(str)
    merged = pd.merge(audit_df, df_veg_fresh, on=["iteration", "member"], how="inner")
    merged.to_csv(OUT_DIR / "exp2_pareto_data.csv", index=False)

    corr_25 = merged[["25SP_lai_nse", "25SP_terminal_pbias_pct", "25SP_fresh_cumulative_nse", "25SP_terminal_rrmse_pct", "phi_veg", "phi_fresh"]].corr()
    corr_26 = merged[["26SP_lai_nse", "26SP_terminal_pbias_pct", "26SP_fresh_cumulative_nse", "26SP_terminal_rrmse_pct", "phi_veg", "phi_fresh"]].corr()
    print("Correlation matrix for 25SP (LAI vs Fresh Yield metrics):")
    print(corr_25.round(3).to_string())

    print("\nCorrelation matrix for 26SP (LAI vs Fresh Yield metrics):")
    print(corr_26.round(3).to_string())

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=180)
    
    # Left: Vegetative Phi vs Fresh Phi
    scatter = axes[0].scatter(merged["phi_veg"], merged["phi_fresh"], c=merged["iteration"], cmap="viridis", alpha=0.6, edgecolors="none")
    cbar = fig.colorbar(scatter, ax=axes[0])
    cbar.set_label("IES Iteration (0 -> 6)")
    axes[0].set_xlabel(r"Vegetative Biomass & Canopy Residual ($\Phi_{Vegetative}$)")
    axes[0].set_ylabel(r"Fresh Fruit Yield Residual ($\Phi_{Fresh}$)")
    axes[0].set_title("Pareto Space: Vegetative Fit vs Fruit Fit Across Iterations")
    axes[0].grid(True, alpha=0.3)

    highlights = [
        (0, "37", "Iter0 #37", "black"),
        (1, "54", "Iter1 #54", "red"),
        (3, "137", "Iter3 #137", "orange"),
        (6, "1", "Iter6 #1", "blue"),
        (6, "45", "Iter6 #45", "purple"),
    ]
    for it, mem, lab, col in highlights:
        sub = merged[(merged["iteration"] == it) & (merged["member"].astype(str) == str(mem))]
        if not sub.empty:
            r = sub.iloc[0]
            axes[0].scatter([r["phi_veg"]], [r["phi_fresh"]], color=col, s=80, zorder=5, edgecolors="black", linewidths=1.2)
            axes[0].annotate(lab, (r["phi_veg"], r["phi_fresh"]), textcoords="offset points", xytext=(8, 5), fontsize=8, weight="bold", color=col)

    # Right: LAI NSE vs Terminal PBIAS
    scatter2 = axes[1].scatter(merged["25SP_lai_nse"], merged["25SP_terminal_pbias_pct"], c=merged["iteration"], cmap="viridis", alpha=0.6, edgecolors="none")
    cbar2 = fig.colorbar(scatter2, ax=axes[1])
    cbar2.set_label("IES Iteration (0 -> 6)")
    axes[1].axhline(-15, color="red", linestyle="--", alpha=0.7, label="PBIAS Hard Gate (-15%)")
    axes[1].axvline(0.60, color="blue", linestyle="--", alpha=0.7, label="LAI NSE Hard Gate (0.60)")
    axes[1].set_xlabel("25SP LAI NSE")
    axes[1].set_ylabel("25SP Fresh Yield Terminal PBIAS (%)")
    axes[1].set_title("Trade-off: LAI NSE vs Fresh Yield Underestimation (PBIAS)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="lower left", fontsize=8)

    for it, mem, lab, col in highlights:
        sub = merged[(merged["iteration"] == it) & (merged["member"].astype(str) == str(mem))]
        if not sub.empty:
            r = sub.iloc[0]
            axes[1].scatter([r["25SP_lai_nse"]], [r["25SP_terminal_pbias_pct"]], color=col, s=80, zorder=5, edgecolors="black", linewidths=1.2)
            axes[1].annotate(lab, (r["25SP_lai_nse"], r["25SP_terminal_pbias_pct"]), textcoords="offset points", xytext=(8, 5), fontsize=8, weight="bold", color=col)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "exp2_pareto_tradeoff.png")
    plt.close(fig)
    print(f"Pareto analysis chart saved to {OUT_DIR / 'exp2_pareto_tradeoff.png'}")


def experiment_3_mechanistic_parameter_ablation():
    print("\n" + "="*70)
    print("EXPERIMENT 3: Mechanistic Parameter Perturbation & DSSAT Replay")
    print("="*70)

    p6_file = RUN_DIR / f"{PREFIX}.6.par.csv"
    p6_df = pd.read_csv(p6_file)
    p6_df["real_name"] = p6_df["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
    p6_df.columns = [c.lower() for c in p6_df.columns]
    base_params = p6_df.set_index("real_name").loc["45"].copy()

    variants = {
        "Base_Iter6_#45": base_params.copy(),
        "VarA_podur_9.33": base_params.copy(),
        "VarB_fl-sh_1.65": base_params.copy(),
        "VarC_slaref_255.8": base_params.copy(),
        "VarD_Combined_A+B+C": base_params.copy(),
    }
    variants["VarA_podur_9.33"]["podur"] = 9.32544
    variants["VarB_fl-sh_1.65"]["fl-sh"] = 1.64803
    variants["VarC_slaref_255.8"]["slaref"] = 255.808
    variants["VarD_Combined_A+B+C"]["podur"] = 9.32544
    variants["VarD_Combined_A+B+C"]["fl-sh"] = 1.64803
    variants["VarD_Combined_A+B+C"]["slaref"] = 255.808

    design_path = PROJECT_ROOT / "configs/runs/e02_formal_v36_fresh_yield_constrained_200x6_20260829.json"
    scratch_dir = OUT_DIR / "scratch_ablation"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    ablation_results = []
    spe_base = PROJECT_ROOT / "data/templates/genotype/TMGRO048.SPE.base"

    for var_name, p_series in variants.items():
        var_dir = scratch_dir / var_name
        var_dir.mkdir(parents=True, exist_ok=True)
        param_csv = var_dir / "parameters.csv"
        p_df = pd.DataFrame({"name": p_series.index, "value": p_series.values})
        p_df.to_csv(param_csv, index=False)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["DSSAT_SPE_BASE"] = str(spe_base.resolve())
        cmd = [
            sys.executable, str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(design_path),
            "--param-csv", str(param_csv),
            "--prefix", var_name,
            "--harvest-var", "CHFPW",
        ]
        res = subprocess.run(cmd, cwd=str(var_dir), env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Variant {var_name} failed: {res.stderr[-200:]}")
            continue

        from pyemu.pst.pst_utils import InstructionFile
        obs_registry = pd.read_csv(RUN_DIR / f"{PREFIX}_observation_registry.csv")
        sim_dict = {}
        for ins_path in RUN_DIR.glob(f"{PREFIX}_*.ins"):
            out_name = ins_path.name.replace(f"{PREFIX}_", "").replace(".ins", "")
            out_path = var_dir / out_name
            if out_path.is_file():
                try:
                    vals = InstructionFile(str(ins_path)).read_output_file(str(out_path))
                    for k, v in vals["obsval"].to_dict().items():
                        sim_dict[str(k).lower()] = float(v)
                except Exception as e:
                    print(f"Error parsing {out_name}: {e}")
        
        raw_sim = _raw_simulated(obs_registry, pd.Series(sim_dict))
        v_record = {"Variant": var_name}
        for season in ("25SP", "26SP"):
            s_mask = obs_registry["season_id"].eq(season)
            term_mask = s_mask & obs_registry["sim_token"].eq("CHFPWS") & obs_registry["rrmse_lambda"].notna()
            lai_mask = s_mask & obs_registry["sim_token"].eq("LAIDS") & pd.to_numeric(obs_registry["weight"]).gt(0)
            cum_mask = s_mask & obs_registry["sim_token"].isin(["CHFPWS_T", "CHFPWS"]) & pd.to_numeric(obs_registry["weight"]).gt(0)
            
            t_m = _metrics(pd.to_numeric(obs_registry.loc[term_mask, "raw_obsval"]).to_numpy(float), raw_sim[term_mask.to_numpy()])
            l_m = _metrics(pd.to_numeric(obs_registry.loc[lai_mask, "raw_obsval"]).to_numpy(float), raw_sim[lai_mask.to_numpy()])
            c_m = _metrics(pd.to_numeric(obs_registry.loc[cum_mask, "raw_obsval"]).to_numpy(float), raw_sim[cum_mask.to_numpy()])

            v_record[f"{season}_Fresh_RRMSE"] = t_m["rrmse_pct"]
            v_record[f"{season}_Fresh_PBIAS"] = t_m["pbias_pct"]
            v_record[f"{season}_Fresh_NSE"] = c_m["nse"]
            v_record[f"{season}_LAI_NSE"] = l_m["nse"]

        ablation_results.append(v_record)

    df_abl = pd.DataFrame(ablation_results)
    df_abl.to_csv(OUT_DIR / "exp3_ablation_results.csv", index=False)
    print("\nParameter Ablation DSSAT Simulation Results:")
    print(df_abl.to_string(index=False))


def main():
    experiment_1_member_decomposition()
    experiment_2_pareto_carbon_tradeoff()
    experiment_3_mechanistic_parameter_ablation()
    print(f"\nAll 3 investigation experiments completed! Results written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
