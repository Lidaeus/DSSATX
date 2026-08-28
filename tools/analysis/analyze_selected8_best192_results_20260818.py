"""Write reproducible calibration and three-season diagnostic audit tables."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_selected8_fixedsoil_nse_official_200x6_20260818"
RUN = ROOT / "workspace/runs" / CASE
DET = RUN / "deterministic_candidates/best_phi_member192_three_season_20260818"
OUT = ROOT / "figture/e02_selected8_best192_three_season_full_20260818"
BEST = "192"
SELECTED = {"25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]}
CONTRASTS = {
    "25SP": {"N": [(2, 5), (10, 13)], "W": [(2, 10), (5, 13)]},
    "26SP": {"N": [(2, 11), (3, 12)], "W": [(2, 3), (11, 12)]},
}


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float | int]:
    error = p - y
    sst = float(np.square(y - y.mean()).sum())
    dden = float(np.square(np.abs(p - y.mean()) + np.abs(y - y.mean())).sum())
    return {
        "n": int(len(y)), "rmse": float(np.sqrt(np.square(error).mean())),
        "rrmse_pct": float(100 * np.sqrt(np.square(error).mean()) / np.abs(y).mean()),
        "mae": float(np.abs(error).mean()), "bias": float(error.mean()),
        "nse": float(1 - np.square(error).sum() / sst) if sst else np.nan,
        "d_index": float(1 - np.square(error).sum() / dden) if dden else np.nan,
        "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and y.std() and p.std() else np.nan,
    }


def response_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_rows = []
    response_rows = []
    for season, treatments in SELECTED.items():
        path = DET / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv"
        frame = pd.read_csv(path)
        frame = frame[frame["TN"].astype(int).isin(treatments)].copy()
        selected_rows.append({"season": season, "scope": "calibration_treatments", **metrics(
            frame["OBS_DRY_CUM"].to_numpy(float), frame["SIM_DRY_CUM"].to_numpy(float)
        )})
        indexed = frame.set_index(["TN", "HNO", "DATE"])
        for family, pairs in CONTRASTS[season].items():
            observed: list[float] = []
            simulated: list[float] = []
            for high, low in pairs:
                high_rows = indexed.loc[high].reset_index().set_index(["HNO", "DATE"])
                low_rows = indexed.loc[low].reset_index().set_index(["HNO", "DATE"])
                joined = high_rows[["OBS_DRY_CUM", "SIM_DRY_CUM"]].join(
                    low_rows[["OBS_DRY_CUM", "SIM_DRY_CUM"]],
                    lsuffix="_high", rsuffix="_low", how="inner", validate="one_to_one",
                )
                observed.extend((joined["OBS_DRY_CUM_high"] - joined["OBS_DRY_CUM_low"]).tolist())
                simulated.extend((joined["SIM_DRY_CUM_high"] - joined["SIM_DRY_CUM_low"]).tolist())
            response_rows.append({
                "season": season, "family": f"{family}_RESPONSE",
                **metrics(np.asarray(observed, float), np.asarray(simulated, float)),
            })
    return pd.DataFrame(selected_rows), pd.DataFrame(response_rows)


def phi_audit() -> tuple[pd.DataFrame, float]:
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv", encoding="utf-8-sig")
    registry["obsnme"] = registry["obsnme"].astype(str).str.lower()
    obs = pd.read_csv(RUN / f"{CASE}.6.obs.csv")
    real_col = obs.columns[0]
    row = obs.loc[obs[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST)].iloc[0]
    records = []
    for item in registry.itertuples(index=False):
        weight = float(item.weight)
        name = str(item.obsnme)
        if weight <= 0 or name not in row.index:
            continue
        simulated = float(row[name])
        observed = float(item.obsval)
        token = str(item.sim_token).upper()
        if token in {"CHPDTS", "CHPDTS_T"}:
            family = "DRY_CUMULATIVE_NSE"
        elif "NRESP" in token:
            family = "N_RESPONSE"
        elif "WRESP" in token:
            family = "W_RESPONSE"
        elif token.startswith("SW") and token[2:6].isdigit():
            family = "SOIL_WATER"
        elif token.startswith(("LAI", "LW", "SW", "CHTD")):
            family = "PROCESS_STATE"
        else:
            family = "OTHER"
        records.append({
            "season": str(item.season_id), "family": family,
            "phi": ((simulated - observed) * weight) ** 2,
        })
    frame = pd.DataFrame(records).groupby(["season", "family"], as_index=False)["phi"].sum()
    return frame, float(frame["phi"].sum())


def boundary_audit() -> pd.DataFrame:
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    active = pst.parameter_data.loc[
        ~pst.parameter_data.partrans.astype(str).str.lower().eq("fixed")
    ]
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
        best_relative = float((float(best[name]) - lower) / span)
        rows.append({
            "parameter": name, "lower": lower, "upper": upper,
            "best_value": float(best[name]), "best_relative_position": best_relative,
            "ensemble_fraction_near_lower_1pct": lower_fraction,
            "ensemble_fraction_near_upper_1pct": upper_fraction,
            "pressure": "lower" if lower_fraction >= 0.10 else "upper" if upper_fraction >= 0.10 else "none",
        })
    return pd.DataFrame(rows).sort_values(
        ["pressure", "ensemble_fraction_near_lower_1pct", "ensemble_fraction_near_upper_1pct"],
        ascending=[True, False, False],
    )


def main() -> int:
    selected, response = response_metrics()
    phi_groups, reconstructed_phi = phi_audit()
    boundary = boundary_audit()
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv")
    members = [column for column in phi if str(column).isdigit()]
    progress = pd.DataFrame({
        "iteration": phi["iteration"].astype(int), "mean_phi": phi["mean"].astype(float),
        "min_phi": [pd.to_numeric(row[members]).min() for _, row in phi.iterrows()],
        "min_phi_member": [pd.to_numeric(row[members]).idxmin() for _, row in phi.iterrows()],
    })
    selected.to_csv(OUT / "calibration_treatment_dry_cum_metrics.csv", index=False)
    response.to_csv(OUT / "calibration_response_metrics.csv", index=False)
    phi_groups.to_csv(OUT / "best192_phi_decomposition.csv", index=False)
    boundary.to_csv(OUT / "final_parameter_boundary_pressure.csv", index=False)
    progress.to_csv(OUT / "phi_progress.csv", index=False)
    status = json.loads((RUN / "run_status.json").read_text(encoding="utf-8"))
    quality = json.loads((RUN / "ies_quality/ies_run_quality.json").read_text(encoding="utf-8"))
    summary = {
        "case": CASE, "best_member": BEST, "best_phi_reported": 507.504,
        "best_phi_reconstructed_from_final_obs": reconstructed_phi,
        "initial_mean_phi": float(progress.iloc[0].mean_phi),
        "final_mean_phi": float(progress.iloc[-1].mean_phi),
        "final_min_phi": float(progress.iloc[-1].min_phi),
        "retained_members": 200, "manager_status": status["status"],
        "engineering_quality": quality["status"], "science_validated": quality["science_validated"],
        "parameters_with_ensemble_boundary_pressure": boundary.loc[boundary.pressure.ne("none"), "parameter"].tolist(),
    }
    (OUT / "calibration_result_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nSelected-treatment cumulative dry metrics:\n", selected.to_string(index=False))
    print("\nResponse metrics:\n", response.to_string(index=False))
    print("\nBoundary pressure:\n", boundary[boundary.pressure.ne("none")].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
