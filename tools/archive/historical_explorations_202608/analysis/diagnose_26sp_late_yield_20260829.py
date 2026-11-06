"""Diagnose the 26SP late-yield deficit using deterministic and IES evidence."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
CASE = "e02_formal_yield_rebalanced_post_200x6_20260829"
DET = RUN / "best_member_153_two_season_deterministic_20260829"
OUT = RUN / "diagnosis_26sp_late_yield_20260829"


def _ensemble(iteration: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    par = pd.read_csv(RUN / f"{CASE}.{iteration}.par.csv")
    obs = pd.read_csv(RUN / f"{CASE}.{iteration}.obs.csv")
    for frame in (par, obs):
        frame["real_name"] = frame["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
        frame.set_index("real_name", inplace=True)
    return par, obs


def _terminal_targets(obs: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    targets = registry.loc[
        registry["season_id"].eq("26SP") & registry["rrmse_lambda"].notna(),
        ["obsnme", "treatment", "raw_obsval"],
    ].copy()
    columns = [name.lower() for name in targets["obsnme"]]
    simulated = obs[columns].copy()
    simulated.columns = [f"tn{int(treatment)}" for treatment in targets["treatment"]]
    simulated["terminal_mean"] = simulated.mean(axis=1)
    simulated["terminal_bias"] = simulated["terminal_mean"] - targets["raw_obsval"].mean()
    return simulated


def _spearman(par: pd.DataFrame, targets: pd.DataFrame, members: list[str], label: str) -> pd.DataFrame:
    joined = par.loc[members].join(targets.loc[members])
    target_columns = ["terminal_mean", "terminal_bias", "tn1", "tn3", "tn9", "tn12"]
    parameter_columns = [column for column in par.columns if pd.api.types.is_numeric_dtype(par[column])]
    rows = []
    for parameter in parameter_columns:
        if joined[parameter].nunique(dropna=True) < 4:
            continue
        for target in target_columns:
            rho = joined[[parameter, target]].corr(method="spearman").iloc[0, 1]
            rows.append({"ensemble": label, "parameter": parameter, "target": target,
                         "spearman_rho": rho, "abs_rho": abs(rho)})
    return pd.DataFrame(rows)


def _weather_summary() -> pd.DataFrame:
    rows = []
    definitions = [
        ("25SP", DET / "_seasons/25SP/XXLI2502.WTH", 2025, 140, 207),
        ("26SP", DET / "_seasons/26SP/XXQL2601.WTH", 2026, 146, 198),
    ]
    for season, path, year, start, end in definitions:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        header = next(index for index, line in enumerate(lines) if line.startswith("@  DATE"))
        weather = pd.read_csv(path, sep=r"\s+", skiprows=header + 1,
                              names=["DATE", "SRAD", "TMAX", "TMIN", "RAIN", "RHUM"])
        weather["YEAR"] = weather["DATE"] // 1000
        weather["DOY"] = weather["DATE"] % 1000
        selected = weather.loc[
            weather["YEAR"].eq(year) & weather["DOY"].between(start, end)
        ]
        rows.append({
            "season": season, "period": f"{year}-{start:03d} to {year}-{end:03d}",
            "days": len(selected), "mean_srad": selected["SRAD"].mean(),
            "mean_tmax": selected["TMAX"].mean(), "mean_tmin": selected["TMIN"].mean(),
            "days_tmax_ge_30": int(selected["TMAX"].ge(30).sum()),
            "days_tmax_ge_35": int(selected["TMAX"].ge(35).sum()),
        })
    return pd.DataFrame(rows)


def _read_dssat_blocks(path: Path) -> pd.DataFrame:
    """Read repeated DSSAT ``*RUN`` tables without assuming one treatment."""
    rows: list[dict[str, float | int]] = []
    run = None
    columns: list[str] | None = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("*RUN"):
            parts = line.split()
            run = int(parts[1])
            columns = None
        elif line.startswith("@YEAR"):
            columns = line[1:].split()
        elif run is not None and columns and line and line[0].isdigit():
            values = line.split()
            if len(values) != len(columns):
                continue
            record: dict[str, float | int] = {"TN": run}
            for key, value in zip(columns, values):
                record[key] = float(value)
            rows.append(record)
    return pd.DataFrame(rows)


def _stress_summary() -> pd.DataFrame:
    plant_gro = _read_dssat_blocks(DET / "_seasons/26SP/PlantGro.OUT")
    plant_n = _read_dssat_blocks(DET / "_seasons/26SP/PlantN.OUT")
    window = plant_gro.loc[plant_gro["DOY"].between(146, 198)].copy()
    summary = window.groupby("TN", as_index=False).agg(
        nstd_harvest_mean=("NSTD", "mean"), nstd_harvest_max=("NSTD", "max"),
        wspd_harvest_mean=("WSPD", "mean"), wspd_harvest_max=("WSPD", "max"),
        wsgd_harvest_mean=("WSGD", "mean"), wsgd_harvest_max=("WSGD", "max"),
        gwgd_mean=("GWGD", "mean"), cwad_terminal=("CWAD", "last"),
        gwad_terminal=("GWAD", "last"), lai_terminal=("LAID", "last"),
    )
    whole_season = plant_gro.groupby("TN", as_index=False).agg(
        nstd_season_mean=("NSTD", "mean"), nstd_season_max=("NSTD", "max"),
        wspd_season_mean=("WSPD", "mean"), wspd_season_max=("WSPD", "max"),
        wsgd_season_mean=("WSGD", "mean"), wsgd_season_max=("WSGD", "max"),
    )
    n_window = plant_n.loc[plant_n["DOY"].between(146, 198)]
    n_summary = n_window.groupby("TN", as_index=False).agg(
        nupc_at_start=("NUPC", "first"), nupc_terminal=("NUPC", "last"),
        leaf_n_pct_mean=("LN%D", "mean"), stem_n_pct_mean=("SN%D", "mean"),
    )
    return summary.merge(whole_season, on="TN", how="left").merge(n_summary, on="TN", how="left")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    active = pst.parameter_data.loc[pst.parameter_data["partrans"].eq("none")]

    harvest = pd.read_csv(DET / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    harvest["bias"] = harvest["SIM_DRY_CUM"] - harvest["OBS_DRY_CUM"]
    harvest["relative_bias_pct"] = 100 * harvest["bias"] / harvest["OBS_DRY_CUM"]
    by_harvest = harvest.groupby("HNO", as_index=False).agg(
        date=("DATE", "first"), observed_mean=("OBS_DRY_CUM", "mean"),
        simulated_mean=("SIM_DRY_CUM", "mean"), bias_mean=("bias", "mean"),
        relative_bias_median_pct=("relative_bias_pct", "median"),
    )
    terminal = harvest.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1)
    mapping = pd.read_csv(ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv")
    terminal = terminal.merge(
        mapping.loc[mapping["season_id"].eq("26SP"),
                    ["treatment", "water_level", "nitrogen_level"]],
        left_on="TN", right_on="treatment", how="left",
    )
    terminal.to_csv(OUT / "terminal_bias_by_treatment.csv", index=False)
    by_harvest.to_csv(OUT / "cumulative_bias_by_harvest.csv", index=False)

    par0, obs0 = _ensemble(0)
    provenance = pd.read_csv(RUN / "posterior_mixture_prior_members.csv")
    provenance["real_name"] = provenance["real_name"].astype(str)
    lhs = provenance.loc[provenance["source"].str.startswith("lhs_"), "real_name"]
    lhs_members = [member for member in lhs if member in par0.index and member in obs0.index]
    targets0 = _terminal_targets(obs0, registry)
    prior_corr = _spearman(par0[list(active.index)], targets0, lhs_members, "prior_full_bounds_lhs")

    par6, obs6 = _ensemble(6)
    final_members = sorted(set(par6.index) & set(obs6.index))
    targets6 = _terminal_targets(obs6, registry)
    final_corr = _spearman(par6[list(active.index)], targets6, final_members, "final_posterior")
    correlations = pd.concat([prior_corr, final_corr], ignore_index=True)
    correlations.sort_values(["ensemble", "target", "abs_rho"], ascending=[True, True, False]).to_csv(
        OUT / "parameter_yield_spearman.csv", index=False
    )

    candidate_metrics = pd.read_csv(RUN / "candidate_audit_20260829/all_iteration_candidate_metrics.csv")
    best_26 = candidate_metrics.sort_values("26sp_terminal_rrmse_pct").iloc[0]
    candidates = [(4, "153", "lowest_phi"),
                  (int(best_26["iteration"]), str(int(best_26["member"])), "best_26sp_terminal_rrmse")]
    candidate_rows = []
    for iteration, member, role in candidates:
        par, _ = _ensemble(iteration)
        row = par.loc[member]
        for parameter in active.index:
            lower = float(active.loc[parameter, "parlbnd"])
            upper = float(active.loc[parameter, "parubnd"])
            candidate_rows.append({
                "role": role, "iteration": iteration, "member": member,
                "parameter": parameter, "value": float(row[parameter]),
                "lower": lower, "upper": upper,
                "normalized_position": (float(row[parameter]) - lower) / (upper - lower)
                if upper > lower else np.nan,
            })
    candidate_values = pd.DataFrame(candidate_rows)
    pivot = candidate_values.pivot(index="parameter", columns="role", values="normalized_position")
    pivot["normalized_shift_best26_minus_lowestphi"] = (
        pivot["best_26sp_terminal_rrmse"] - pivot["lowest_phi"]
    )
    comparison = candidate_values.merge(
        pivot[["normalized_shift_best26_minus_lowestphi"]], left_on="parameter", right_index=True
    )
    comparison.to_csv(OUT / "candidate_parameter_contrast.csv", index=False)

    weather = _weather_summary()
    weather.to_csv(OUT / "harvest_period_weather_summary.csv", index=False)
    stress = _stress_summary()
    stress = stress.merge(
        mapping.loc[mapping["season_id"].eq("26SP"),
                    ["treatment", "water_level", "nitrogen_level"]],
        left_on="TN", right_on="treatment", how="left",
    )
    stress.to_csv(OUT / "harvest_period_stress_by_treatment.csv", index=False)

    posterior_rows = []
    for parameter in active.index:
        values = par6[parameter].dropna()
        lower = float(active.loc[parameter, "parlbnd"])
        upper = float(active.loc[parameter, "parubnd"])
        width = upper - lower
        posterior_rows.append({
            "parameter": parameter, "lower": lower, "upper": upper,
            "q05": values.quantile(0.05), "median": values.median(),
            "q95": values.quantile(0.95),
            "fraction_near_lower_5pct": float((values <= lower + 0.05 * width).mean()),
            "fraction_near_upper_5pct": float((values >= upper - 0.05 * width).mean()),
        })
    pd.DataFrame(posterior_rows).to_csv(OUT / "posterior_boundary_diagnostics.csv", index=False)
    phtmax = candidate_values.loc[candidate_values["parameter"].eq("phtmax")]
    prior_pht_corr = prior_corr.loc[
        prior_corr["parameter"].eq("phtmax") & prior_corr["target"].eq("terminal_mean"),
        "spearman_rho",
    ]
    payload = {
        "lowest_phi_member": "153 iteration 4",
        "best_26sp_yield_member": f"{int(best_26['member'])} iteration {int(best_26['iteration'])}",
        "best_26sp_terminal_rrmse_pct": float(best_26["26sp_terminal_rrmse_pct"]),
        "best_26sp_25sp_terminal_rrmse_pct": float(best_26["25sp_terminal_rrmse_pct"]),
        "phtmax_lowest_phi": float(phtmax.loc[phtmax["role"].eq("lowest_phi"), "value"].iloc[0]),
        "phtmax_best_26sp": float(phtmax.loc[phtmax["role"].eq("best_26sp_terminal_rrmse"), "value"].iloc[0]),
        "phtmax_bounds": [float(active.loc["phtmax", "parlbnd"]), float(active.loc["phtmax", "parubnd"])],
        "prior_lhs_phtmax_terminal_yield_spearman": float(prior_pht_corr.iloc[0]),
        "largest_gap_harvest": int(by_harvest.loc[by_harvest["bias_mean"].idxmin(), "HNO"]),
        "largest_gap_bias_mean": float(by_harvest["bias_mean"].min()),
    }
    (OUT / "diagnosis_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nTop prior-LHS correlations with terminal mean yield:\n", prior_corr.loc[
        prior_corr["target"].eq("terminal_mean")
    ].nlargest(20, "abs_rho")[["parameter", "spearman_rho"]].to_string(index=False))
    print("\nHarvest bias:\n", by_harvest.to_string(index=False))
    print("\nTerminal bias by treatment:\n", terminal[[
        "TN", "water_level", "nitrogen_level", "OBS_DRY_CUM", "SIM_DRY_CUM", "bias", "relative_bias_pct"
    ]].to_string(index=False))
    print("\nHarvest-period stress by treatment:\n", stress.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
