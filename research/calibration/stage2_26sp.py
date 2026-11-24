"""Replay and evaluate the F6 stage-2A and substrate-driven stage-2B trials."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np
import pandas as pd

from f5_26sp import IDENTITY, JUNE_29, assess_case, digest, model_output, native_table, run_case

CASES = ("control", "f5", "f6", "f5_hill", "f6_hill")
NATIVE_TRAJECTORIES = ("PlantGro.OUT", "PlantN.OUT", "FreshWt.OUT")
SHOOT_METRICS = ("LAID", "LWAD", "SWAD", "HIAD", "WSPD", "WSGD")
P0_SIGNALS = {
    ("rnk_tissue_target", "fill"): "day_substrate_fill",
    ("rnk_psi_feedback", "psi"): "day_psi",
    ("lux_shoot_state", "xfrt_factor"): "xfrt_factor",
    ("lux_shoot_substrate", "fill"): "mode2_fill",
    ("lux_demand", "C_rep_cap"): "lux_demand_cap",
    ("lux_pods", "C_rep_cap"): "lux_pods_cap",
}
FILL_THRESHOLD = .76


def read_signals(case):
    series = []
    keys = ("event", "key")
    for block in pd.read_csv(case / "P0Trace.csv",
                             usecols=["run", "yrdoy", *keys, "value"], chunksize=200_000):
        index = pd.MultiIndex.from_frame(block[list(keys)])
        series.append(block.loc[index.isin(P0_SIGNALS)])
    signals = pd.concat(series, ignore_index=True)
    signals["metric"] = [P0_SIGNALS[key] for key in zip(signals.event, signals.key)]
    return signals.pivot(index=["run", "yrdoy"], columns="metric", values="value")


def anthesis_dates(case):
    summary = (case / "Summary.OUT").read_text().splitlines()
    column = next(line for line in summary if line.startswith("@")).split().index("ADAT") - 1
    return {int(parts[0]): int(parts[column]) for line in summary if (parts := line.split()) and parts[0].isdigit()}


def growth_diagnostics(stage, case, results):
    growth = native_table(case / "PlantGro.OUT", allow_numeric_overflow=True)
    by_run = growth.set_index(["run", "yrdoy"])
    cash = pd.read_csv(case / "PlantCCash.csv", usecols=["run", "yrdoy", "maintenance"]).set_index(["run", "yrdoy"])
    signals = read_signals(case)
    if "mode2_fill" in signals:
        np.testing.assert_array_equal(signals.mode2_fill, signals.day_substrate_fill)
    defaults = {"xfrt_factor": 1., "lux_demand_cap": 0., "lux_pods_cap": 0.}
    for name, default in defaults.items():
        signals[name] = signals[name].fillna(default) if name in signals else default
    daily = signals.join(by_run[list(SHOOT_METRICS)]).join(cash).drop(columns="mode2_fill", errors="ignore")
    daily["SWFAC"] = 1 - daily.WSPD
    daily["TURFAC"] = 1 - daily.WSGD
    daily = daily.reset_index()
    flowers = anthesis_dates(case)
    daily["reproductive"] = daily.yrdoy.ge(daily.run.map(flowers))
    metadata = pd.read_csv(stage / "treatment_metadata.csv")
    daily = daily.merge(metadata[["treatment", "water_level", "nitrogen_level"]],
                        left_on="run", right_on="treatment", validate="many_to_one")
    daily.to_csv(case / "daily_luxury_diagnostics.csv", index=False)
    for (water, nitrogen), rows in daily.groupby(["water_level", "nitrogen_level"]):
        values = results["groups"][water][nitrogen]
        june = rows.loc[rows.yrdoy.eq(JUNE_29)].iloc[0]
        for col in ("LAID", "LWAD", "SWAD"):
            values[f"{col}_june29"] = float(june[col])
        repro = rows.loc[rows.reproductive]
        earlier = rows.loc[~rows.reproductive]
        if not np.isfinite(repro[list(SHOOT_METRICS) + ["day_substrate_fill", "SWFAC", "TURFAC"]]).all().all():
            raise ValueError(f"Missing reproductive diagnostics for {case.name}/{water}/{nitrogen}")
        higher_fill = repro.day_substrate_fill.gt(FILL_THRESHOLD)
        xfrt_active = repro.xfrt_factor.lt(1)
        water_limited = repro.TURFAC.lt(.99)
        values.update({
            "HIAD_last": float(rows.HIAD.iloc[-1]),
            "maintenance_gCH2O_m2": float(rows.maintenance.sum()),
            "anthesis_yrdoy": int(flowers[int(june.run)]),
            "reproductive_days": len(repro),
            "fill_mean": float(repro.day_substrate_fill.mean()),
            "fill_p90": float(repro.day_substrate_fill.quantile(.9)),
            "fill_max": float(repro.day_substrate_fill.max()),
            "fill_gt_076_days": int(higher_fill.sum()),
            "fill_gt_080_days": int(repro.day_substrate_fill.gt(.8).sum()),
            "psi_gt_085_days": int(repro.day_psi.gt(.85).sum()),
            "xfrt_reduced_days": int(xfrt_active.sum()),
            "xfrt_reduced_days_before_anthesis": int(earlier.xfrt_factor.lt(1).sum()),
            "lux_demand_cap_positive_days_before_anthesis": int(earlier.lux_demand_cap.gt(0).sum()),
            "lux_pods_cap_positive_days_before_anthesis": int(earlier.lux_pods_cap.gt(0).sum()),
            "xfrt_factor_mean": float(repro.xfrt_factor.mean()),
            "xfrt_factor_min": float(repro.xfrt_factor.min()),
            "SWFAC_mean": float(repro.SWFAC.mean()), "TURFAC_mean": float(repro.TURFAC.mean()),
            "SWFAC_min": float(repro.SWFAC.min()), "TURFAC_min": float(repro.TURFAC.min()),
            "TURFAC_lt_099_days": int(water_limited.sum()),
            "high_fill_and_TURFAC_lt_099_days": int((higher_fill & water_limited).sum()),
            "xfrt_and_TURFAC_lt_099_days": int((xfrt_active & water_limited).sum()),
        })
    holdouts = pd.read_csv(case / "paired_holdout.csv")
    holdouts["error"] = holdouts.simulated - holdouts.observed
    results["holdouts"] = {int(treatment): {group: float(np.sqrt(rows.error.pow(2).mean()))
                                          for group, rows in targets.groupby("group")}
                           for treatment, targets in holdouts.groupby("treatment")}
    return results


def assess_trial(engine, stage, case, config):
    run_case(engine, stage, case, config)
    return growth_diagnostics(stage, case, assess_case(stage, case))


def contrasts(groups, water):
    n0, n1, n2, n3 = (groups[water][f"N{level}"] for level in range(4))
    return {
        "N0_lt_N1_lt_N2": n0["fresh_kg_ha"] < n1["fresh_kg_ha"] < n2["fresh_kg_ha"],
        "N2_minus_N1_fresh_t_ha": (n2["fresh_kg_ha"] - n1["fresh_kg_ha"]) / 1000,
        "N3_minus_N2_fresh_t_ha": (n3["fresh_kg_ha"] - n2["fresh_kg_ha"]) / 1000,
        "N2_minus_N1_leaf_N_pp": n2["leaf_n_june29_pct"] - n1["leaf_n_june29_pct"],
        "N2_minus_N1_stem_N_pp": n2["stem_n_june29_pct"] - n1["stem_n_june29_pct"],
        "N3_minus_N2_leaf_N_pp": n3["leaf_n_june29_pct"] - n2["leaf_n_june29_pct"],
        "LAID_june29_steps": [n1["LAID_june29"] - n0["LAID_june29"], n2["LAID_june29"] - n1["LAID_june29"]],
        "N3_minus_N2_LWAD_june29": n3["LWAD_june29"] - n2["LWAD_june29"],
        "N3_minus_N2_SWAD_june29": n3["SWAD_june29"] - n2["SWAD_june29"],
        "N3_minus_N2_actual_uptake": n3["uptake_kgN_ha"] - n2["uptake_kgN_ha"],
        "N3_minus_N2_maintenance": n3["maintenance_gCH2O_m2"] - n2["maintenance_gCH2O_m2"],
        "N3_minus_N2_HIAD_last": n3["HIAD_last"] - n2["HIAD_last"],
    }


def stage2a(result, control):
    waters = {}
    for water in ("W2", "W3"):
        row = contrasts(result["groups"], water)
        row["pass"] = (row["N0_lt_N1_lt_N2"] and 3 <= row["N2_minus_N1_fresh_t_ha"] <= 6
                       and .25 - 1e-12 <= row["N2_minus_N1_leaf_N_pp"] <= .35 + 1e-12
                       and row["N2_minus_N1_stem_N_pp"] > 0 and min(row["LAID_june29_steps"]) > 0)
        waters[water] = row
    phi_limit = control["phi"] * 1.10
    holds = {str(key): result["holdouts"][str(key)]["fresh"] <= control["holdouts"][str(key)]["fresh"]
             for key in (7, 10)}
    return {"pass": bool(result["phi"] <= phi_limit and all(holds.values()) and all(row["pass"] for row in waters.values())),
            "phi": result["phi"], "phi_limit": phi_limit, "holdouts_fresh_RMSE_at_most_control": holds, "waters": waters}


def low_n_trajectories(stage, off, on):
    metadata = pd.read_csv(stage / "treatment_metadata.csv")
    low = metadata.loc[metadata.nitrogen_level.isin(["N0", "N1"]), "treatment"]
    same = {}
    for name in NATIVE_TRAJECTORIES:
        a, b = (native_table(case / name, allow_numeric_overflow=True).set_index(["treatment", "yrdoy"]).loc[low]
                for case in (off, on))
        same[name] = a.equals(b)
        if name == "FreshWt.OUT":
            if not a.index.equals(b.index):
                raise ValueError("Mismatched low-N fresh trajectory dates")
            daily_fresh_delta = float((a.CHFPW - b.CHFPW).abs().max()) / 1000
    return {"same_daily_native_values": same, "max_daily_fresh_abs_change_t_ha": daily_fresh_delta}


def stage2b(stage, off, on, result):
    low = low_n_trajectories(stage, off, on)
    waters = {}
    for water in ("W2", "W3"):
        row = contrasts(result["groups"], water)
        row["pass"] = (row["N0_lt_N1_lt_N2"] and -4 <= row["N3_minus_N2_fresh_t_ha"] <= -1.8
                       and .25 - 1e-12 <= row["N2_minus_N1_leaf_N_pp"] <= .35 + 1e-12
                       and row["N3_minus_N2_leaf_N_pp"] >= 0 and row["N3_minus_N2_LWAD_june29"] > 0
                       and row["N3_minus_N2_SWAD_june29"] > 0)
        waters[water] = row
    return {"meets_field_pattern": bool(all(row["pass"] for row in waters.values())
                                       and all(low["same_daily_native_values"].values())
                                       and low["max_daily_fresh_abs_change_t_ha"] < .2),
            "waters": waters, "low_N": low}


def json_values(value):
    # Numeric native-table results can contain NumPy scalar types.
    return json.loads(json.dumps(value, default=lambda x: x.item(), allow_nan=False))


def write_results(out, receipt):
    receipt = json_values(receipt)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    rows = [dict(case=case, water=water, nitrogen=nitrogen, **values)
            for case, result in receipt["cases"].items()
            for water, group in result["groups"].items() for nitrogen, values in group.items()]
    pd.DataFrame(rows).to_csv(out / "treatment_summary.csv", index=False)


def compare(engine, stage, out, reference):
    out.mkdir(parents=True)
    with ProcessPoolExecutor(max_workers=len(CASES)) as pool:
        jobs = {name: pool.submit(assess_trial, engine, stage, out / name, stage / f"{name}.nml")
                for name in CASES}
        cases = {name: job.result() for name, job in jobs.items()}
    parity = {name: model_output(out / "control" / name) == model_output(reference / name)
              for name in sorted(IDENTITY | {"P0Trace.csv"})}
    if not all(parity.values()):
        raise ValueError(f"Off-mode regression failed: {parity}")
    cases = json_values(cases)
    receipt = {
        "engine_sha256": digest(engine), "disabled_parity": parity, "cases": cases,
        "stage_2a": {name: stage2a(cases[name], cases["control"]) for name in ("f5", "f6")},
        "stage_2b_exploratory": {name: stage2b(stage, out / name, out / f"{name}_hill", cases[f"{name}_hill"])
                                 for name in ("f5", "f6")},
    }
    write_results(out, receipt)


def posterior(engine, stage, out, reference, config):
    out.mkdir(parents=True)
    prior = json.loads(reference.read_text())
    if digest(engine) != prior["engine_sha256"]:
        raise ValueError("The paired run and posterior must use the same engine")
    result = json_values(assess_trial(engine, stage, out / "posterior", config))
    write_results(out, {"engine_sha256": digest(engine), "cases": {"posterior": result},
                        "stage_2a": stage2a(result, prior["cases"]["control"])})


def luxury(engine, stage, out, reference, config, baseline):
    prior = json.loads(reference.read_text())
    if prior["stage_2a"]["pass"] is not True:
        raise ValueError("Stage 2B requires a complete native stage-2A pass")
    if (digest(engine) != prior["engine_sha256"]
            or digest(baseline / "NIntegration.nml") != prior["cases"]["posterior"]["config_sha256"]):
        raise ValueError("The stage-2B engine and off-mode baseline must match the passing 2A replay")
    out.mkdir(parents=True)
    on = out / "hill"
    result = json_values(assess_trial(engine, stage, on, config))
    write_results(out, {"engine_sha256": digest(engine), "cases": {"hill": result},
                        "stage_2a_reference_sha256": digest(reference),
                        "stage_2b": stage2b(stage, baseline, on, result)})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("compare", "posterior", "luxury"))
    for name in ("engine", "stage", "out", "reference"):
        ap.add_argument(f"--{name}", type=Path, required=True)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--baseline", type=Path)
    args = ap.parse_args()
    engine, stage, out, reference = (getattr(args, name).resolve() for name in ("engine", "stage", "out", "reference"))
    if args.action == "compare":
        compare(engine, stage, out, reference)
    elif args.config is None:
        ap.error(f"{args.action} requires --config")
    elif args.action == "posterior":
        posterior(engine, stage, out, reference, args.config.resolve())
    elif args.baseline is None:
        ap.error("luxury requires --baseline from the passed 2A native replay")
    else:
        luxury(engine, stage, out, reference, args.config.resolve(), args.baseline.resolve())


if __name__ == "__main__":
    main()
