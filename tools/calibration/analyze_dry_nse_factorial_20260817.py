"""Independently audit the completed 20260815 dry-NSE 2x2 factorial runs."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace" / "reports" / "dry_nse_factorial_20260817"
ARMS = {
    "r0": (False, False),
    "nse": (True, False),
    "bnd": (False, True),
    "nse_bnd": (True, True),
}


def _case(arm: str) -> str:
    return f"e02_fs2x2_{arm}_120x4_20260815"


def _family(token: str) -> str:
    token = str(token).upper()
    if token in {"CHPDTS_T", "CHPDTS"}:
        return "DRY_CUMULATIVE"
    if token == "HPODWS":
        return "FRESH_INCREMENT"
    if token == "LAIETS":
        return "CANOPY_TERMINAL"
    if token == "LAIDDS":
        return "PROCESS_LAI_CHANGE"
    if token in {"LWADDS", "SWADDS", "LWETS", "SWETS"}:
        return "PROCESS_BIOMASS"
    if token == "NRESPS":
        return "N_RESPONSE"
    if token == "WRESPS":
        return "W_RESPONSE"
    if token.startswith("SW0"):
        return "SOIL_WATER"
    return "OTHER"


def _nse(obs: np.ndarray, sim: np.ndarray) -> float:
    valid = np.isfinite(obs) & np.isfinite(sim)
    obs = obs[valid]
    sim = sim[valid]
    if len(obs) < 2:
        return math.nan
    sst = float(np.square(obs - obs.mean()).sum())
    return 1.0 - float(np.square(sim - obs).sum()) / sst if sst > 0 else math.nan


def _rmse(obs: np.ndarray, sim: np.ndarray) -> float:
    valid = np.isfinite(obs) & np.isfinite(sim)
    return float(np.sqrt(np.square(sim[valid] - obs[valid]).mean())) if valid.any() else math.nan


def _inverse_sim(reg: pd.DataFrame, values: np.ndarray) -> np.ndarray:
    transform = reg["transform"].astype(str).str.lower().to_numpy()
    offset = pd.to_numeric(reg["transform_offset"], errors="coerce").fillna(0.0).to_numpy(float)
    reference = pd.to_numeric(reg["transform_reference"], errors="coerce").fillna(1.0).to_numpy(float)
    result = values.astype(float, copy=True)
    is_log = transform == "log"
    result[is_log] = np.exp(result[is_log]) * reference[is_log] - offset[is_log]
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    convergence_rows: list[dict] = []
    member_rows: list[dict] = []
    selected_rows: list[dict] = []
    family_rows: list[dict] = []
    boundary_rows: list[dict] = []
    run_rows: list[dict] = []
    metadata_rows: list[dict] = []

    for arm, (raw_nse_objective, released_bounds) in ARMS.items():
        case = _case(arm)
        run_dir = ROOT / "workspace" / "runs" / case
        status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        quality = json.loads((run_dir / "ies_quality" / "ies_run_quality.json").read_text(encoding="utf-8"))
        pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
        phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
        final_iteration = int(phi["iteration"].max())
        if final_iteration != int(pst.control_data.noptmax):
            raise RuntimeError(f"{case}: final iteration {final_iteration} != noptmax {pst.control_data.noptmax}")
        final_phi = phi.loc[phi["iteration"].eq(final_iteration)].iloc[0]
        for _, row in phi.iterrows():
            convergence_rows.append(
                {
                    "arm": arm,
                    "raw_nse_objective": raw_nse_objective,
                    "released_bounds": released_bounds,
                    "iteration": int(row["iteration"]),
                    "total_runs": int(row["total_runs"]),
                    "phi_mean": float(row["mean"]),
                    "phi_min": float(row["min"]),
                    "phi_sd": float(row["standard_deviation"]),
                }
            )

        obs_ens = pd.read_csv(run_dir / f"{case}.{final_iteration}.obs.csv", index_col=0)
        par_ens = pd.read_csv(run_dir / f"{case}.{final_iteration}.par.csv", index_col=0)
        obs_ens.index = obs_ens.index.map(str)
        par_ens.index = par_ens.index.map(str)
        obs_ens.columns = obs_ens.columns.str.lower()
        par_ens.columns = par_ens.columns.str.lower()
        registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
        registry["obsnme_l"] = registry["obsnme"].astype(str).str.lower()
        registry["family"] = registry["sim_token"].map(_family)
        dry = registry[registry["sim_token"].isin(["CHPDTS_T", "CHPDTS"])].copy()
        dry_names = dry["obsnme_l"].tolist()
        dry_obs = pd.to_numeric(dry["raw_obsval"], errors="raise").to_numpy(float)

        member_phi = {
            str(col): float(final_phi[col])
            for col in phi.columns
            if col not in {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
        }
        for real in obs_ens.index:
            sim_raw = _inverse_sim(dry, obs_ens.loc[real, dry_names].to_numpy(float))
            row = {
                "arm": arm,
                "raw_nse_objective": raw_nse_objective,
                "released_bounds": released_bounds,
                "realization": real,
                "total_phi": member_phi[real],
                "dry_nse_pooled": _nse(dry_obs, sim_raw),
                "dry_rmse_pooled": _rmse(dry_obs, sim_raw),
                "dry_bias_pooled": float(np.nanmean(sim_raw - dry_obs)),
                "dry_valid_n": int(np.isfinite(sim_raw).sum()),
            }
            for season in ("25SP", "26SP"):
                mask = dry["season_id"].astype(str).eq(season).to_numpy()
                row[f"dry_nse_{season.lower()}"] = _nse(dry_obs[mask], sim_raw[mask])
                row[f"dry_rmse_{season.lower()}"] = _rmse(dry_obs[mask], sim_raw[mask])
                if raw_nse_objective:
                    sst = float(np.square(dry_obs[mask] - dry_obs[mask].mean()).sum())
                    weight = float(pd.to_numeric(dry.loc[mask, "weight"], errors="raise").iloc[0])
                    phi_direct = float(np.square((sim_raw[mask] - dry_obs[mask]) * weight).sum())
                    row[f"dry_phi_{season.lower()}"] = phi_direct
                    row[f"dry_phi_identity_delta_{season.lower()}"] = phi_direct - 75.0 * (1.0 - row[f"dry_nse_{season.lower()}"])
                    if not np.isclose(weight * weight, 75.0 / sst, rtol=5e-6, atol=1e-12):
                        raise AssertionError(f"{case} {season}: NSE weight is not lambda/SST")
            member_rows.append(row)

        members = pd.DataFrame([row for row in member_rows if row["arm"] == arm])
        best_phi_real = str(members.sort_values(["total_phi", "realization"]).iloc[0]["realization"])
        best_nse_real = str(members.sort_values(["dry_nse_pooled", "total_phi"], ascending=[False, True]).iloc[0]["realization"])
        phi_cut = float(members["total_phi"].quantile(0.10))
        compromise_real = str(
            members[members["total_phi"] <= phi_cut]
            .sort_values(["dry_nse_pooled", "total_phi"], ascending=[False, True])
            .iloc[0]["realization"]
        )
        for selection, real in {"best_phi": best_phi_real, "best_dry_nse": best_nse_real, "best_nse_within_phi_q10": compromise_real}.items():
            selected = members.loc[members["realization"].eq(real)].iloc[0].to_dict()
            selected["selection"] = selection
            selected_rows.append(selected)

            active = registry[pd.to_numeric(registry["weight"], errors="coerce").fillna(0.0) > 0].copy()
            names = active["obsnme_l"].tolist()
            sim = obs_ens.loc[real, names].to_numpy(float)
            target = pd.to_numeric(active["obsval"], errors="raise").to_numpy(float)
            weights = pd.to_numeric(active["weight"], errors="raise").to_numpy(float)
            contributions = np.square((sim - target) * weights)
            active = active.assign(phi_contribution=contributions)
            for family, rows in active.groupby("family", sort=True):
                family_rows.append(
                    {
                        "arm": arm,
                        "selection": selection,
                        "realization": real,
                        "family": family,
                        "phi": float(rows["phi_contribution"].sum()),
                        "n_obs": int(len(rows)),
                    }
                )

        par = pst.parameter_data.copy()
        par.index = par.index.astype(str).str.lower()
        active_names = par.index[~par["partrans"].astype(str).str.lower().eq("fixed")]
        for name in active_names:
            lo = float(par.loc[name, "parlbnd"])
            hi = float(par.loc[name, "parubnd"])
            values = pd.to_numeric(par_ens[name], errors="coerce")
            span = hi - lo
            lower_distance = (values - lo) / span
            upper_distance = (hi - values) / span
            boundary_rows.append(
                {
                    "arm": arm,
                    "parameter": name,
                    "lower": lo,
                    "upper": hi,
                    "q05": float(values.quantile(0.05)),
                    "median": float(values.median()),
                    "q95": float(values.quantile(0.95)),
                    "share_within_1pct_lower": float((lower_distance <= 0.01).mean()),
                    "share_within_1pct_upper": float((upper_distance <= 0.01).mean()),
                    "share_within_5pct_any": float(((lower_distance <= 0.05) | (upper_distance <= 0.05)).mean()),
                }
            )

        manifest_text = (run_dir / "run_manifest.yaml").read_text(encoding="utf-8")
        stale_stage = "stage_representative_source:" in manifest_text
        stage_dir = run_dir / "calibration_finalize"
        metadata_rows.append(
            {
                "arm": arm,
                "manifest_has_stage_representative_fields": stale_stage,
                "calibration_finalize_exists": stage_dir.is_dir(),
                "manifest_mentions_iteration_5": ".5.par.csv" in manifest_text,
                "actual_final_iteration": final_iteration,
            }
        )
        arm_members = members
        iter3 = phi.loc[phi["iteration"].eq(final_iteration - 1), "mean"].iloc[0]
        iter4 = phi.loc[phi["iteration"].eq(final_iteration), "mean"].iloc[0]
        run_rows.append(
            {
                "arm": arm,
                "raw_nse_objective": raw_nse_objective,
                "released_bounds": released_bounds,
                "run_status": status["status"],
                "engineering_quality": quality["status"],
                "science_validated": quality["science_validated"],
                "final_iteration": final_iteration,
                "members": int(len(obs_ens)),
                "members_with_complete_dry": int((arm_members["dry_valid_n"] == len(dry)).sum()),
                "nonfinite_obs_cells": int((~np.isfinite(obs_ens.to_numpy(float))).sum()),
                "final_phi_mean": float(final_phi["mean"]),
                "final_phi_min": float(final_phi["min"]),
                "phi_mean_improvement_iter3_to_4": float((iter3 - iter4) / iter3),
                "dry_nse_median": float(arm_members["dry_nse_pooled"].median()),
                "dry_nse_q10": float(arm_members["dry_nse_pooled"].quantile(0.10)),
                "dry_nse_q90": float(arm_members["dry_nse_pooled"].quantile(0.90)),
                "dry_nse_best_phi": float(arm_members.loc[arm_members["realization"].eq(best_phi_real), "dry_nse_pooled"].iloc[0]),
                "best_phi_realization": best_phi_real,
                "best_dry_nse_realization": best_nse_real,
                "compromise_realization": compromise_real,
            }
        )

    convergence = pd.DataFrame(convergence_rows)
    members = pd.DataFrame(member_rows)
    selected = pd.DataFrame(selected_rows)
    families = pd.DataFrame(family_rows)
    boundaries = pd.DataFrame(boundary_rows)
    runs = pd.DataFrame(run_rows)
    metadata = pd.DataFrame(metadata_rows)

    effects = []
    by_arm = runs.set_index("arm")
    for metric in ["dry_nse_median", "dry_nse_best_phi"]:
        effects.extend(
            [
                {"metric": metric, "contrast": "objective_effect_old_bounds", "delta": by_arm.loc["nse", metric] - by_arm.loc["r0", metric]},
                {"metric": metric, "contrast": "objective_effect_released_bounds", "delta": by_arm.loc["nse_bnd", metric] - by_arm.loc["bnd", metric]},
                {"metric": metric, "contrast": "bounds_effect_old_objective", "delta": by_arm.loc["bnd", metric] - by_arm.loc["r0", metric]},
                {"metric": metric, "contrast": "bounds_effect_nse_objective", "delta": by_arm.loc["nse_bnd", metric] - by_arm.loc["nse", metric]},
            ]
        )

    best_phi = selected[selected["selection"].eq("best_phi")].set_index("arm")
    compromise = selected[
        (selected["arm"].eq("nse_bnd"))
        & (selected["selection"].eq("best_nse_within_phi_q10"))
    ].iloc[0]
    focus_bounds = boundaries[
        boundaries["arm"].eq("nse_bnd") & boundaries["parameter"].isin(["phtmax", "podur"])
    ].set_index("parameter")
    decision_summary = pd.DataFrame(
        [
            {
                "recommended_arm": "nse_bnd",
                "best_phi_realization": str(best_phi.loc["nse_bnd", "realization"]),
                "best_phi_total": float(best_phi.loc["nse_bnd", "total_phi"]),
                "best_phi_dry_nse_pooled": float(best_phi.loc["nse_bnd", "dry_nse_pooled"]),
                "best_phi_dry_nse_25sp": float(best_phi.loc["nse_bnd", "dry_nse_25sp"]),
                "best_phi_dry_nse_26sp": float(best_phi.loc["nse_bnd", "dry_nse_26sp"]),
                "best_phi_dry_rmse_pooled": float(best_phi.loc["nse_bnd", "dry_rmse_pooled"]),
                "baseline_best_phi_dry_nse_pooled": float(best_phi.loc["r0", "dry_nse_pooled"]),
                "baseline_best_phi_dry_rmse_pooled": float(best_phi.loc["r0", "dry_rmse_pooled"]),
                "compromise_realization": str(compromise["realization"]),
                "compromise_total_phi": float(compromise["total_phi"]),
                "compromise_dry_nse_pooled": float(compromise["dry_nse_pooled"]),
                "compromise_dry_nse_25sp": float(compromise["dry_nse_25sp"]),
                "compromise_dry_nse_26sp": float(compromise["dry_nse_26sp"]),
                "podur_within_1pct_lower_share": float(focus_bounds.loc["podur", "share_within_1pct_lower"]),
                "phtmax_within_5pct_any_share": float(focus_bounds.loc["phtmax", "share_within_5pct_any"]),
                "phi_mean_improvement_iter3_to_4": float(by_arm.loc["nse_bnd", "phi_mean_improvement_iter3_to_4"]),
                "all_runs_completed": bool(runs["run_status"].eq("completed").all()),
                "all_engineering_quality_pass": bool(runs["engineering_quality"].eq("pass").all()),
                "science_validated": bool(runs["science_validated"].all()),
                "manifest_metadata_contamination": bool(
                    metadata["manifest_has_stage_representative_fields"].all()
                    and metadata["manifest_mentions_iteration_5"].all()
                    and (~metadata["calibration_finalize_exists"]).all()
                ),
            }
        ]
    )
    family_best = families[families["selection"].eq("best_phi")].pivot(
        index="family", columns="arm", values="phi"
    ).reset_index()
    family_best["nse_bnd_minus_r0"] = family_best["nse_bnd"] - family_best["r0"]

    outputs = {
        "run_summary.csv": runs,
        "convergence.csv": convergence,
        "member_dry_metrics.csv": members,
        "selected_member_metrics.csv": selected,
        "selected_member_family_phi.csv": families,
        "boundary_pressure.csv": boundaries,
        "factorial_effects.csv": pd.DataFrame(effects),
        "metadata_integrity.csv": metadata,
        "decision_summary.csv": decision_summary,
        "family_best_phi_comparison.csv": family_best,
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False, encoding="utf-8-sig")

    identity_cols = [c for c in members.columns if c.startswith("dry_phi_identity_delta")]
    summary = {
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "analysis_final_iteration": 4,
        "all_runs_completed": bool(runs["run_status"].eq("completed").all()),
        "all_engineering_quality_pass": bool(runs["engineering_quality"].eq("pass").all()),
        "all_have_120_members": bool(runs["members"].eq(120).all()),
        "science_validated": bool(runs["science_validated"].all()),
        "max_abs_nse_phi_identity_delta": float(members[identity_cols].abs().max().max()),
        "manifest_metadata_contamination_all_arms": bool(
            metadata["manifest_has_stage_representative_fields"].all()
            and metadata["manifest_mentions_iteration_5"].all()
            and (~metadata["calibration_finalize_exists"]).all()
        ),
    }
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(runs.to_string(index=False))
    print("\nSelected members:\n", selected[["arm", "selection", "realization", "total_phi", "dry_nse_pooled", "dry_nse_25sp", "dry_nse_26sp"]].to_string(index=False))
    print("\nFactorial effects:\n", pd.DataFrame(effects).to_string(index=False))
    print("\nSummary:\n", json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
