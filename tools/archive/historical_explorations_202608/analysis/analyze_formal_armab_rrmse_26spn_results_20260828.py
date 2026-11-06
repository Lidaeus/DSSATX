"""Summarize the corrected-26SP-N formal calibration and its all-22 replay."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_formal_armab_rrmse_26spncal_official_200x6_20260828"
CASE = "e02_formal_armab_rrmse_26spncal_200x6_20260828"
DET = RUN / "best_member_103_two_season_deterministic_20260828"
OUT = RUN / "result_summary_20260828"
CALIBRATION_TN = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}


def metrics(y: pd.Series, p: pd.Series) -> dict[str, float | int]:
    y = pd.to_numeric(y, errors="coerce")
    p = pd.to_numeric(p, errors="coerce")
    ok = y.notna() & p.notna() & (y > -90) & (p > -90)
    y = y.loc[ok].to_numpy(float)
    p = p.loc[ok].to_numpy(float)
    if not len(y):
        return {key: np.nan for key in ("n", "rmse", "rrmse_pct", "mae", "bias", "nse", "d_index", "r2")}
    error = p - y
    sst = float(np.sum((y - y.mean()) ** 2))
    dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
    return {
        "n": len(y),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "rrmse_pct": float(100 * np.sqrt(np.mean(error ** 2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
        "mae": float(np.mean(np.abs(error))),
        "bias": float(np.mean(error)),
        "nse": float(1 - np.sum(error ** 2) / sst) if sst > 0 else np.nan,
        "d_index": float(1 - np.sum(error ** 2) / dden) if dden > 0 else np.nan,
        "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
    }


def role_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    terminal_rows: list[dict] = []
    for season in ("25SP", "26SP"):
        season_dir = DET / "_seasons" / season
        sources = {
            "process": pd.read_csv(season_dir / f"{season}_deterministic_process_compare.csv"),
            "harvest": pd.read_csv(season_dir / f"{season}_deterministic_harvest_compare.csv"),
        }
        role_masks = {
            "all22": lambda frame: pd.Series(True, index=frame.index),
            "calibration": lambda frame: frame["TN"].isin(CALIBRATION_TN[season]),
            "diagnostic": lambda frame: ~frame["TN"].isin(CALIBRATION_TN[season]),
        }
        for role, mask_func in role_masks.items():
            for kind, frame in sources.items():
                sub = frame.loc[mask_func(frame)]
                for obs_col in [c for c in sub.columns if c.startswith("OBS_")]:
                    variable = obs_col[4:]
                    sim_col = f"SIM_{variable}"
                    if sim_col in sub:
                        rows.append({"season": season, "role": role, "kind": kind, "variable": variable,
                                     **metrics(sub[obs_col], sub[sim_col])})
            harvest = sources["harvest"].loc[mask_func(sources["harvest"])]
            terminal = harvest.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1)
            for variable in ("DRY_CUM", "FRESH_CUM"):
                terminal_rows.append({"season": season, "role": role, "variable": f"TERMINAL_{variable}",
                                      **metrics(terminal[f"OBS_{variable}"], terminal[f"SIM_{variable}"])})
    return pd.DataFrame(rows), pd.DataFrame(terminal_rows)


def response_metrics() -> pd.DataFrame:
    mapping = pd.read_csv(DET / "two_season_water_n_mapping_from_filex.csv").rename(
        columns={"season_id": "season", "treatment": "TN"}
    )
    rows: list[dict] = []
    for season in ("25SP", "26SP"):
        harvest = pd.read_csv(DET / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv")
        season_mapping = mapping.loc[
            mapping["season"].eq(season), ["TN", "water_level", "nitrogen_level"]
        ]
        harvest = harvest.merge(season_mapping, on="TN", how="left")
        for contrast, strata, hi_field, lo_field, group_field in (
            ("N3_minus_N0", sorted(harvest["water_level"].dropna().unique()), "N3", "N0", "water_level"),
            ("W3_minus_W1", ["N3", "N0"], "W3", "W1", "nitrogen_level"),
        ):
            for stratum in strata:
                sub = harvest[harvest[group_field] == stratum]
                level_field = "nitrogen_level" if group_field == "water_level" else "water_level"
                indexed = sub.set_index(["HNO", level_field]).sort_index()
                values = []
                for hno in sorted(sub["HNO"].unique()):
                    try:
                        hi = indexed.loc[(hno, hi_field)]
                        lo = indexed.loc[(hno, lo_field)]
                    except KeyError:
                        continue
                    if isinstance(hi, pd.DataFrame) or isinstance(lo, pd.DataFrame):
                        continue
                    values.append({
                        "observed": float(hi["OBS_DRY_CUM"] - lo["OBS_DRY_CUM"]),
                        "simulated": float(hi["SIM_DRY_CUM"] - lo["SIM_DRY_CUM"]),
                    })
                frame = pd.DataFrame(values)
                if not frame.empty:
                    rows.append({"season": season, "contrast": contrast, "stratum": stratum,
                                 **metrics(frame["observed"], frame["simulated"])})
    return pd.DataFrame(rows)


def convergence() -> tuple[pd.DataFrame, int, str, float]:
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv", index_col=0)
    members = [column for column in phi.columns if str(column).isdigit()]
    rows = []
    candidates = []
    for iteration in phi.index:
        values = pd.to_numeric(phi.loc[iteration, members], errors="coerce")
        best_member = str(values.idxmin())
        best_phi = float(values.min())
        candidates.append((best_phi, int(iteration), best_member))
        rows.append({"iteration": int(iteration), "best_member": best_member, "minimum": best_phi,
                     "mean": float(values.mean()), "median": float(values.median()),
                     "q05": float(values.quantile(.05)), "q95": float(values.quantile(.95))})
    best_phi, best_iteration, best_member = min(candidates)
    return pd.DataFrame(rows), best_iteration, best_member, best_phi


def boundary_pressure(iteration: int, member: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    par = pd.read_csv(RUN / f"{CASE}.{iteration}.par.csv")
    real_col = "real_name" if "real_name" in par else par.columns[0]
    row = par.loc[par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(member)].iloc[0]
    active = pst.parameter_data.loc[pst.parameter_data["partrans"] == "none"].copy()
    records = []
    final_ensemble = pd.read_csv(RUN / f"{CASE}.6.par.csv").set_index(real_col)
    for name, definition in active.iterrows():
        value = float(row[name])
        lower, upper = float(definition["parlbnd"]), float(definition["parubnd"])
        span = upper - lower
        distance_lower = (value - lower) / span if span > 0 else np.nan
        distance_upper = (upper - value) / span if span > 0 else np.nan
        ensemble_values = pd.to_numeric(final_ensemble[name], errors="coerce")
        near_fraction = float(((ensemble_values - lower <= 0.02 * span) | (upper - ensemble_values <= 0.02 * span)).mean()) if span > 0 else np.nan
        records.append({"parameter": name, "value": value, "lower": lower, "upper": upper,
                        "normalized_distance_lower": distance_lower, "normalized_distance_upper": distance_upper,
                        "best_member_near_boundary_2pct": min(distance_lower, distance_upper) <= .02,
                        "final_ensemble_near_boundary_fraction_2pct": near_fraction})
    detail = pd.DataFrame(records).sort_values(["best_member_near_boundary_2pct", "final_ensemble_near_boundary_fraction_2pct"], ascending=False)
    summary = pd.DataFrame([{
        "active_parameters": len(detail),
        "best_member_near_boundary_count_2pct": int(detail["best_member_near_boundary_2pct"].sum()),
        "parameters_with_final_ensemble_boundary_fraction_ge_0_20": int((detail["final_ensemble_near_boundary_fraction_2pct"] >= .20).sum()),
    }])
    return detail, summary


def objective_contributions(iteration: int, member: str) -> pd.DataFrame:
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    observations = pst.observation_data[["obsval", "weight", "obgnme"]].copy()
    simulations = pd.read_csv(RUN / f"{CASE}.{iteration}.obs.csv")
    simulations["real_name"] = simulations["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
    simulated = simulations.set_index("real_name").loc[member]
    observations["simulated"] = [simulated[name] for name in observations.index]
    observations["phi"] = ((observations["simulated"] - observations["obsval"]) * observations["weight"]) ** 2
    grouped = observations.groupby("obgnme", as_index=False)["phi"].sum().sort_values("phi", ascending=False)
    grouped["phi_fraction"] = grouped["phi"] / grouped["phi"].sum()
    return grouped


def previous_formal_comparison() -> pd.DataFrame:
    previous = ROOT / "workspace/runs/e02_formal_armab_rrmse_official_200x6_20260828/best_member_152_two_season_deterministic_20260828/metrics_by_season_variable.csv"
    current = DET / "metrics_by_season_variable.csv"
    if not previous.is_file() or not current.is_file():
        return pd.DataFrame()
    old = pd.read_csv(previous)
    new = pd.read_csv(current)
    keys = ["season", "kind", "variable"]
    result = new.merge(old, on=keys, suffixes=("_new", "_old"))
    for metric in ("rmse", "rrmse_pct", "bias", "nse", "d_index", "r2"):
        result[f"delta_{metric}_new_minus_old"] = result[f"{metric}_new"] - result[f"{metric}_old"]
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    role, terminal = role_metrics()
    response = response_metrics()
    conv, iteration, member, phi = convergence()
    boundary, boundary_summary = boundary_pressure(iteration, member)
    contributions = objective_contributions(iteration, member)
    previous = previous_formal_comparison()
    role.to_csv(OUT / "metrics_by_season_role_variable.csv", index=False)
    terminal.to_csv(OUT / "terminal_yield_metrics_by_season_role.csv", index=False)
    response.to_csv(OUT / "water_nitrogen_response_metrics.csv", index=False)
    conv.to_csv(OUT / "phi_convergence_summary.csv", index=False)
    boundary.to_csv(OUT / "best_member_and_ensemble_boundary_pressure.csv", index=False)
    boundary_summary.to_csv(OUT / "boundary_pressure_summary.csv", index=False)
    contributions.to_csv(OUT / "best_member_phi_by_observation_group.csv", index=False)
    if not previous.empty:
        previous.to_csv(OUT / "comparison_to_previous_formal_best152.csv", index=False)
    payload = {
        "best_member": member,
        "best_iteration": iteration,
        "best_actual_phi": phi,
        "engineering_quality": json.loads((RUN / "ies_quality/ies_run_quality.json").read_text(encoding="utf-8"))["status"],
        "all22_treatments": 22,
        **boundary_summary.iloc[0].to_dict(),
        "top_10_observation_groups_phi_fraction": float(contributions.head(10)["phi_fraction"].sum()),
    }
    (OUT / "result_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nTerminal yield metrics:\n", terminal.to_string(index=False))
    print("\nResponse metrics:\n", response.to_string(index=False))
    print("\nNear-boundary best-member parameters:\n", boundary.loc[boundary["best_member_near_boundary_2pct"], ["parameter", "value", "lower", "upper"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
