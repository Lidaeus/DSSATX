"""Compare N2-N1 yield contrasts and their carbon budgets in the two spring trials."""

import argparse
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from assess_stage2_springs import native_outputs, pair_outputs
from prepare_stage2_springs import DATASETS


TRACE = {
    ("cg_seed", "PGAVL"): "C_before_assim",
    ("cg_mobil", "PGAVL"): "C_after_remob",
    ("cg_mobil", "RPRO"): "RPRO",
    ("cg_mobil", "NMINEA"): "planned_remob_N",
    ("cg_fix", "PGAVL"): "C_before_PODS",
    ("cg_repro", "CGRSD"): "CGRSD",
    ("cg_repro", "CGRSH"): "CGRSH",
}
KEYS = ["run", "yrdoy"]


def trace_budget(path):
    pieces = []
    for frame in pd.read_csv(path, usecols=[*KEYS, "event", "key", "value"], chunksize=200_000):
        pairs = pd.MultiIndex.from_frame(frame[["event", "key"]])
        subset = frame.loc[pairs.isin(TRACE)].copy()
        subset["field"] = [TRACE[key] for key in zip(subset.event, subset.key)]
        pieces.append(subset)
    result = pd.concat(pieces).pivot(index=KEYS, columns="field", values="value")
    return result


def carbon_chain(audit, observed):
    frames = []
    for dataset in DATASETS:
        case = audit / dataset
        config = (case / "NIntegration.nml").read_text()
        if not re.search(r"(?m)^\s*common_acceptance\s*=\s*0\b", config):
            raise ValueError("CG_FIX.PGAVL represents pre-PODS carbon only with common_acceptance off")
        tables = native_outputs(case)
        runs = tables["PlantGro.OUT"][["run", "treatment"]].drop_duplicates()
        cash = pd.read_csv(case / "PlantCCash.csv", usecols=[*KEYS, "PG", "actual_C_mined", "maintenance", "N_assim",
                         "N_resynthesis", "fruit_growth", "veg_growth"]).set_index(KEYS, verify_integrity=True)
        nitrogen = pd.read_csv(case / "PlantNIntegration.csv", usecols=[*KEYS, "U_NO3", "U_NH4", "A_NO3", "A_NH4"])
        nitrogen["uptake_N"] = nitrogen.U_NO3 + nitrogen.U_NH4
        nitrogen["assim_N"] = nitrogen.A_NO3 + nitrogen.A_NH4
        nitrogen = nitrogen.set_index(KEYS, verify_integrity=True)[["uptake_N", "assim_N"]]
        daily = cash.join(nitrogen, validate="one_to_one").join(trace_budget(case / "P0Trace.csv"), validate="one_to_one")
        if daily.isna().any().any():
            raise ValueError(f"Missing carbon or nitrogen accounting events in {case}")
        np.testing.assert_allclose(daily.CGRSD + daily.CGRSH, daily.fruit_growth, atol=2e-6, rtol=2e-7)
        # Current mode makes the assimilation and remobilization reservations
        # between CG_SEED and CG_MOBIL. The cash ledger records their settlement.
        daily["N_assim_before_PODS"] = (daily.C_before_assim - daily.C_after_remob
                                      - daily.planned_remob_N * daily.RPRO / .16).clip(lower=0)
        np.testing.assert_allclose(daily.C_before_PODS, daily.C_after_remob, atol=2e-6, rtol=2e-7)
        fresh = observed.loc[observed.dataset.eq(dataset) & observed.column.eq("CHFPW")]
        fresh = fresh.loc[fresh.nitrogen_level.isin(["N1", "N2"])]
        meta = fresh[["treatment", "water_level", "nitrogen_level"]].drop_duplicates()
        daily = daily.reset_index().merge(runs, on="run", validate="many_to_one").merge(
            meta, on="treatment", validate="many_to_one")
        for water, field in fresh.groupby("water_level"):
            days = sorted(field.yrdoy.unique())
            subset = daily.loc[daily.water_level.eq(water)]
            for window, lower, upper in [("season", 0, days[-1]), ("last_harvest_interval", days[-2], days[-1])]:
                totals = subset.loc[subset.yrdoy.gt(lower) & subset.yrdoy.le(upper)].groupby("nitrogen_level").sum(numeric_only=True)
                columns = cash.columns.tolist() + ["uptake_N", "assim_N", "C_before_PODS", "N_assim_before_PODS"]
                delta = (totals.loc["N2", columns] - totals.loc["N1", columns]).to_dict()
                frames.append(dict(dataset=dataset, water=water, window=window, after_yrdoy=lower, through_yrdoy=upper, **delta))
    return pd.DataFrame(frames)


def score_cases(ies, baseline, targets, observed):
    datasets = []
    for dataset in DATASETS:
        datasets.append(pair_outputs(targets.loc[targets.dataset.eq(dataset)], native_outputs(baseline / dataset)))
    base = pd.concat(datasets).set_index("name", verify_integrity=True)
    weights = targets.set_index("name", verify_integrity=True)
    base = base.reindex(weights.index)
    reported = pd.read_csv(ies / "mechanism.phi.actual.csv").set_index("iteration")
    delta = weights.loc[weights.group.eq("delta_n21_fresh")]
    terminal = delta.loc[delta.yrdoy.eq(delta.groupby("dataset").yrdoy.transform("max"))]
    if len(terminal) != 5 or not terminal.observed.gt(0).all():
        raise ValueError("The directional screen expects five positive observed terminal differences")
    metadata = observed[["dataset", "water_level", "nitrogen_level", "treatment"]].drop_duplicates()
    treatments = metadata.set_index(["dataset", "water_level", "nitrogen_level"], verify_integrity=True).treatment
    keys = ["dataset", "column", "treatment", "yrdoy"]
    absolute_names = weights.loc[weights.reference_treatment.isna()].reset_index().set_index(keys).name

    def metrics(predicted):
        phi = predicted.sub(weights.observed, axis=0).mul(weights.weight, axis=0).pow(2)
        difference = predicted.loc[terminal.index]
        directions_low = pd.Series(0, index=predicted.columns)
        stage_checks = pd.Series(0, index=predicted.columns)
        for name, row in terminal.iterrows():
            group = metadata.loc[metadata.dataset.eq(row.dataset) & metadata.treatment.eq(row.treatment)]
            water = group.water_level.item()
            ids = [treatments.loc[(row.dataset, water, level)] for level in ("N0", "N1", "N2")]
            n0, n1, n2 = ids
            y0, y1 = [predicted.loc[absolute_names.loc[(row.dataset, "CHFPW", t, row.yrdoy)]] for t in (n0, n1)]
            directions_low += y1.gt(y0).astype(int)
            if row.dataset == "s26" and water in ("W2", "W3"):
                y_step = predicted.loc[name] / 1000
                l1, l2 = [predicted.loc[absolute_names.loc[("s26", "LN%D", t, 2026180)]] for t in (n1, n2)]
                a0, a1, a2 = [predicted.loc[absolute_names.loc[("s26", "LAID", t, 2026180)]] for t in ids]
                good = (y1.gt(y0) & y_step.between(3, 6) & (l2-l1).between(.25-1e-12, .35+1e-12)
                        & a1.gt(a0) & a2.gt(a1))
                stage_checks += good.astype(int)
        return pd.DataFrame({"phi": phi.sum(axis=0), "absolute_phi": phi.loc[weights.reference_treatment.isna()].sum(axis=0),
                             "contrast_phi": phi.loc[delta.index].sum(axis=0),
                             "terminal_rmse_t_ha": difference.sub(terminal.observed, axis=0).pow(2).mean(axis=0)**.5/1000,
                             "positive_terminal_pairs": difference.gt(0).sum(axis=0),
                             "positive_n10_pairs": directions_low, "screened_legacy_26sp_waters": stage_checks})

    output = [metrics(base[["simulated"]]).reset_index(drop=True).assign(iteration=-1, member="baseline")]
    for iteration in reported.index:
        observations = pd.read_csv(ies / f"mechanism.{iteration}.obs.csv", index_col=0)
        observations.index = observations.index.astype(str).str.lower()
        available = observations.T.reindex(weights.index)
        valid = np.isfinite(available).all(axis=0)
        scores = metrics(available.loc[:, valid]).rename_axis("member").reset_index()
        expected = reported.loc[iteration].rename(index=str.lower).reindex(scores.member).to_numpy(dtype=float)
        np.testing.assert_allclose(scores.phi, expected, atol=1e-4, rtol=1e-5)
        output.append(scores.assign(iteration=iteration))
    return pd.concat(output, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("suite", "baseline", "out"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads((args.suite / "stage/stage_receipt.json").read_text())
    if not receipt.get("n21_fresh_contrasts"):
        raise ValueError("Use a 2A suite with N2-N1 contrast targets")
    root = args.suite
    args.out.mkdir(parents=True, exist_ok=True)
    target = pd.read_csv(root / "stage/observations.csv")
    obs = pd.read_csv(root / "stage/all_observations.csv")
    score_cases(root / "ies", args.baseline, target, obs).to_csv(args.out / "ensemble_direction_screen.csv", index=False)
    output = [carbon_chain(audit, obs).assign(case=label) for label, audit in
              [("previous_2a", args.baseline), ("n21_2a", root / "audit")]]
    pd.concat(output, ignore_index=True).to_csv(args.out / "carbon_chain_n2_minus_n1.csv", index=False)


if __name__ == "__main__":
    main()
