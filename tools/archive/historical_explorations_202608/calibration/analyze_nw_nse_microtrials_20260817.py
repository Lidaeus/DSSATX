"""Audit the completed A/B/C/D N/W response-NSE micro-trials."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace/reports/nw_nse_microtrials_20260817"
CASES = {
    "A": "e02_nw_nse_micro_A_baseline_static_80x4_20260817",
    "B": "e02_nw_nse_micro_B_n_response_nse_80x4_20260817",
    "C": "e02_nw_nse_micro_C_w_response_nse_80x4_20260817",
    "D": "e02_nw_nse_micro_D_nw_response_nse_80x4_20260817",
}
NSE_LAMBDAS = {
    "A": {},
    "B": {"N_RESPONSE": 1.5},
    "C": {"W_RESPONSE": 0.75},
    "D": {"N_RESPONSE": 1.5, "W_RESPONSE": 0.75},
}
TOKENS = {
    "DRY_CUMULATIVE": {"CHPDTS_T", "CHPDTS"},
    "N_RESPONSE": {"NRESPS"},
    "W_RESPONSE": {"WRESPS"},
}


def nse(obs: np.ndarray, sim: np.ndarray) -> float:
    valid = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[valid], sim[valid]
    if len(obs) < 2:
        return math.nan
    sst = float(np.square(obs - obs.mean()).sum())
    return 1.0 - float(np.square(sim - obs).sum()) / sst if sst > 0 else math.nan


def metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float | int]:
    valid = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[valid], sim[valid]
    residual = sim - obs
    return {
        "n": int(len(obs)),
        "nse": nse(obs, sim),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "bias": float(np.mean(residual)),
        "pbias_pct": float(100.0 * residual.sum() / obs.sum()) if obs.sum() else math.nan,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    run_rows: list[dict] = []
    member_rows: list[dict] = []
    metric_rows: list[dict] = []
    selected_rows: list[dict] = []
    boundary_rows: list[dict] = []
    identity_rows: list[dict] = []
    design_rows: list[dict] = []
    convergence_rows: list[dict] = []

    for arm, case in CASES.items():
        run_dir = ROOT / "workspace/runs" / case
        status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        quality = json.loads((run_dir / "ies_quality/ies_run_quality.json").read_text(encoding="utf-8"))
        design = json.loads((run_dir / "joint_design.json").read_text(encoding="utf-8"))
        contract = json.loads((run_dir / "nw_nse_microtrial_contract.json").read_text(encoding="utf-8"))
        pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
        phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
        final_iteration = int(phi["iteration"].max())
        final_phi = phi.loc[phi["iteration"].eq(final_iteration)].iloc[0]
        obs_ens = pd.read_csv(run_dir / f"{case}.{final_iteration}.obs.csv", index_col=0)
        par_ens = pd.read_csv(run_dir / f"{case}.{final_iteration}.par.csv", index_col=0)
        obs_ens.index, par_ens.index = obs_ens.index.map(str), par_ens.index.map(str)
        obs_ens.columns, par_ens.columns = obs_ens.columns.str.lower(), par_ens.columns.str.lower()
        registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
        registry["obsnme_l"] = registry["obsnme"].astype(str).str.lower()
        pst_obs = pst.observation_data.copy()
        pst_obs.index = pst_obs.index.astype(str).str.lower()

        member_phi = {
            str(col): float(final_phi[col])
            for col in phi.columns
            if col not in {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
        }
        for _, row in phi.iterrows():
            convergence_rows.append({
                "arm": arm, "iteration": int(row["iteration"]),
                "phi_mean": float(row["mean"]), "phi_min": float(row["min"]),
                "phi_sd": float(row["standard_deviation"]), "total_runs": int(row["total_runs"]),
            })

        per_arm: list[dict] = []
        for real in obs_ens.index:
            summary = {"arm": arm, "realization": real, "total_phi": member_phi[real]}
            response_nses: list[float] = []
            for family, tokens in TOKENS.items():
                rows = registry[registry["sim_token"].astype(str).isin(tokens)].copy()
                for season, part in rows.groupby("season_id", sort=True):
                    names = part["obsnme_l"].tolist()
                    obs = pd.to_numeric(part["raw_obsval"], errors="raise").to_numpy(float)
                    sim = pd.to_numeric(obs_ens.loc[real, names], errors="coerce").to_numpy(float)
                    value = metrics(obs, sim)
                    metric_rows.append({"arm": arm, "realization": real, "family": family, "season": season, **value})
                    key = f"{family.lower()}_{str(season).lower()}"
                    summary[f"{key}_nse"] = value["nse"]
                    summary[f"{key}_rmse"] = value["rmse"]
                    summary[f"{key}_bias"] = value["bias"]
                    summary[f"{key}_pbias_pct"] = value["pbias_pct"]
                    if family in {"N_RESPONSE", "W_RESPONSE"}:
                        response_nses.append(float(value["nse"]))

                    if family in NSE_LAMBDAS[arm]:
                        weights = pd.to_numeric(pst_obs.loc[names, "weight"], errors="raise").to_numpy(float)
                        phi_direct = float(np.square((sim - obs) * weights).sum())
                        lam = NSE_LAMBDAS[arm][family]
                        identity_rows.append({
                            "arm": arm, "realization": real, "family": family, "season": season,
                            "lambda": lam, "phi_direct": phi_direct,
                            "lambda_times_one_minus_nse": lam * (1.0 - float(value["nse"])),
                            "identity_delta": phi_direct - lam * (1.0 - float(value["nse"])),
                        })
            summary["response_nse_mean4"] = float(np.mean(response_nses))
            member_rows.append(summary)
            per_arm.append(summary)

        members = pd.DataFrame(per_arm)
        phi_q10 = float(members["total_phi"].quantile(0.10))
        selections = {
            "anchor_member126_row0": "0",
            "best_phi": str(members.sort_values(["total_phi", "realization"]).iloc[0]["realization"]),
            "best_response_within_phi_q10": str(
                members[members["total_phi"] <= phi_q10]
                .sort_values(["response_nse_mean4", "total_phi"], ascending=[False, True]).iloc[0]["realization"]
            ),
        }
        for selection, real in selections.items():
            row = members.loc[members["realization"].eq(real)].iloc[0].to_dict()
            selected_rows.append({"selection": selection, **row})

        par = pst.parameter_data.copy()
        par.index = par.index.astype(str).str.lower()
        active = par.index[~par["partrans"].astype(str).str.lower().eq("fixed")]
        for name in active:
            lo, hi = float(par.loc[name, "parlbnd"]), float(par.loc[name, "parubnd"])
            values = pd.to_numeric(par_ens[name], errors="coerce")
            lower_dist, upper_dist = (values - lo) / (hi - lo), (hi - values) / (hi - lo)
            boundary_rows.append({
                "arm": arm, "parameter": name, "lower": lo, "upper": hi,
                "median": float(values.median()), "q05": float(values.quantile(.05)), "q95": float(values.quantile(.95)),
                "share_within_1pct_any": float(((lower_dist <= .01) | (upper_dist <= .01)).mean()),
                "share_within_5pct_any": float(((lower_dist <= .05) | (upper_dist <= .05)).mean()),
            })

        reg_weights = registry.set_index("obsnme_l")["weight"]
        active_names = pst_obs.index[pd.to_numeric(pst_obs["weight"], errors="coerce") > 0]
        mismatch = sum(
            not np.isclose(float(pst_obs.loc[name, "weight"]), float(reg_weights.loc[name]), rtol=1e-9, atol=1e-12)
            for name in active_names if name in reg_weights.index
        )
        design_rows.append({
            "arm": arm, "anchor_source_member": contract.get("anchor_member"),
            "n_reals_contract": 80, "noptmax_contract": 4,
            "pst_noptmax": int(pst.control_data.noptmax), "final_iteration": final_iteration,
            "pst_parameter_ensemble": pst.pestpp_options.get("ies_parameter_ensemble"),
            "pst_observation_ensemble": pst.pestpp_options.get("ies_observation_ensemble"),
            "registry_weight_mismatch_count": int(mismatch),
            "n_response_weighting": design["nitrogen_response_objective"].get("weighting", "static"),
            "n_response_lambda": design["nitrogen_response_objective"].get("nse_lambda"),
            "w_response_weighting": design["water_response_objective"].get("weighting", "static"),
            "w_response_lambda": design["water_response_objective"].get("nse_lambda"),
        })
        run_rows.append({
            "arm": arm, "case": case, "status": status["status"],
            "engineering_status": status["engineering_status"], "quality_status": quality["status"],
            "final_iteration": final_iteration, "members": len(obs_ens),
            "nonfinite_obs_cells": int((~np.isfinite(obs_ens.to_numpy(float))).sum()),
            "final_phi_mean": float(final_phi["mean"]), "final_phi_min": float(final_phi["min"]),
            "phi_mean_change_last_iteration_pct": float(100 * (phi.iloc[-2]["mean"] - phi.iloc[-1]["mean"]) / phi.iloc[-2]["mean"]),
        })

    outputs = {
        "run_summary.csv": pd.DataFrame(run_rows),
        "design_audit.csv": pd.DataFrame(design_rows),
        "convergence.csv": pd.DataFrame(convergence_rows),
        "member_metrics.csv": pd.DataFrame(member_rows),
        "metric_long.csv": pd.DataFrame(metric_rows),
        "selected_candidates.csv": pd.DataFrame(selected_rows),
        "boundary_pressure.csv": pd.DataFrame(boundary_rows),
        "nse_phi_identity.csv": pd.DataFrame(identity_rows),
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    identity = outputs["nse_phi_identity.csv"]
    summary = {
        "all_runs_engineering_validated": bool(outputs["run_summary.csv"]["engineering_status"].eq("engineering_validated").all()),
        "all_final_iteration_4": bool(outputs["run_summary.csv"]["final_iteration"].eq(4).all()),
        "all_have_80_members": bool(outputs["run_summary.csv"]["members"].eq(80).all()),
        "max_abs_nse_phi_identity_delta": float(identity["identity_delta"].abs().max()),
        "registry_metadata_mismatch_present": bool((outputs["design_audit.csv"]["registry_weight_mismatch_count"] > 0).any()),
    }
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(outputs["run_summary.csv"].to_string(index=False))
    print("\nSelected candidates:\n", outputs["selected_candidates.csv"].to_string(index=False))
    print("\nDesign audit:\n", outputs["design_audit.csv"].to_string(index=False))
    print("\nSummary:\n", json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
