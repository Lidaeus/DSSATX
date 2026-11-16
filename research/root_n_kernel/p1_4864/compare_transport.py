"""Compare the 26SP steady run and two 24-substep transient grid runs."""

import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "n_diagnostics"))
from data import native_table

KEY = ["run", "yrdoy", "layer", "species"]
DAY = KEY[:2]
CANDIDATE = "candidate_gN_m2"


def confirm_configs(paths):
    settings = []
    for path in paths:
        config = (path / "NIntegration.nml").read_text()
        config = re.sub(r"\brnk_(?:mode|radial_cells)\s*=\s*\d+\s*,", "", config, flags=re.I)
        settings.append("".join(line.split("!", 1)[0].strip() for line in config.splitlines()))
    if len(set(settings)) != 1:
        raise ValueError("The paired cases have different physical inputs")
    for name in ("DSSBatch.v48", "SOIL.SOL", "TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"):
        if len({(path / name).read_bytes() for path in paths}) != 1:
            raise ValueError(f"Paired case input differs: {name}")
    return settings[0]


def ledger(path, mode):
    data = pd.read_csv(path / "LayerRootNUptake.csv").set_index(KEY, verify_integrity=True).sort_index()
    if set(data.transport_mode) != {mode} or set(data.shared_transport) != {1}:
        raise ValueError(f"Unexpected transport mode in {path}")
    return data


def load_water_trace(path):
    fields = ["run", "yrdoy", "layer", "event", "key", "value"]
    selected = []
    for chunk in pd.read_csv(path / "P0Trace.csv", usecols=fields, chunksize=100_000):
        selected.append(chunk.loc[chunk.event.eq("rnk_pre_extract") & chunk.key.isin(("LL", "DLAYR"))])
    return pd.concat(selected).pivot(index=KEY[:3], columns="key", values="value")


def compare_candidates(a, b, coarse, path, config):
    pair = (b[[CANDIDATE, "theta_mid", "rlv_cm_cm3", "stock_before_gN_m2", "stock_cap_gN_m2", "d_bulk_m2_d"]]
            .rename(columns={CANDIDATE: "transient"}))
    pair["steady"] = a[CANDIDATE]
    pair["transient8"] = coarse[CANDIDATE]
    pair = pair.join(load_water_trace(path), on=KEY[:3]).reset_index()
    if pair[["LL", "DLAYR"]].isna().any().any() or (pair[["LL", "DLAYR"]] <= 0).any().any():
        raise ValueError("Missing or invalid layer water metadata")

    mgmt = native_table(path / "MgmtOps.OUT").sort_values(DAY)
    increments = mgmt.groupby("run")[["IRRC", "NICM"]].diff()
    events = mgmt.loc[increments.gt(0).any(axis=1), DAY]
    event_dates = {(row.run, row.yrdoy + offset) for row in events.itertuples() for offset in range(3)}
    growth = native_table(path / "PlantGro.OUT").set_index(DAY)
    pair = pair.join(growth.DAP, on=DAY)
    if pair.DAP.isna().any():
        raise ValueError("Missing paired plant days")
    pair["management_window"] = [(r, d) in event_dates for r, d in zip(pair.run, pair.yrdoy)]
    pair["early"] = pair.DAP.le(30)
    rooted = pair.loc[pair.rlv_cm_cm3.gt(0)].drop_duplicates(KEY[:3])
    pair["low_rlv"] = pair.rlv_cm_cm3.gt(0) & pair.rlv_cm_cm3.le(rooted.rlv_cm_cm3.quantile(.25))
    pair["moisture"] = np.select(
        [pair.theta_mid.le(0.5 * pair.LL), pair.theta_mid.le(pair.LL)],
        ["extreme_dry", "dry"], default="normal",
    )
    for name, x, y in (("method", "transient", "steady"), ("grid", "transient", "transient8")):
        pair[name + "_delta"] = pair[x] - pair[y]
        pair[name + "_mean"] = (pair[x] + pair[y]) / 2
        pair[name + "_relative"] = pair[name + "_delta"] / pair[name + "_mean"].where(pair[name + "_mean"].gt(0))
    pair["beyond_grid"] = pair.method_delta.abs().gt(pair.grid_delta.abs())
    pair["large_delta"] = pair.method_relative.abs().gt(0.15) & pair.beyond_grid

    def species_values(key):
        match = re.search(key + r"=([^,]+),([^,]+)", config)
        return pair.species.map({1: float(match[1]), 2: float(match[2])})

    # Recover BD from the mass reserved by the stock floor on rows above it.
    density = 100 * (pair.stock_before_gN_m2 - pair.stock_cap_gN_m2) / (pair.DLAYR * species_values("rnk_residual"))
    density = density.where(pair.stock_cap_gN_m2.gt(0))
    density = density.fillna(density.groupby([pair.run, pair.yrdoy, pair.layer]).transform("max"))
    radius = float(re.search(r"rnk_radius=([^,]+)", config)[1])
    outer_r2 = radius**2 + 1 / (np.pi * 10_000 * pair.rlv_cm_cm3.where(pair.rlv_cm_cm3.gt(0)))
    kd = species_values("rnk_kd")
    capacity = pair.theta_mid + (density * kd).where(kd.gt(0), 0)
    pair["tau_days"] = outer_r2 * capacity / (2 * pair.d_bulk_m2_d.where(pair.d_bulk_m2_d.gt(0)))

    for name, source in (("steady", a), ("transient", b)):
        n = source.reset_index()
        pair[name + "_root_mean"] = n.c_root_mean_mgN_L.where(n.c_root_mean_mgN_L.ge(0))
        pair[name + "_mean_ratio"] = pair[name + "_root_mean"] / n.c_bulk_mean_mgN_L.where(n.c_bulk_mean_mgN_L.gt(0))
        pair[name + "_hats_share"] = n.hats_candidate_gN_m2 / (
            n.hats_candidate_gN_m2 + n.lats_candidate_gN_m2).where(n[CANDIDATE].gt(0))
    end = b.reset_index()
    pair["transient_end_ratio"] = end.c_root_mgN_L / end.c_bulk_end_mgN_L.where(end.c_bulk_end_mgN_L.gt(0))
    return pair


def summarize(pair):
    active = pair.loc[pair.method_mean.gt(0)]
    stats = []
    for context, data in (("all", pair), ("early_DAP_0_30", pair[pair.early]),
                          ("operations_day_0_2", pair[pair.management_window]), ("low_RLV_q25", pair[pair.low_rlv])):
        for (moisture, species), rows in data.groupby(["moisture", "species"]):
            group = rows.loc[rows.method_mean.gt(0)]
            weight = group.method_mean.sum()
            if not weight:
                continue
            strong = group.loc[group.large_delta]
            grid_weight = rows.grid_mean.sum()
            stats.append({
                "context": context, "moisture": moisture, "species": species, "rows": len(rows),
                "positive_rows": len(group), "share_all_active_uptake_pct": 100 * weight / active.method_mean.sum(),
                "mean_abs_method_kg_ha_d": group.method_delta.abs().mean() * 10,
                "weighted_abs_method_pct": 100 * group.method_delta.abs().sum() / weight,
                "weighted_signed_method_pct": 100 * group.method_delta.sum() / weight,
                "weighted_abs_grid_pct": 100 * rows.grid_delta.abs().sum() / grid_weight if grid_weight else None,
                "over_15pct_and_grid_rows": len(strong),
                "over_15pct_and_grid_uptake_share_pct": 100 * strong.method_mean.sum() / weight,
                "large_median_tau_days": strong.tau_days.median() if strong.tau_days.notna().any() else None,
                "large_median_steady_root_mean": strong.steady_root_mean.median() if strong.steady_root_mean.notna().any() else None,
                "large_median_transient_root_mean": strong.transient_root_mean.median() if strong.transient_root_mean.notna().any() else None,
                "large_median_transient_mean_ratio": strong.transient_mean_ratio.median() if strong.transient_mean_ratio.notna().any() else None,
                "large_median_transient_end_ratio": strong.transient_end_ratio.median() if strong.transient_end_ratio.notna().any() else None,
                "large_median_hats_delta_pp": 100 * (strong.transient_hats_share - strong.steady_hats_share).median()
                    if (strong.transient_hats_share - strong.steady_hats_share).notna().any() else None,
            })
    return pd.DataFrame(stats)


def whole_crop(a, b, paths):
    uptake = pd.concat([frame.groupby(["run", "species"]).deducted_gN_m2.sum() * 10
                        for frame in (a, b)], axis=1, keys=["steady", "transient"])
    uptake["transient_minus_steady_pct"] = 100 * (uptake.transient - uptake.steady) / uptake.steady
    output = {}
    for fn, fields in (("PlantGro.OUT", ("LAID", "CWAD", "LN%D")), ("FreshWt.OUT", ("CHFPW",))):
        sides = [native_table(path / fn).set_index(DAY, verify_integrity=True).sort_index() for path in paths]
        for field in fields:
            x, y = (side[field] for side in sides)
            if not x.index.equals(y.index):
                raise ValueError(f"Different whole-plant dates in {fn}")
            final = pd.concat([x, y], axis=1).groupby("run").tail(1)
            output[field] = {
                "mean_absolute_trajectory_difference": float((y - x).abs().mean()),
                "trajectory_normalized_mae_pct": float(100 * (y - x).abs().sum() / x.abs().sum()),
                "season_end_means": list(final.mean()),
                "max_treatment_end_abs_difference": float((final.iloc[:, 0] - final.iloc[:, 1]).abs().max()),
            }
    return uptake, output


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("steady", "transient8", "transient16", "out"):
        cli.add_argument(f"--{name}", required=True, type=Path)
    args = cli.parse_args()
    config = confirm_configs((args.steady, args.transient8, args.transient16))
    a, coarse, b = (ledger(path, mode) for path, mode in
                    ((args.steady, 1), (args.transient8, 2), (args.transient16, 2)))
    if not a.index.equals(b.index) or not coarse.index.equals(b.index):
        raise ValueError("The three ledgers have different layer/day/species keys")
    pair = compare_candidates(a, b, coarse, args.transient16, config)
    stats = summarize(pair)
    uptake, growth = whole_crop(a, b, (args.steady, args.transient16))
    args.out.mkdir(parents=True, exist_ok=False)
    stats.to_csv(args.out / "group_comparison.csv", index=False)
    pair.loc[pair.large_delta].to_csv(args.out / "large_layer_day_differences.csv", index=False)
    uptake.to_csv(args.out / "treatment_soil_uptake.csv")
    (args.out / "whole_crop.json").write_text(json.dumps(growth, indent=2) + "\n")


if __name__ == "__main__":
    main()
