"""Audit v37 local nitrogen multi-arm IES results against predeclared gates.

The anchor is explicitly v37 iteration-3 realization 137.  Candidate metrics
are reconstructed from the PEST observation ensembles and observation
registries; no existing "best member" label is consumed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829/postrun_analysis"
MAPPING = ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"
ARMS = {
    arm: (
        ROOT / f"workspace/runs/e02_v37_nmulti_arm_{arm}_60x3_20260829",
        f"e02_v37_nmulti_arm_{arm}_20260829",
    )
    for arm in "abcde"
}
BOUND_SUFFIX = {
    "a": "local_nitrogen_baseline",
    "b": "nresponse_weight_only",
    "c": "uptake_supply_trigger",
    "d": "protein_demand_mobilization",
    "e": "leaf_n_photosynthesis_curve",
}
BASELINE = {
    "25SP_nresp_W1_nse": -6.1405,
    "25SP_nresp_W3_nse": -7.9375,
    "26SP_nresp_W1_nse": -6.2487,
    "26SP_nresp_W3_nse": -8.4122,
    "25SP_nresp_W3_terminal_sim": -4694.1,
    "25SP_nresp_W1_terminal_sim": -2084.3,
    "26SP_nresp_all_sae": np.nan,
    "25SP_fresh_cum_nse": 0.7776,
    "26SP_fresh_cum_nse": 0.7625,
    "25SP_lai_nse": 0.8802,
    "26SP_lai_nse": 0.5024,
    "25SP_wresp_N0_nse": 0.2200,
    "25SP_wresp_N3_nse": -1.4833,
    "26SP_wresp_N0_nse": 0.3138,
    "26SP_wresp_N3_nse": -0.2046,
}


def metric(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    # Response contrasts are signed and can legitimately be below -99.  The
    # selected objective rows are already valid observations, so filtering by
    # value here would silently delete the strongest negative N/W responses.
    valid = np.isfinite(obs) & np.isfinite(sim)
    o, s = obs[valid], sim[valid]
    if not len(o):
        return {"n": 0, "nse": np.nan, "mae": np.nan, "sae": np.nan,
                "rrmse_pct": np.nan, "pbias_pct": np.nan}
    residual = s - o
    sst = float(np.square(o - o.mean()).sum())
    return {
        "n": int(len(o)),
        "nse": 1.0 - float(np.square(residual).sum()) / sst if sst > 0 else np.nan,
        "mae": float(np.abs(residual).mean()),
        "sae": float(np.abs(residual).sum()),
        "rrmse_pct": 100.0 * float(np.sqrt(np.square(residual).mean())) / float(np.mean(np.abs(o))),
        "pbias_pct": 100.0 * float(residual.sum()) / float(o.sum()),
    }


def raw_sim(registry: pd.DataFrame, row: pd.Series) -> np.ndarray:
    lookup = row.copy()
    lookup.index = lookup.index.astype(str).str.lower()
    values = pd.to_numeric(registry["obsnme"].str.lower().map(lookup), errors="coerce").to_numpy(float)
    is_log = registry["transform"].astype(str).str.lower().eq("log").to_numpy()
    offset = pd.to_numeric(registry["transform_offset"], errors="coerce").fillna(0).to_numpy(float)
    values[is_log] = np.exp(values[is_log]) - offset[is_log]
    return values


def group_metric(registry: pd.DataFrame, sim: np.ndarray, mask: pd.Series) -> dict[str, float]:
    obs = pd.to_numeric(registry.loc[mask, "raw_obsval"], errors="coerce").to_numpy(float)
    return metric(obs, sim[mask.to_numpy()])


def evaluate_member(registry: pd.DataFrame, sim: np.ndarray, mapping: pd.DataFrame) -> dict[str, float | bool]:
    result: dict[str, float | bool] = {}
    response = registry["obgnme"].str.contains("NRESP|WRESP", regex=True)
    enriched = registry.loc[response, ["season_id", "treatment", "obgnme", "raw_obsval"]].copy()
    enriched["_index"] = enriched.index
    enriched["treatment"] = pd.to_numeric(enriched["treatment"]).astype(int)
    enriched = enriched.merge(
        mapping[["season_id", "treatment", "water_level", "nitrogen_level"]],
        on=["season_id", "treatment"], how="left", validate="many_to_one",
    )
    enriched["simulated"] = sim[enriched["_index"].to_numpy(int)]
    enriched["family"] = np.where(enriched["obgnme"].str.contains("NRESP"), "nresp", "wresp")
    enriched["stratum"] = np.where(
        enriched["family"].eq("nresp"), enriched["water_level"], enriched["nitrogen_level"]
    )
    for (season, family, stratum), frame in enriched.groupby(["season_id", "family", "stratum"]):
        m = metric(frame["raw_obsval"].to_numpy(float), frame["simulated"].to_numpy(float))
        result[f"{season}_{family}_{stratum}_nse"] = m["nse"]
        result[f"{season}_{family}_{stratum}_mae"] = m["mae"]
        result[f"{season}_{family}_{stratum}_sae"] = m["sae"]
        if family == "nresp":
            terminal = frame.assign(
                _harvest=pd.to_numeric(frame["obgnme"].str.extract(r"_H(\d+)$")[0])
            ).sort_values("_harvest").iloc[-1]
            result[f"{season}_{family}_{stratum}_terminal_obs"] = float(terminal["raw_obsval"])
            result[f"{season}_{family}_{stratum}_terminal_sim"] = float(terminal["simulated"])
            result[f"{season}_{family}_{stratum}_terminal_abs_error"] = abs(
                float(terminal["simulated"] - terminal["raw_obsval"])
            )
    for season in ("25SP", "26SP"):
        nframe = enriched.loc[enriched["season_id"].eq(season) & enriched["family"].eq("nresp")]
        nm = metric(nframe["raw_obsval"].to_numpy(float), nframe["simulated"].to_numpy(float))
        result[f"{season}_nresp_all_mae"] = nm["mae"]
        result[f"{season}_nresp_all_sae"] = nm["sae"]

        cumulative_mask = (
            registry["season_id"].eq(season)
            & registry["obgnme"].str.contains(r"_CHFPWM_(?:T_)?H", regex=True)
            & registry["phi_role"].eq("calibration")
        )
        result[f"{season}_fresh_cum_nse"] = group_metric(registry, sim, cumulative_mask)["nse"]
        terminal_mask = (
            registry["season_id"].eq(season)
            & registry["obgnme"].str.fullmatch(fr"{season}_CHFPWM_H(?:10|5)")
            & registry["phi_role"].eq("calibration")
        )
        tm = group_metric(registry, sim, terminal_mask)
        result[f"{season}_terminal_rrmse_pct"] = tm["rrmse_pct"]
        result[f"{season}_terminal_pbias_pct"] = tm["pbias_pct"]
        lai_mask = (
            registry["season_id"].eq(season)
            & registry["obgnme"].str.contains(fr"^{season}_LAIDM_D", regex=True)
            & registry["phi_role"].eq("calibration")
        )
        result[f"{season}_lai_nse"] = group_metric(registry, sim, lai_mask)["nse"]
    return result


def phi_lookup(run: Path, case: str) -> dict[tuple[int, str], float]:
    table = pd.read_csv(run / f"{case}.phi.actual.csv")
    result: dict[tuple[int, str], float] = {}
    for _, row in table.iterrows():
        iteration = int(row["iteration"])
        for column in table.columns:
            if column not in {"iteration", "total_runs", "mean", "standard_deviation", "min", "max", "base"}:
                result[(iteration, str(column))] = float(row[column])
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = pd.read_csv(MAPPING)
    mapping["treatment"] = pd.to_numeric(mapping["treatment"]).astype(int)
    all_rows: list[dict[str, object]] = []
    for arm, (run, case) in ARMS.items():
        registry = pd.read_csv(run / f"{case}_observation_registry.csv")
        phi = phi_lookup(run, case)
        for iteration in range(4):
            ensemble = pd.read_csv(run / f"{case}.{iteration}.obs.csv")
            ensemble["real_name"] = ensemble["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
            for _, member_row in ensemble.iterrows():
                member = str(member_row["real_name"])
                sim = raw_sim(registry, member_row.drop(labels="real_name"))
                metrics = evaluate_member(registry, sim, mapping)
                all_rows.append({"arm": arm.upper(), "iteration": iteration, "member": member,
                                 "phi": phi.get((iteration, member), np.nan), **metrics})
    audit = pd.DataFrame(all_rows)

    # The exact v37 anchor baseline is present as iteration-0 base simulation in every arm.
    base_run, base_case = ARMS["a"]
    base_registry = pd.read_csv(base_run / f"{base_case}_observation_registry.csv")
    base_ensemble = pd.read_csv(base_run / f"{base_case}.0.obs.csv")
    base_row = base_ensemble.loc[base_ensemble["real_name"].astype(str).eq("base")].iloc[0]
    base_metrics = evaluate_member(base_registry, raw_sim(base_registry, base_row.drop(labels="real_name")), mapping)
    baseline = BASELINE | base_metrics
    (OUT / "anchor_metrics.json").write_text(json.dumps(baseline, indent=2, allow_nan=True) + "\n", encoding="utf-8")

    nse_cols = [f"{season}_nresp_{water}_nse" for season in ("25SP", "26SP") for water in ("W3", "W1")]
    w_cols = [f"{season}_wresp_{nitrogen}_nse" for season in ("25SP", "26SP") for nitrogen in ("N3", "N0")]
    audit["nresp_layers_improved"] = sum(audit[c].gt(float(baseline[c])) for c in nse_cols)
    audit["nresp_mean_nse_delta"] = sum(audit[c] - float(baseline[c]) for c in nse_cols) / 4.0
    audit["nresp_worst_nse_delta"] = pd.concat(
        [audit[c] - float(baseline[c]) for c in nse_cols], axis=1
    ).min(axis=1)
    audit["26SP_nresp_abs_error_reduction_pct"] = 100.0 * (
        float(baseline["26SP_nresp_all_sae"]) - audit["26SP_nresp_all_sae"]
    ) / float(baseline["26SP_nresp_all_sae"])
    audit["25SP_terminal_sign_gate"] = (
        audit["25SP_nresp_W3_terminal_sim"].gt(0) & audit["25SP_nresp_W1_terminal_sim"].gt(0)
    )
    audit["n_layers_gate"] = audit["nresp_layers_improved"].ge(3)
    audit["26SP_abs_error_gate"] = audit["26SP_nresp_abs_error_reduction_pct"].ge(30.0)
    audit["fresh_scale_guard"] = True
    audit["lai_guard"] = True
    audit["water_guard"] = True
    for season in ("25SP", "26SP"):
        audit["fresh_scale_guard"] &= audit[f"{season}_fresh_cum_nse"].ge(float(baseline[f"{season}_fresh_cum_nse"]) - 0.03)
        audit["lai_guard"] &= audit[f"{season}_lai_nse"].ge(float(baseline[f"{season}_lai_nse"]) - 0.03)
    for column in w_cols:
        audit["water_guard"] &= audit[column].ge(float(baseline[column]) - 0.30)
    audit["protection_gate"] = audit["fresh_scale_guard"] & audit["lai_guard"] & audit["water_guard"]
    audit["full_gate_pass"] = (
        audit["25SP_terminal_sign_gate"] & audit["26SP_abs_error_gate"]
        & audit["n_layers_gate"] & audit["protection_gate"]
    )
    audit.to_csv(OUT / "all_iteration_candidate_metrics.csv", index=False)

    selected: list[pd.Series] = []
    for arm, frame in audit.groupby("arm"):
        final = frame.loc[frame["iteration"].eq(3)].copy()
        eligible = final.loc[final["protection_gate"]].copy()
        pool = eligible if not eligible.empty else final
        winner = pool.sort_values(
            ["full_gate_pass", "25SP_terminal_sign_gate", "26SP_abs_error_gate",
             "n_layers_gate", "nresp_layers_improved", "26SP_nresp_abs_error_reduction_pct",
             "nresp_mean_nse_delta", "phi"],
            ascending=[False, False, False, False, False, False, False, True],
        ).iloc[0].copy()
        winner["selection_rule"] = "science gates first; Phi last; final iteration only"
        selected.append(winner)
    selected_df = pd.DataFrame(selected)
    selected_df.to_csv(OUT / "selected_arm_candidates.csv", index=False)

    summaries = []
    for arm, frame in audit.groupby("arm"):
        final = frame.loc[frame["iteration"].eq(3)]
        chosen = selected_df.loc[selected_df["arm"].eq(arm)].iloc[0]
        summaries.append({
            "arm": arm,
            "final_members": len(final),
            "full_gate_pass_count": int(final["full_gate_pass"].sum()),
            "terminal_sign_pass_count": int(final["25SP_terminal_sign_gate"].sum()),
            "26sp_abs_error_pass_count": int(final["26SP_abs_error_gate"].sum()),
            "three_layer_pass_count": int(final["n_layers_gate"].sum()),
            "protection_pass_count": int(final["protection_gate"].sum()),
            "selected_member": chosen["member"],
            "selected_phi": chosen["phi"],
            "selected_layers_improved": chosen["nresp_layers_improved"],
            "selected_26sp_abs_error_reduction_pct": chosen["26SP_nresp_abs_error_reduction_pct"],
            "selected_terminal_sign_gate": chosen["25SP_terminal_sign_gate"],
            "selected_protection_gate": chosen["protection_gate"],
            "selected_full_gate_pass": chosen["full_gate_pass"],
        })
    pd.DataFrame(summaries).to_csv(OUT / "arm_gate_summary.csv", index=False)

    # Parameter values and posterior pressure for the selected member of each arm.
    parameter_rows = []
    posterior_rows = []
    for _, chosen in selected_df.iterrows():
        arm = str(chosen["arm"]).lower()
        run, case = ARMS[arm]
        par = pd.read_csv(run / f"{case}.3.par.csv")
        par["real_name"] = par["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
        par = par.set_index("real_name")
        bounds = pd.read_csv(
            ROOT / "data/parameter_registry/bounds_frozen/eggplant"
            / f"eggplant_e02_v37_nmulti_arm_{arm}_{BOUND_SUFFIX[arm]}_bounds.csv"
        )
        bounds["name"] = bounds["name"].astype(str).str.lower()
        for name in par.columns:
            spec = bounds.loc[bounds["name"].eq(name)].iloc[0]
            values = pd.to_numeric(par[name], errors="coerce")
            width = float(spec["upper"] - spec["lower"])
            value = float(par.loc[str(chosen["member"]), name])
            parameter_rows.append({"arm": chosen["arm"], "member": chosen["member"],
                                   "parameter": name, "value": value})
            if str(spec["status"]).lower() == "active" and width > 0:
                posterior_rows.append({
                    "arm": chosen["arm"], "parameter": name, "lower": spec["lower"],
                    "upper": spec["upper"], "selected_value": value,
                    "selected_position": (value - float(spec["lower"])) / width,
                    "q05": values.quantile(.05), "median": values.median(), "q95": values.quantile(.95),
                    "fraction_within_2pct_edge": float(
                        ((values - float(spec["lower"]) <= .02 * width)
                         | (float(spec["upper"]) - values <= .02 * width)).mean()
                    )
                })
    pd.DataFrame(parameter_rows).to_csv(OUT / "selected_candidate_parameters.csv", index=False)
    pd.DataFrame(posterior_rows).to_csv(OUT / "selected_candidate_posterior_pressure.csv", index=False)
    print(pd.DataFrame(summaries).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
