"""Audit water-response and terminal-LAI limitations of selected8 member 192.

This is a read-only diagnostic.  It reconstructs evidence from the frozen PEST
control file, iteration ensembles, group Phi output, and deterministic replay.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_selected8_fixedsoil_nse_official_200x6_20260818"
RUN = ROOT / "workspace/runs" / CASE
DET = RUN / "deterministic_candidates/best_phi_member192_three_season_20260818"
OUT = ROOT / "workspace/reports/selected8_water_lai_diagnostic_20260818"
BEST_MEMBER = 192
SELECTED = {"25SP": {2, 5, 10, 13}, "26SP": {2, 3, 11, 12}, "25FA": set()}


def _nse_rows(pred: pd.DataFrame, target: np.ndarray) -> pd.Series:
    sst = float(np.square(target - target.mean()).sum())
    return 1.0 - pred.sub(target, axis=1).pow(2).sum(axis=1) / sst


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    obsdef = pst.observation_data.copy()
    obsdef.index = obsdef.obsnme.str.lower()

    # Actual objective-function allocation for the selected deterministic member.
    phi = pd.read_csv(RUN / f"{CASE}.phi.group.csv")
    row = phi.loc[(phi.iteration == 6) & (phi.par_realization == BEST_MEMBER)].iloc[0]
    meta = {"iteration", "total_runs", "obs_realization", "par_realization"}
    values = row.drop(labels=list(meta)).astype(float)
    category_rules = {
        "W_RESPONSE": lambda c: "wresp" in c,
        "N_RESPONSE": lambda c: "nresp" in c,
        "CANOPY_INCREMENT": lambda c: "laiddm" in c,
        "CANOPY_TERMINAL": lambda c: "laietm" in c,
        "LEAF_MASS": lambda c: "lwaddm" in c or "lwetm" in c,
        "STEM_MASS": lambda c: "swaddm" in c or "swetm" in c,
        "DRY_CUMULATIVE_NSE": lambda c: c == "drynse",
        "SOIL_WATER": lambda c: "_sw00" in c,
    }
    used: set[str] = set()
    objective_rows = []
    total_phi = float(values.sum())
    for category, rule in category_rules.items():
        cols = [c for c in values.index if rule(c)]
        used.update(cols)
        value = float(values[cols].sum())
        objective_rows.append(
            {"category": category, "phi": value, "share_pct": 100.0 * value / total_phi}
        )
    other = float(values[[c for c in values.index if c not in used]].sum())
    objective_rows.append({"category": "OTHER", "phi": other, "share_pct": 100.0 * other / total_phi})
    objective = pd.DataFrame(objective_rows).sort_values("phi", ascending=False)
    objective.to_csv(OUT / "objective_phi_allocation.csv", index=False, encoding="utf-8-sig")

    # Did PEST improve the explicit water-response objective, and did the active
    # parameter space generate enough response variability?
    response_rows = []
    for iteration in (0, 6):
        oe = pd.read_csv(RUN / f"{CASE}.{iteration}.obs.csv", index_col=0)
        oe.columns = oe.columns.str.lower()
        for season in ("25sp", "26sp"):
            names = obsdef.loc[obsdef.obgnme.str.contains(f"{season}_wrespm"), "obsnme"].str.lower().tolist()
            target = obsdef.loc[names, "obsval"].astype(float).to_numpy()
            pred = oe[names].astype(float)
            nse = _nse_rows(pred, target)
            response_rows.append(
                {
                    "season": season.upper(),
                    "iteration": iteration,
                    "n_response_points": len(names),
                    "target_sd": float(np.std(target, ddof=1)),
                    "median_prediction_sd_across_members": float(pred.std(axis=0).median()),
                    "nse_min": float(nse.min()),
                    "nse_median": float(nse.median()),
                    "nse_max": float(nse.max()),
                    "member192_nse": float(nse.loc[BEST_MEMBER]),
                }
            )
    response_evolution = pd.DataFrame(response_rows)
    response_evolution.to_csv(OUT / "water_response_ensemble_evolution.csv", index=False, encoding="utf-8-sig")

    mapping = pd.read_csv(DET / "three_season_water_n_mapping_from_filex.csv").rename(
        columns={"season_id": "season", "treatment": "TN"}
    )

    # Final cumulative dry-mass contrasts for every available nitrogen level.
    contrast_rows = []
    for season, high_water in (("25SP", "W3"), ("26SP", "W2")):
        harvest = pd.read_csv(DET / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv")
        final = harvest.sort_values("DATE").groupby("TN", as_index=False).tail(1)
        final["season"] = season
        final = final.merge(
            mapping[["season", "TN", "water_level", "nitrogen_level"]],
            on=["season", "TN"], how="left",
        )
        wide = final.pivot(index="nitrogen_level", columns="water_level", values=["OBS_DRY_CUM", "SIM_DRY_CUM"])
        for nitrogen in sorted(final.nitrogen_level.dropna().unique()):
            observed = float(wide.loc[nitrogen, ("OBS_DRY_CUM", high_water)] - wide.loc[nitrogen, ("OBS_DRY_CUM", "W1")])
            simulated = float(wide.loc[nitrogen, ("SIM_DRY_CUM", high_water)] - wide.loc[nitrogen, ("SIM_DRY_CUM", "W1")])
            contrast_rows.append(
                {
                    "season": season,
                    "nitrogen_level": nitrogen,
                    "contrast": f"{high_water}-W1",
                    "observed_g_m2": observed,
                    "simulated_g_m2": simulated,
                    "error_g_m2": simulated - observed,
                }
            )
    contrasts = pd.DataFrame(contrast_rows)
    contrasts.to_csv(OUT / "terminal_water_contrasts_by_nitrogen.csv", index=False, encoding="utf-8-sig")

    # Last valid LAI observation per treatment, split by calibration inclusion.
    terminal_parts = []
    for season in ("25SP", "25FA", "26SP"):
        process = pd.read_csv(DET / "_seasons" / season / f"{season}_deterministic_process_compare.csv")
        valid = process.loc[process.OBS_LAID.notna() & (process.OBS_LAID != -99)].copy()
        valid = valid.sort_values("DATE").groupby("TN", as_index=False).tail(1)
        valid["season"] = season
        valid["calibration_treatment"] = valid.TN.isin(SELECTED[season])
        valid["residual_sim_minus_obs"] = valid.SIM_LAID - valid.OBS_LAID
        terminal_parts.append(valid)
    terminal = pd.concat(terminal_parts, ignore_index=True).merge(
        mapping[["season", "TN", "water_level", "nitrogen_level"]],
        on=["season", "TN"], how="left",
    )
    terminal_cols = [
        "season", "TN", "water_level", "nitrogen_level", "calibration_treatment",
        "DATE", "OBS_LAID", "SIM_LAID", "residual_sim_minus_obs",
    ]
    terminal[terminal_cols].to_csv(OUT / "terminal_lai_by_treatment.csv", index=False, encoding="utf-8-sig")
    terminal_summary = (
        terminal.groupby(["season", "calibration_treatment"], dropna=False)
        .agg(
            n=("TN", "size"),
            observed_mean=("OBS_LAID", "mean"),
            simulated_mean=("SIM_LAID", "mean"),
            bias=("residual_sim_minus_obs", "mean"),
            rmse=("residual_sim_minus_obs", lambda x: float(np.sqrt(np.mean(np.square(x))))),
        )
        .reset_index()
    )
    terminal_summary.to_csv(OUT / "terminal_lai_summary.csv", index=False, encoding="utf-8-sig")

    # Boundary pressure in parameters plausibly connected to water and LAI.
    par = pst.parameter_data.copy()
    par.index = par.parnme.str.lower()
    ensemble = pd.read_csv(RUN / f"{CASE}.6.par.csv", index_col=0)
    ensemble.columns = ensemble.columns.str.lower()
    best = ensemble.loc[BEST_MEMBER]
    focus = {
        "RWUMX": "water uptake", "DSWBAR": "water-stress sensing depth",
        "PORMIN": "root aeration threshold", "RTEXF": "root exploration",
        "PORPT": "root porosity response", "KC_SLOPE": "canopy photosynthesis",
        "SENRTE": "leaf senescence", "SENDAY": "leaf senescence",
        "SLAREF": "specific leaf area", "SLAVR": "specific leaf area",
        "SIZLF": "leaf size", "LFMAX": "leaf expansion",
    }
    boundary_rows = []
    for display, role in focus.items():
        name = display.lower()
        q = par.loc[name]
        lower, upper, value = float(q.parlbnd), float(q.parubnd), float(best[name])
        span = upper - lower
        member_values = ensemble[name].astype(float)
        boundary_rows.append(
            {
                "parameter": display,
                "role": role,
                "lower": lower,
                "member192": value,
                "upper": upper,
                "relative_position": (value - lower) / span,
                "ensemble_near_lower_1pct": float((((member_values - lower) / span) <= 0.01).mean()),
                "ensemble_near_upper_1pct": float((((upper - member_values) / span) <= 0.01).mean()),
            }
        )
    boundary = pd.DataFrame(boundary_rows)
    boundary.to_csv(OUT / "focused_parameter_boundary_pressure.csv", index=False, encoding="utf-8-sig")

    active_names = set(par.index[par.partrans.str.lower() != "fixed"])
    structural = pd.DataFrame(
        [
            {"parameter_family": "XSWFAC/YSWFAC", "active": False, "role": "water-stress response curve"},
            {"parameter_family": "XSWBAR/YSWBAR", "active": False, "role": "topsoil-water response curve"},
            {"parameter_family": "XTRFAC/YTRFAC", "active": False, "role": "turgor/reproductive response curve"},
            {"parameter_family": "SENPOR", "active": "senpor" in active_names, "role": "waterlogging-driven senescence"},
            {"parameter_family": "SENRT2", "active": "senrt2" in active_names, "role": "secondary senescence rate"},
            {"parameter_family": "SLAREF and SLAVR", "active": {"slaref", "slavr"}.issubset(active_names), "role": "redundant SLA scale freedoms"},
        ]
    )
    structural.to_csv(OUT / "structural_parameter_coverage.csv", index=False, encoding="utf-8-sig")

    # A small SQLite evidence store makes every report chart/table query
    # independently runnable and keeps source provenance explicit.
    sqlite_path = OUT / "diagnostic_evidence.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        objective.to_sql("objective_phi_allocation", connection, if_exists="replace", index=False)
        response_evolution.to_sql("water_response_ensemble_evolution", connection, if_exists="replace", index=False)
        contrasts.to_sql("terminal_water_contrasts", connection, if_exists="replace", index=False)
        terminal_summary.to_sql("terminal_lai_summary", connection, if_exists="replace", index=False)
        boundary.to_sql("focused_parameter_boundary_pressure", connection, if_exists="replace", index=False)
        structural.to_sql("structural_parameter_coverage", connection, if_exists="replace", index=False)

    summary = {
        "case": CASE,
        "best_member": BEST_MEMBER,
        "total_phi": total_phi,
        "w_response_phi_share_pct": float(objective.loc[objective.category == "W_RESPONSE", "share_pct"].iloc[0]),
        "lai_objective_phi_share_pct": float(objective.loc[objective.category.isin(["CANOPY_INCREMENT", "CANOPY_TERMINAL"]), "share_pct"].sum()),
        "leaf_stem_phi_share_pct": float(objective.loc[objective.category.isin(["LEAF_MASS", "STEM_MASS"]), "share_pct"].sum()),
        "diagnosis": {
            "primary": "objective weighting and treatment/target coverage",
            "secondary": "missing water-response curve degrees of freedom and shared-season structural limitation",
            "contributing": "selected canopy/SLA boundary pressure and SLA equifinality",
            "not_supported": "a simple across-the-board bound expansion as the main remedy",
        },
    }
    (OUT / "diagnostic_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Evidence written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
