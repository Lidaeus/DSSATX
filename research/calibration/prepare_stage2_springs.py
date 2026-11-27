"""Prepare 25SP + 26SP shared-parameter Stage 2A and Stage 2B calibrations."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from f5_26sp import digest
from prepare_26sp_signal import TARGETS, dated, replace_assignment
from prepare_stage2b_26sp import BOUNDS
from forward import render_template


DATASETS = {"s25": ("25SP", "XXQL2501", 8), "s26": ("26SP", "XXQL2601", 12)}
TARGET_COLUMNS = ["name", "dataset", "file", "column", "treatment", "reference_treatment",
                  "yrdoy", "observed", "weight", "group", "sample_sd_or_scale", "preflight_only"]
RESULTS = Path(__file__).resolve().parent / "results"


def observations(bundle, dataset):
    season, excode, count = DATASETS[dataset]
    manifest_path = bundle / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["season"] != season:
        raise ValueError(f"Expected a {season} experiment bundle")
    for entry in manifest["files"]:
        if digest(bundle / entry["name"]) != entry["sha256"]:
            raise ValueError(f"Bundle file changed: {entry['name']}")
    meta = pd.read_csv(bundle / "treatment_metadata.csv")
    if len(meta) != count or meta.treatment.duplicated().any() or meta.treatment_label.duplicated().any():
        raise ValueError(f"Expected {count} distinct treatment records for {season}")
    uncertain = pd.read_csv(bundle / "observation_uncertainty.csv")
    rows = uncertain.loc[uncertain.season_id.eq(season) & uncertain.quality_flag.eq("ok")
                         & uncertain.variable.isin(TARGETS), ["trno", "date", "variable", "value", "raw_sd"]].copy()
    rows = rows.rename(columns={"trno": "treatment", "variable": "column", "value": "observed"})
    rows["file"] = rows.column.map({key: v[0] for key, v in TARGETS.items()})
    rows["group"] = rows.column.map({key: v[1] for key, v in TARGETS.items()})
    rows["sample_sd_or_scale"] = np.maximum.reduce([rows.raw_sd.fillna(0).to_numpy(),
        .05 * rows.observed.to_numpy(), rows.column.map({key: v[2] for key, v in TARGETS.items()}).to_numpy()])
    filet = pd.read_csv(bundle / "FileT_values.csv").rename(columns={"TRNO": "treatment", "DATE": "yrdoy"})
    filet.yrdoy += 2000000
    dates = rows.date.map(dated)
    expected = filet.melt(id_vars=["treatment", "yrdoy"], value_vars=list(TARGETS),
                          var_name="column", value_name="observed").query("observed >= 0")
    index = ["treatment", "yrdoy", "column"]
    np.testing.assert_allclose(rows.assign(yrdoy=dates).set_index(index).observed.sort_index(),
                               expected.set_index(index).observed.sort_index(), atol=1e-10, rtol=0)
    if not rows.assign(yrdoy=dates).set_index(index).index.sort_values().equals(
            expected.set_index(index).index.sort_values()):
        raise ValueError(f"Uncertainty and FileT tables disagree for {season}")

    tissues = pd.read_csv(bundle / "plant_npk_source_values.csv")
    leaf = (tissues.loc[tissues.organ.eq("叶")].dropna(subset=["N"]).groupby(["trno", "date"])["N"]
            .agg(["mean", "std"]).reset_index().rename(columns={"trno": "treatment"}))
    if leaf.empty:
        raise ValueError(f"Leaf nitrogen observations are missing for {season}")
    leaf = leaf.assign(file="PlantN.OUT", column="LN%D", group="leaf_n", observed=leaf["mean"] / 10,
                       sample_sd_or_scale=leaf["std"].fillna(0) / 10)
    rows = pd.concat([rows, leaf], ignore_index=True).drop(columns=["raw_sd", "mean", "std"])
    rows = rows.merge(meta, on="treatment", how="left", validate="many_to_one")
    if rows.treatment_label.isna().any() or set(rows.treatment) != set(meta.treatment):
        raise ValueError(f"Unmapped or missing treatments for {season}")
    rows["dataset"] = dataset
    rows["yrdoy"] = rows.date.map(dated)
    rows["name"] = (dataset + "_" + rows.column.str.lower().replace({"ln%d": "ln_pct"}) + "_"
                    + rows.treatment.astype(str) + "_" + rows.yrdoy.astype(str).str[-3:])
    rows["reference_treatment"] = pd.NA
    return rows.set_index("name", verify_integrity=True).reset_index(), manifest["bundle_id"], digest(manifest_path), excode


def balance(rows):
    count = rows.groupby(["dataset", "group"]).name.transform("size")
    seasons = rows.groupby("group").dataset.transform("nunique")
    if (set(rows.dataset) != set(DATASETS) or not rows.sample_sd_or_scale.gt(0).all()
            or not np.isfinite(rows.sample_sd_or_scale).all()):
        raise ValueError("The objective needs both seasons and finite positive observation uncertainty")
    rows = rows.assign(weight=1 / (rows.sample_sd_or_scale * np.sqrt(seasons * count)), preflight_only=0)
    return rows[TARGET_COLUMNS].sort_values(["dataset", "group", "name"])


def phase_a(rows, n21_fresh_contrasts=False):
    late = rows.loc[rows.group.eq("leaf_n")].groupby("dataset").yrdoy.max()
    fitted = rows.loc[rows.nitrogen_level.ne("N3")
                      & (~rows.group.eq("leaf_n") | rows.yrdoy.lt(rows.dataset.map(late)))].copy()
    leaf = fitted.group.eq("leaf_n")
    fitted.loc[leaf, "sample_sd_or_scale"] = np.where(fitted.loc[leaf, "nitrogen_level"].eq("N2"), .40,
                                                        fitted.loc[leaf, "sample_sd_or_scale"].clip(lower=.50))
    levels = balance(fitted)
    if not n21_fresh_contrasts:
        return levels
    delta = same_day_contrast(fitted.loc[fitted.group.eq("fresh")], "N2", "N1")
    delta["group"] = "delta_n21_fresh"
    terminal = delta.yrdoy.eq(delta.groupby(["dataset", "water_level"]).yrdoy.transform("max"))
    # Preserve the absolute targets. Give the added family one unit of
    # standardized squared weight, split equally over the two seasons.
    delta["window"] = np.where(terminal, "terminal", "earlier")
    count = delta.groupby(["dataset", "window"]).name.transform("size")
    budget = np.where(terminal, .60, .40) / len(DATASETS)
    delta["weight"] = np.sqrt(budget / count) / delta.sample_sd_or_scale
    delta["preflight_only"] = 0
    return pd.concat([levels, delta[TARGET_COLUMNS]], ignore_index=True)


def same_day_contrast(selected, high_level, low_level):
    keys = ["dataset", "water_level", "column", "yrdoy"]
    high = selected.loc[selected.nitrogen_level.eq(high_level)]
    low = selected.loc[selected.nitrogen_level.eq(low_level), keys + ["treatment", "observed", "sample_sd_or_scale"]]
    delta = high.merge(low, on=keys, how="outer", validate="one_to_one", suffixes=("", "_reference"), indicator=True)
    if delta.empty or not delta._merge.eq("both").all():
        raise ValueError(f"{high_level}-{low_level} requires same-season, same-water observations on each date")
    delta["name"] = "d_" + delta.name
    delta["observed"] -= delta.observed_reference
    delta["reference_treatment"] = delta.treatment_reference.astype(int)
    delta["sample_sd_or_scale"] = np.hypot(delta.sample_sd_or_scale, delta.sample_sd_or_scale_reference)
    return delta


def phase_b(rows):
    selected = rows.loc[rows.group.isin(["fresh", "shoot_dm"])]
    high = selected.loc[selected.nitrogen_level.eq("N3")].copy()
    delta = same_day_contrast(selected, "N3", "N2")
    delta["group"] = "delta_" + delta.group
    high["group"] = "n3_" + high.group
    return balance(pd.concat([high, delta], ignore_index=True))


def prepare_a(engine, baseline, bundle25, bundle26, out, n21_fresh_contrasts=False):
    reference = json.loads((baseline / "run_manifest.json").read_text())
    if digest(engine) != reference["engine_sha256"]:
        raise ValueError("Use the same engine as the original continuation")
    for name, value in reference["inputs_sha256"].items():
        if name.startswith("inputs/") or name in {"bounds.csv", "NIntegration.nml.tpl"}:
            if digest(baseline / name) != value:
                raise ValueError(f"Frozen 2A input changed: {name}")
    tables, evidence = [], {}
    out.mkdir(parents=True)
    for dataset, bundle in zip(DATASETS, (bundle25, bundle26)):
        targets, bundle_id, checksum, excode = observations(bundle, dataset)
        tables.append(targets)
        inputs = out / "inputs" / dataset
        shutil.copytree(baseline / "inputs", inputs, ignore=shutil.ignore_patterns("XXQL2601.*"))
        season_files = [f"{excode}.{suffix}" for suffix in ("TMX", "TMA", "TMT")]
        season_files += ["SOIL.SOL", "XXTW2403.WTH", "DSSBatch.v48"]
        for name in season_files:
            original = baseline / "inputs" / name
            if dataset == "s26" and digest(original) != digest(bundle / name):
                raise ValueError(f"26SP simulation input differs from the training bundle: {name}")
            shutil.copyfile(bundle / name, inputs / name)
        evidence[dataset] = {"bundle_id": bundle_id, "bundle_manifest_sha256": checksum,
                             "treatments": sorted(map(int, targets.treatment.unique()))}
    targets = pd.concat(tables, ignore_index=True)
    targets.to_csv(out / "all_observations.csv", index=False)
    phase_a(targets, n21_fresh_contrasts).to_csv(out / "observations.csv", index=False)
    phase_b(targets).to_csv(out / "phase_b_observations.csv", index=False)
    for name in ("bounds.csv", "NIntegration.nml.tpl"):
        shutil.copyfile(baseline / name, out / name)
    (out / "stage_receipt.json").write_text(json.dumps({"engine_sha256": digest(engine), "datasets": evidence,
        "weights": "equal squared-weight budget for each season within an observation family",
        "n21_fresh_contrasts": {"budget": 1., "terminal_share": .60} if n21_fresh_contrasts else None,
        "files_sha256": {str(p.relative_to(out)): digest(p) for p in out.rglob("*") if p.is_file()}}, indent=2) + "\n")


def prepare_b(stage, replay, out):
    config = replay / "configs/NIntegration.nml"
    source = json.loads((stage / "stage_receipt.json").read_text())
    receipt = json.loads((replay / "receipt.json").read_text())
    if (receipt["engine_sha256"] != source["engine_sha256"]
            or digest(config) != receipt["rendered_config_sha256"][config.name]):
        raise ValueError("Stage 2B requires a verified joint Stage 2A replay")
    for name, checksum in source["files_sha256"].items():
        if digest(stage / name) != checksum:
            raise ValueError(f"Joint input changed before Stage 2B: {name}")
    text = config.read_text()
    updates = {"lux_veg_mode": "2"} | {field: f"~ {field:26} ~" for field, *_ in BOUNDS}
    for field, value in updates.items():
        text, count = replace_assignment(text, field, value)
        if count > 1:
            raise ValueError(f"Nonunique assignment for {field}")
        if not count:
            text = text.replace("&NINTEGRATION", f"&NINTEGRATION\n {field}={value},", 1)
    out.mkdir(parents=True)
    shutil.copytree(stage / "inputs", out / "inputs")
    shutil.copyfile(stage / "phase_b_observations.csv", out / "observations.csv")
    shutil.copyfile(config, out / "frozen_2a.nml")
    (out / "NIntegration.nml.tpl").write_text("ptf ~\n" + text, encoding="ascii")
    pd.DataFrame(BOUNDS, columns=["name", "init", "lower", "upper"]).to_csv(out / "bounds.csv", index=False)
    (out / "stage_receipt.json").write_text(json.dumps({"mode": "joint_research_calibration",
        "frozen_2a_sha256": digest(config), "reference_replay_sha256": digest(replay / "receipt.json"),
        "engine_sha256": receipt["engine_sha256"], "source_stage_sha256": digest(stage / "stage_receipt.json"),
        "files_sha256": {str(p.relative_to(out)): digest(p) for p in out.rglob("*") if p.is_file()}}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="phase", required=True)
    for phase, args in (("a", ("engine", "baseline", "bundle25", "bundle26", "out")),
                        ("b", ("stage", "replay", "out"))):
        mode = modes.add_parser(phase)
        for name in args:
            mode.add_argument(f"--{name}", type=Path, required=True)
        if phase == "a":
            mode.add_argument("--n21-fresh-contrasts", action="store_true")
    args = vars(parser.parse_args())
    (prepare_a if args.pop("phase") == "a" else prepare_b)(**args)


if __name__ == "__main__":
    main()
