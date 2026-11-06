"""Audit the formal corrected-bundle calibration and deterministic best member."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_selected8_water_formal_measuredmoisture_official_200x6_20260819"
RUN = ROOT / "workspace/runs" / CASE
DET = RUN / "deterministic_candidates/best_phi_member42_two_season_20260819"
OUT = ROOT / "figture/e02_selected8_water_formal_best42_two_season_full_20260819"
BEST = "42"
SELECTED = {"25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]}
CONTRASTS = {
    "25SP": {"N_RESPONSE": [(2, 5), (10, 13)], "W_RESPONSE": [(2, 10), (5, 13)]},
    "26SP": {"N_RESPONSE": [(2, 11), (3, 12)], "W_RESPONSE": [(2, 3), (11, 12)]},
}
STRATA = {
    "25SP": {"N_RESPONSE": ["W3", "W1"], "W_RESPONSE": ["N3", "N0"]},
    "26SP": {"N_RESPONSE": ["W2", "W1"], "W_RESPONSE": ["N3", "N0"]},
}


def metrics(observed: np.ndarray, simulated: np.ndarray) -> dict[str, float | int]:
    error = simulated - observed
    sst = float(np.square(observed - observed.mean()).sum())
    dden = float(np.square(np.abs(simulated - observed.mean()) + np.abs(observed - observed.mean())).sum())
    return {
        "n": int(len(observed)),
        "rmse": float(np.sqrt(np.square(error).mean())),
        "rrmse_pct": float(100 * np.sqrt(np.square(error).mean()) / np.abs(observed).mean()),
        "mae": float(np.abs(error).mean()),
        "bias": float(error.mean()),
        "nse": float(1 - np.square(error).sum() / sst) if sst else np.nan,
        "d_index": float(1 - np.square(error).sum() / dden) if dden else np.nan,
        "r2": float(np.corrcoef(observed, simulated)[0, 1] ** 2)
        if len(observed) > 1 and observed.std() and simulated.std() else np.nan,
    }


def deterministic_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    fit_rows: list[dict] = []
    response_rows: list[dict] = []
    for season, treatments in SELECTED.items():
        harvest = pd.read_csv(DET / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv")
        harvest = harvest.loc[harvest["TN"].astype(int).isin(treatments)].copy()
        fit_rows.append({
            "season": season, "scope": "calibration_treatments", "variable": "DRY_CUM",
            **metrics(harvest["OBS_DRY_CUM"].to_numpy(float), harvest["SIM_DRY_CUM"].to_numpy(float)),
        })
        process = pd.read_csv(DET / "_seasons" / season / f"{season}_deterministic_process_compare.csv")
        process = process.loc[process["TN"].astype(int).isin(treatments)].copy()
        for variable in ("LAID", "LWAD", "SWAD", "CHTD"):
            observed = pd.to_numeric(process[f"OBS_{variable}"], errors="coerce")
            simulated = pd.to_numeric(process[f"SIM_{variable}"], errors="coerce")
            valid = observed.notna() & simulated.notna() & observed.ne(-99) & simulated.ne(-99)
            fit_rows.append({
                "season": season, "scope": "calibration_treatments", "variable": variable,
                **metrics(observed.loc[valid].to_numpy(float), simulated.loc[valid].to_numpy(float)),
            })

        indexed = harvest.set_index(["TN", "HNO", "DATE"])
        for family, pairs in CONTRASTS[season].items():
            observed_values: list[float] = []
            simulated_values: list[float] = []
            for stratum, (high, low) in zip(STRATA[season][family], pairs):
                high_rows = indexed.loc[high].reset_index().set_index(["HNO", "DATE"])
                low_rows = indexed.loc[low].reset_index().set_index(["HNO", "DATE"])
                joined = high_rows[["OBS_DRY_CUM", "SIM_DRY_CUM"]].join(
                    low_rows[["OBS_DRY_CUM", "SIM_DRY_CUM"]],
                    lsuffix="_high", rsuffix="_low", how="inner", validate="one_to_one",
                )
                observed_stratum = (joined["OBS_DRY_CUM_high"] - joined["OBS_DRY_CUM_low"]).to_numpy(float)
                simulated_stratum = (joined["SIM_DRY_CUM_high"] - joined["SIM_DRY_CUM_low"]).to_numpy(float)
                observed_values.extend(observed_stratum.tolist())
                simulated_values.extend(simulated_stratum.tolist())
                response_rows.append({
                    "season": season, "family": family, "stratum": stratum,
                    **metrics(observed_stratum, simulated_stratum),
                })
            response_rows.append({
                "season": season, "family": family, "stratum": "combined_raw",
                **metrics(np.asarray(observed_values, float), np.asarray(simulated_values, float)),
            })
    return pd.DataFrame(fit_rows), pd.DataFrame(response_rows)


def phi_decomposition() -> tuple[pd.DataFrame, float]:
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv", encoding="utf-8-sig")
    registry["obsnme"] = registry["obsnme"].astype(str).str.lower()
    obs = pd.read_csv(RUN / f"{CASE}.6.obs.csv")
    real_col = obs.columns[0]
    row = obs.loc[obs[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST)].iloc[0]
    records = []
    for item in registry.itertuples(index=False):
        name = str(item.obsnme)
        weight = float(item.weight)
        if weight <= 0 or name not in row.index:
            continue
        token = str(item.sim_token).upper()
        if token in {"CHPDTS", "CHPDTS_T"}:
            family = "DRY_CUM_NSE"
        elif "WRESP" in token:
            family = "W_RESPONSE"
        elif "NRESP" in token:
            family = "N_RESPONSE"
        elif token.startswith("SW") and token[2:6].isdigit():
            family = "SOIL_WATER"
        elif token.startswith(("LAI", "LW", "SW", "CHTD")):
            family = "PROCESS_STATE"
        elif token.startswith(("PDAP", "ADAP", "MDAP")):
            family = "PHENOLOGY"
        elif token.startswith(("CHFPW", "HPODW")):
            family = "HARVEST_OTHER"
        else:
            family = "OTHER"
        records.append({
            "season": str(item.season_id), "family": family,
            "phi": ((float(row[name]) - float(item.obsval)) * weight) ** 2,
        })
    result = pd.DataFrame(records).groupby(["season", "family"], as_index=False)["phi"].sum()
    return result, float(result["phi"].sum())


def boundary_pressure() -> pd.DataFrame:
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    active = pst.parameter_data.loc[~pst.parameter_data.partrans.astype(str).str.lower().eq("fixed")]
    ensemble = pd.read_csv(RUN / f"{CASE}.6.par.csv")
    real_col = ensemble.columns[0]
    best = ensemble.loc[
        ensemble[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST)
    ].iloc[0]
    rows = []
    for name, spec in active.iterrows():
        values = pd.to_numeric(ensemble[name], errors="raise").to_numpy(float)
        lower, upper = float(spec.parlbnd), float(spec.parubnd)
        span = upper - lower
        lower_fraction = float(np.mean((values - lower) / span <= 0.01))
        upper_fraction = float(np.mean((upper - values) / span <= 0.01))
        relative = float((float(best[name]) - lower) / span)
        rows.append({
            "parameter": name, "lower": lower, "upper": upper,
            "best_value": float(best[name]), "best_relative_position": relative,
            "ensemble_fraction_near_lower_1pct": lower_fraction,
            "ensemble_fraction_near_upper_1pct": upper_fraction,
            "best_near_boundary": relative <= 0.01 or relative >= 0.99,
            "ensemble_pressure": "lower" if lower_fraction >= 0.10 else "upper" if upper_fraction >= 0.10 else "none",
        })
    return pd.DataFrame(rows)


def main() -> int:
    fit, response = deterministic_metrics()
    phi_groups, reconstructed_phi = phi_decomposition()
    boundary = boundary_pressure()
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv")
    members = [column for column in phi if str(column).isdigit()]
    progress = pd.DataFrame({
        "iteration": phi["iteration"].astype(int),
        "mean_phi": phi["mean"].astype(float),
        "median_phi": [pd.to_numeric(row[members]).median() for _, row in phi.iterrows()],
        "min_phi": [pd.to_numeric(row[members]).min() for _, row in phi.iterrows()],
        "min_phi_member": [pd.to_numeric(row[members]).idxmin() for _, row in phi.iterrows()],
    })
    fit.to_csv(OUT / "calibration_treatment_metrics.csv", index=False)
    response.to_csv(OUT / "calibration_response_metrics.csv", index=False)
    phi_groups.to_csv(OUT / "best42_phi_decomposition.csv", index=False)
    boundary.to_csv(OUT / "final_parameter_boundary_pressure.csv", index=False)
    progress.to_csv(OUT / "phi_progress.csv", index=False)
    quality = json.loads((RUN / "ies_quality/ies_run_quality.json").read_text(encoding="utf-8"))
    summary = {
        "case": CASE,
        "best_member": BEST,
        "reported_final_phi": float(progress.iloc[-1].min_phi),
        "reconstructed_final_phi": reconstructed_phi,
        "initial_mean_phi": float(progress.iloc[0].mean_phi),
        "final_mean_phi": float(progress.iloc[-1].mean_phi),
        "mean_phi_reduction_pct": float(100 * (1 - progress.iloc[-1].mean_phi / progress.iloc[0].mean_phi)),
        "initial_min_phi": float(progress.iloc[0].min_phi),
        "final_min_phi": float(progress.iloc[-1].min_phi),
        "best_phi_reduction_pct": float(100 * (1 - progress.iloc[-1].min_phi / progress.iloc[0].min_phi)),
        "engineering_quality": quality["status"],
        "science_validated": quality["science_validated"],
        "retained_numeric_members": len(members),
        "best_parameters_near_boundary": boundary.loc[boundary.best_near_boundary, "parameter"].tolist(),
        "parameters_with_ensemble_boundary_pressure": boundary.loc[
            boundary.ensemble_pressure.ne("none"), "parameter"
        ].tolist(),
    }
    (OUT / "calibration_analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nCalibration-treatment metrics:\n" + fit.to_string(index=False))
    print("\nResponse metrics:\n" + response.to_string(index=False))
    print("\nPhi decomposition:\n" + phi_groups.to_string(index=False))
    print("\nBoundary pressure:\n" + boundary.loc[
        boundary.best_near_boundary | boundary.ensemble_pressure.ne("none")
    ].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
