"""Stage a local 26SP multi-response IES case."""

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
    ("rnk_vmax_scale", 1, 0.5, 2.0), ("pool_beta", 0.6, 0.1, 1.5),
    ("assim_no3_v", 0.003, 0.0015, 0.006), ("leaf_a", 0.042, 0.035, 0.05),
    ("remob_tau", 8, 4, 16), ("lai_cn_shape", 2, 1, 3),
)
JOINT_PARAMETERS = Path(__file__).with_name("26sp_joint_parameters.csv")
HOLDOUT = {7, 10}  # W3–N1 and W1–N1. Every date and response stays out of fitting.
LEAF_N_SIGMA_FLOOR = 0.5  # Percentage points of dry mass.
LATE_LEAF_N = 2026198  # 17 July is diagnostic only.


def records(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        yield from csv.DictReader(stream)


def dated(value):
    dt = date.fromisoformat(value)
    return 1000 * dt.year + dt.timetuple().tm_yday


def targets(experiment):
    levels = {int(row["treatment"]): row["nitrogen_level"]
              for row in records(experiment / "treatment_metadata.csv")}
    if set(levels) != set(range(1, 13)) or Counter(levels.values()) != dict.fromkeys(("N0", "N1", "N2", "N3"), 3):
        raise ValueError("Expected the 12 26SP factorial treatments")
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
        scatter = stdev(samples) if len(samples) > 1 else 0.0
        rows.append((run, day, "LN%D", "PlantN.OUT", "leaf_n", mean(samples), scatter))
    if not leaf or {row[0] for row in rows} != set(range(1, 13)):
        raise ValueError("Expected dated 26SP leaf N and growth data from all 12 treatments")
    def active(run, day, group):
        return (run not in HOLDOUT and levels[run] != "N3"
                and (group != "leaf_n" or (levels[run] in ("N0", "N1") and day != LATE_LEAF_N)))

    counts = Counter(group for run, day, _, _, group, _, _ in rows if active(run, day, group))
    fit, holdout, high_n = [], [], []
    codes = {"LN%D": "ln_pct"}
    for run, day, column, file, group, value, sigma in sorted(rows):
        destination = holdout if run in HOLDOUT else high_n if levels[run] == "N3" else fit
        use = active(run, day, group)
        if use and group == "leaf_n":
            sigma = max(sigma, LEAF_N_SIGMA_FLOOR)
        weight = 1 / (sigma * sqrt(counts[group])) if use else 0
        destination.append(dict(
            name=f"{codes.get(column, column.lower())}_{run}_{day}",
            file=file, column=column, treatment=run, yrdoy=day, observed=value,
            weight=weight, group=group, sample_sd_or_scale=sigma, preflight_only=1,
        ))
    assert len({row["name"] for row in fit + holdout + high_n}) == len(rows)
    return fit, holdout, high_n


def write_csv(path, rows):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def replace_assignment(config, name, replacement):
    pattern = rf"(?im)(^[^!\n]*?\b{name}\s*=\s*)[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[de][-+]?\d+)?(?=[ \t,!/\r\n]|$)"
    return re.subn(pattern, lambda match: match[1] + replacement, config)


def stage(experiment, out, joint=False, calibrate=False):
    out.mkdir(parents=True, exist_ok=False)
    fit, holdout, high_n = targets(experiment)
    if calibrate:
        for row in fit:
            row["preflight_only"] = 0
    write_csv(out / "observations.csv", fit)
    write_csv(out / "holdout.csv", holdout)
    write_csv(out / "stage2b_observations.csv", high_n)
    n_bounds = bounds = BOUNDS
    scopes = {}
    if joint:
        parameters = list(records(JOINT_PARAMETERS))
        shutil.copyfile(JOINT_PARAMETERS, out / "parameter_design.csv")
        scopes = Counter(row["scope"] for row in parameters)
        bounds = tuple(tuple(row[key] for key in ("name", "init", "lower", "upper")) for row in parameters)
        n_bounds = tuple(bound for bound, row in zip(bounds, parameters) if row["file"] == "NIntegration.nml")
        write_csv(out / "crop_map.csv", [
            {key: row[key] for key in ("name", "file", "record", "field")}
            for row in parameters if row["file"] != "NIntegration.nml"
        ])
    write_csv(out / "bounds.csv", [dict(name=n, init=x, lower=lo, upper=hi) for n, x, lo, hi in bounds])
    default = TEMPLATE.read_text(encoding="ascii")
    default, count = re.subn(r"(?im)^(&rootnuptake[ \t]*)$", r"\1\n rnk_vmax_scale=1.,", default)
    if count != 1:
        raise ValueError("Expected one steady root namelist in the deficiency template")
    rendered = default
    for name, init, _, _ in n_bounds:
        default, count = replace_assignment(default, name, str(init))
        if count != 1:
            raise ValueError(f"Expected one template assignment for {name}")
        rendered, _ = replace_assignment(rendered, name, f"~ {name:19s} ~")
    config = out / "NIntegration.nml"
    config.write_text(default, encoding="ascii")
    (out / "NIntegration.nml.tpl").write_text("ptf ~\n" + rendered, encoding="ascii")
    inputs = prepare_case(argparse.Namespace(config=config, out=out / "inputs"))
    for name in FILES:
        shutil.copyfile(experiment / name, inputs / name)
    sources = (*FILES, "observation_uncertainty.csv", "plant_npk_source_values.csv", "treatment_metadata.csv")
    receipt = {
        "stage": "2A joint calibration" if calibrate else "2A input preflight only",
        "holdout_treatments": sorted(HOLDOUT),
        "parameter_profile": "joint_crop_and_namelist" if joint else "namelist_only",
        "parameter_count": len(bounds),
        "parameter_count_by_scope": scopes,
        "training_rows_by_group": Counter(row["group"] for row in fit),
        "positive_weight_rows_by_group": Counter(row["group"] for row in fit if row["weight"] > 0),
        "holdout_rows_by_group": Counter(row["group"] for row in holdout),
        "stage_2b_treatments": sorted({row["treatment"] for row in high_n}),
        "stage_2b_rows_by_group": Counter(row["group"] for row in high_n),
        "leaf_n_proxy": {"active_levels": ["N0", "N1"], "sigma_floor_pct_points": LEAF_N_SIGMA_FLOOR,
                         "diagnostic_only_yrdoy": LATE_LEAF_N, "digestion_recovery_verified": False},
        "input_source_sha256": {name: sha256((experiment / name).read_bytes()).hexdigest() for name in sources},
    }
    if joint:
        receipt["parameter_design_sha256"] = sha256((out / "parameter_design.csv").read_bytes()).hexdigest()
    (out / "preflight_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True, help="26SP SASC70 experiment pack")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--joint", action="store_true", help="Use the full crop-card and mechanism parameter design")
    parser.add_argument("--calibrate", action="store_true", help="Permit updates for the joint 2A training rows")
    args = parser.parse_args()
    if args.calibrate and not args.joint:
        parser.error("--calibrate requires --joint")
    stage(args.experiment.resolve(strict=True), args.out.resolve(), joint=args.joint, calibrate=args.calibrate)


if __name__ == "__main__":
    main()
