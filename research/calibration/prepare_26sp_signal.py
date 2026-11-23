"""Stage a local, preflight-only 26SP multi-response IES case."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
import re
import shutil
from statistics import mean, stdev
import sys

RESEARCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH))
from portable_dssat import prepare_case

TEMPLATE = RESEARCH / "root_n_kernel/source/TMDeficiency.nml.template"
FILES = ("XXQL2601.TMX", "XXQL2601.TMA", "XXQL2601.TMT", "SOIL.SOL", "XXTW2403.WTH",
         "TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE", "DSSBatch.v48")
TARGETS = {
    "LAID": ("PlantGro.OUT", "lai", 0.05),
    "LWAD": ("PlantGro.OUT", "shoot_dm", 25),
    "SWAD": ("PlantGro.OUT", "shoot_dm", 25),
    "CHFPW": ("FreshWt.OUT", "fresh", 250),
}
BOUNDS = (
    ("rnk_vmax_scale", 1, 0.5, 2.0), ("pool_beta", 1, 0.3, 1),
    ("assim_no3_v", 0.003, 0.0015, 0.006), ("leaf_a", 0.042, 0.035, 0.05),
    ("remob_tau", 8, 4, 16), ("lai_cn_shape", 2, 1, 3),
)
HOLDOUT = {7, 10}  # W3–N1 and W1–N1. Every date and response stays out of fitting.


def records(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        yield from csv.DictReader(stream)


def dated(value):
    dt = date.fromisoformat(value)
    return 1000 * dt.year + dt.timetuple().tm_yday


def targets(experiment):
    rows = []
    for raw in records(experiment / "observation_uncertainty.csv"):
        variable = raw["variable"]
        if raw["season_id"] != "26SP" or raw["quality_flag"] != "ok" or variable not in TARGETS:
            continue
        file, group, floor = TARGETS[variable]
        value = float(raw["value"])
        sigma = max(float(raw["raw_sd"] or 0), 0.05 * value, floor)
        rows.append((int(raw["trno"]), dated(raw["date"]), variable, file, group, value, sigma))
    leaf = defaultdict(list)
    for raw in records(experiment / "plant_npk_source_values.csv"):
        if raw["organ"] == "叶" and raw["N"]:
            # mg N per g dry mass to percent. Recovery has not been quantified.
            leaf[int(raw["trno"]), dated(raw["date"])].append(float(raw["N"]) / 10)
    for (run, day), samples in sorted(leaf.items()):
        rows.append((run, day, "LN%D", "PlantN.OUT", "leaf_n", mean(samples), stdev(samples)))
    if not leaf or {row[0] for row in rows} != set(range(1, 13)):
        raise ValueError("Expected dated 26SP leaf N and growth data from all 12 treatments")
    counts = Counter(row[4] for row in rows if row[0] not in HOLDOUT)
    fit, holdout = [], []
    codes = {"LN%D": "ln_pct"}
    for run, day, column, file, group, value, sigma in sorted(rows):
        destination = holdout if run in HOLDOUT else fit
        weight = 0 if run in HOLDOUT or group == "leaf_n" else 1 / (sigma * sqrt(counts[group]))
        destination.append(dict(
            name=f"{codes.get(column, column.lower())}_{run}_{day}",
            file=file, column=column, treatment=run, yrdoy=day, observed=value,
            weight=weight, group=group, sample_sd_or_scale=sigma, preflight_only=1,
        ))
    assert len({row["name"] for row in fit + holdout}) == len(rows)
    return fit, holdout


def write_csv(path, rows):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def stage(experiment, out):
    out.mkdir(parents=True, exist_ok=False)
    fit, holdout = targets(experiment)
    write_csv(out / "observations.csv", fit)
    write_csv(out / "holdout.csv", holdout)
    write_csv(out / "bounds.csv", [dict(name=n, init=x, lower=lo, upper=hi) for n, x, lo, hi in BOUNDS])
    default = TEMPLATE.read_text(encoding="ascii")
    default, count = re.subn(r"(?im)^(&rootnuptake[ \t]*)$", r"\1\n rnk_vmax_scale=1.,", default)
    if count != 1:
        raise ValueError("Expected one steady root namelist in the deficiency template")
    config = out / "NIntegration.nml"
    config.write_text(default, encoding="ascii")
    rendered = default
    for name, _, _, _ in BOUNDS:
        pattern = rf"(\b{name}\s*=\s*)[-.\d]+"
        rendered, count = re.subn(pattern, rf"\1~ {name:19s} ~", rendered)
        if count != 1:
            raise ValueError(f"Expected one template assignment for {name}")
    (out / "NIntegration.nml.tpl").write_text("ptf ~\n" + rendered, encoding="ascii")
    inputs = prepare_case(argparse.Namespace(config=config, out=out / "inputs"))
    for name in FILES:
        shutil.copyfile(experiment / name, inputs / name)
    sources = (*FILES, "observation_uncertainty.csv", "plant_npk_source_values.csv")
    receipt = {
        "stage": "2A input preflight only", "holdout_treatments": sorted(HOLDOUT),
        "training_rows_by_group": Counter(row["group"] for row in fit),
        "positive_weight_rows_by_group": Counter(row["group"] for row in fit if row["weight"] > 0),
        "holdout_rows_by_group": Counter(row["group"] for row in holdout),
        "nitrogen_target_blocker": "No validated digestion recovery or measured whole-plant uptake series",
        "input_source_sha256": {name: sha256((experiment / name).read_bytes()).hexdigest() for name in sources},
    }
    (out / "preflight_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True, help="26SP SASC70 experiment pack")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stage(args.experiment.resolve(strict=True), args.out.resolve())


if __name__ == "__main__":
    main()
