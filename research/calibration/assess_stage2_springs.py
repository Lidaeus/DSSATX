"""Audit a selected Stage 2 ensemble member against both seasons' native outputs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from f5_26sp import audit, digest, native_table, run_inputs
from forward import native_value
from prepare_stage2_springs import DATASETS


OUTPUTS = ("FreshWt.OUT", "PlantGro.OUT", "PlantN.OUT")
FINAL = "CHFPW_terminal"
JUNE29 = 2026180
PHASE_B_FIELDS = ("lux_veg_mode", "lux_psi_threshold", "lux_hill_k", "lux_xfrt_drop")


def native_outputs(case):
    return {name: native_table(case / name, allow_numeric_overflow=True).sort_values("yrdoy") for name in OUTPUTS}


def pair_outputs(observed, tables):
    values = []
    for row in observed.itertuples(index=False):
        sim = native_value(tables[row.file], row, row.treatment)
        if pd.notna(row.reference_treatment):
            sim -= native_value(tables[row.file], row, row.reference_treatment)
        values.append(sim)
    return observed.assign(simulated=values)


def validate_stage_b_freeze(off, on):
    fields = "|".join(PHASE_B_FIELDS)
    pattern = rf"\b(?:{fields})[ \t]*=[ \t]*[-+.\dEeDd]+[ \t]*,?"

    def fixed(config):
        return [line.strip() for line in re.sub(pattern, "", config.read_text()).splitlines() if line.strip()]

    if fixed(off) != fixed(on):
        raise ValueError("A parameter outside the three luxury controls changed in Stage 2B")


def assess_season(engine, stage, out, config, dataset, observations, training, off, cards=()):
    case = out / dataset
    run_inputs(engine, stage / "inputs" / dataset, case, config, cards)
    tables = native_outputs(case)
    metadata = observations[["treatment", "treatment_label", "nitrogen_level"]].drop_duplicates().set_index("treatment")
    for table in tables.values():
        if (set(table.treatment) != set(metadata.index)
                or not table.treatment.map(metadata.treatment_label).eq(table.treatment_label_native).all()):
            raise ValueError(f"Treatment mappings disagree for {DATASETS[dataset][0]}")

    paired = pair_outputs(observations, tables)
    fresh = paired.loc[paired.column.eq("CHFPW")]
    terminal = fresh.sort_values("yrdoy").groupby("treatment").tail(1).copy()
    data = tables["FreshWt.OUT"].merge(terminal[["treatment", "yrdoy"]], on="treatment", suffixes=("", "_last"))
    late = data.loc[data.yrdoy.ge(data.yrdoy_last), ["treatment", "CHFPW"]]
    if late.groupby("treatment").CHFPW.nunique().ne(1).any():
        raise ValueError(f"Simulated fresh harvest after the last recorded harvest for {DATASETS[dataset][0]}")
    terminal["column"] = FINAL
    paired = pd.concat([paired, terminal], ignore_index=True)

    comparison = pair_outputs(training.drop(columns=["simulated", "phi_contribution"]), tables)
    np.testing.assert_allclose(comparison.simulated, training.simulated, atol=1e-10, rtol=0)
    budgets = audit(case, len(metadata))
    daily = None
    if off:
        baseline = native_outputs(off / dataset)
        ids = metadata.index[metadata.nitrogen_level.isin(("N0", "N1"))]
        daily = {}
        for filename in OUTPUTS:
            left, right = [group[filename].loc[group[filename].treatment.isin(ids)]
                           .set_index(["treatment", "yrdoy"]).sort_index() for group in (baseline, tables)]
            if not left.index.equals(right.index):
                raise ValueError("Low-N comparison has different native day coverage")
            daily[filename] = left.equals(right)
            if filename == "FreshWt.OUT":
                daily["max_daily_fresh_difference_kg_ha"] = float(right.CHFPW.sub(left.CHFPW).abs().max())
    stages = pd.concat([tables[key].loc[tables[key].yrdoy.eq(JUNE29)].set_index("treatment")[cols]
                       for key, cols in (("PlantN.OUT", ["LN%D", "SN%D"]),
                                         ("PlantGro.OUT", ["LAID", "LWAD", "SWAD"]))], axis=1)
    stages = terminal.set_index("treatment").join(stages)
    if dataset == "s26":
        stage_records = {}
        for water in ("W2", "W3"):
            n = stages.loc[stages.water_level.eq(water)].set_index("nitrogen_level")
            n0, n1, n2, n3 = [n.loc[level] for level in ("N0", "N1", "N2", "N3")]
            gain = float((n2.simulated - n1.simulated) / 1000)
            leaf = float(n2["LN%D"] - n1["LN%D"])
            stem = float(n2["SN%D"] - n1["SN%D"])
            lai = [float(n1.LAID - n0.LAID), float(n2.LAID - n1.LAID)]
            change = float((n3.simulated - n2.simulated) / 1000)
            monotone = bool(n0.simulated < n1.simulated < n2.simulated)
            leaf_high = float(n3["LN%D"] - n2["LN%D"])
            leaf_dm, stem_dm = (float(n3[key] - n2[key]) for key in ("LWAD", "SWAD"))
            stage_records[water] = {"N0_lt_N1_lt_N2": monotone, "N2_N1_t_ha": gain, "N3_N2_t_ha": change,
                                    "N2_N1_leaf_N_pp": leaf, "N2_N1_stem_N_pp": stem, "LAI_steps": lai,
                                    "N3_N2_leaf_N_pp": leaf_high, "N3_N2_LWAD_kg_ha": leaf_dm,
                                    "N3_N2_SWAD_kg_ha": stem_dm,
                                    "legacy_2a_agronomic": monotone and 3 <= gain <= 6 and .25-1e-12 <= leaf <= .35+1e-12
                                    and stem > 0 and min(lai) > 0,
                                    "legacy_2b_agronomic": monotone and -4 <= change <= -1.8
                                    and .25-1e-12 <= leaf <= .35+1e-12 and leaf_high >= 0 and min(leaf_dm, stem_dm) > 0}
    else:
        stage_records = None
    return paired, {"native_audit": budgets, "low_n_daily_comparison": daily, "legacy_26sp_field_checks": stage_records}


def fit_metrics(pairs):
    output = []
    for (dataset, column), p in pairs.groupby(["dataset", "column"]):
        factor = 1000 if column in ("CHFPW", FINAL) else 1
        observed, simulated = p.observed / factor, p.simulated / factor
        errors = simulated - observed
        rmse = math.sqrt(errors.pow(2).mean())
        output.append({"dataset": dataset, "column": column, "n": len(p), "r2": observed.corr(simulated)**2,
                       "nrmse_percent": 100 * rmse / observed.mean(),
                       "nse": 1 - errors.pow(2).sum() / (observed - observed.mean()).pow(2).sum(),
                       "rmse": rmse, "bias": errors.mean()})
    return pd.DataFrame(output)


def gradients(terminal):
    output = []
    for (dataset, water), frame in terminal.groupby(["dataset", "water_level"]):
        n = frame.set_index("nitrogen_level")
        for low, high in (("N0", "N1"), ("N1", "N2"), ("N2", "N3")):
            quantities = (n.loc[high, ["observed", "simulated"]] - n.loc[low, ["observed", "simulated"]]) / 1000
            output.append({"dataset": dataset, "water": water, "contrast": f"{high}-{low}",
                           "observed_t_ha": quantities.observed, "simulated_t_ha": quantities.simulated})
    return pd.DataFrame(output)


def run(engine, stage, replay, out, off):
    source = json.loads((stage / "stage_receipt.json").read_text())
    prior = json.loads((replay / "receipt.json").read_text())
    config = replay / "configs/NIntegration.nml"
    workload = pd.read_csv(stage / "all_observations.csv")
    targets = pd.read_csv(replay / "comparison.csv")
    if (digest(engine) != source["engine_sha256"] or digest(engine) != prior["engine_sha256"]
            or digest(config) != prior["rendered_config_sha256"][config.name]):
        raise ValueError("Selected configuration or engine differs from the joint IES replay")
    card_names = {"TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"}
    cards = [config.parent / name for name in sorted(card_names & prior["rendered_config_sha256"].keys())]
    for card in cards:
        if digest(card) != prior["rendered_config_sha256"][card.name]:
            raise ValueError(f"Selected crop card changed: {card.name}")
    for name, checksum in source["files_sha256"].items():
        if digest(stage / name) != checksum:
            raise ValueError(f"Joint assessment input changed: {name}")
    if off:
        validate_stage_b_freeze(off / "s26" / "NIntegration.nml", config)
    out.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=2) as threads:
        runs = {dataset: threads.submit(assess_season, engine, stage, out, config, dataset,
                                       workload.loc[workload.dataset.eq(dataset)],
                                       targets.loc[targets.dataset.eq(dataset)], off, cards) for dataset in DATASETS}
        cases = {dataset: future.result() for dataset, future in runs.items()}
    pairs = pd.concat([record[0] for record in cases.values()], ignore_index=True)
    pairs.to_csv(out / "all_matched.csv", index=False)
    fit_metrics(pairs).to_csv(out / "fit_metrics.csv", index=False)
    terminal = pairs.loc[pairs.column.eq(FINAL)]
    terminal.assign(observed_t_ha=terminal.observed/1000, simulated_t_ha=terminal.simulated/1000)[
        ["dataset", "treatment", "treatment_label", "yrdoy", "observed_t_ha", "simulated_t_ha"]].sort_values(
            ["dataset", "treatment_label"]).to_csv(out / "terminal_yields.csv", index=False)
    gradients(terminal).to_csv(out / "yield_gradients.csv", index=False)
    contributions = targets.groupby(["dataset", "group"]).phi_contribution.agg(["size", "sum"]).reset_index()
    contributions.rename(columns={"size": "n", "sum": "phi"}).to_csv(out / "phi_by_group.csv", index=False)
    (out / "native_receipt.json").write_text(json.dumps({"engine_sha256": digest(engine),
        "selected_config_sha256": digest(config), "ies": prior, "cases": {key: val[1] for key, val in cases.items()}},
        indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "stage", "replay", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--off", type=Path)
    run(**{key: path.resolve() if path else None for key, path in vars(parser.parse_args()).items()})
