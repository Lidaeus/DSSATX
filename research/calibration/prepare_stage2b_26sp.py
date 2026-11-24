"""Stage the independent three-parameter 26SP Hill fit after a passing 2A replay."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from f5_26sp import ARCHIVE, digest
from prepare_26sp_signal import replace_assignment

BOUNDS = (
    ("lux_psi_threshold", .76, .68, .84),
    ("lux_hill_k", .04, .02, .10),
    ("lux_xfrt_drop", .50, .25, .50),
)


def observations():
    archive = pd.read_csv(ARCHIVE / "matched_observations.csv")
    used = archive.loc[archive.nitrogen_level.isin(["N2", "N3"]) & archive.group.isin(["fresh", "shoot_dm"])]
    keys = ["water_level", "file", "column", "yrdoy"]
    high = used.loc[used.nitrogen_level.eq("N3")].copy()
    medium = used.loc[used.nitrogen_level.eq("N2"), keys + ["treatment", "observed", "sample_sd_or_scale"]]
    if high.empty or not high["role"].eq("n3").all():
        raise ValueError("The 2B absolute observations must come from the reserved N3 rows")
    contrasts = high.merge(medium, on=keys, how="left", validate="one_to_one", suffixes=("", "_n2"))
    if contrasts.treatment_n2.isna().any():
        raise ValueError("Every N3 observation needs a matching N2 treatment and date")
    contrasts["name"] = "d_" + contrasts.name
    contrasts["observed"] -= contrasts.observed_n2
    contrasts["reference_treatment"] = contrasts.treatment_n2.astype(int)
    contrasts["sample_sd_or_scale"] = np.hypot(contrasts.sample_sd_or_scale, contrasts.sample_sd_or_scale_n2)
    contrasts["group"] = "delta_" + contrasts.group
    high["group"] = "n3_" + high.group
    high["reference_treatment"] = pd.NA
    result = pd.concat([high, contrasts], ignore_index=True)
    result["weight"] = 1 / (result.sample_sd_or_scale * np.sqrt(result.groupby("group").name.transform("size")))
    result["preflight_only"] = 0
    return result[["name", "file", "column", "treatment", "reference_treatment", "yrdoy", "observed", "weight",
                   "group", "sample_sd_or_scale", "preflight_only"]]


def prepare(engine, stage, assessment, config, out):
    receipt = json.loads(assessment.read_text())
    if receipt["stage_2a"]["pass"] is not True:
        raise ValueError("Stage 2B requires a complete native stage-2A pass")
    if receipt["engine_sha256"] != digest(engine) or receipt["cases"]["posterior"]["config_sha256"] != digest(config):
        raise ValueError("Stage 2A engine or frozen parameter file differs from the passing replay")
    text = config.read_text()
    new = {"lux_veg_mode": "2"} | {field: f"~ {field:26} ~" for field, *_ in BOUNDS}
    for field, value in new.items():
        text, count = replace_assignment(text, field, value)
        if count > 1:
            raise ValueError(f"Nonunique assignment for {field}")
        if not count:
            text = text.replace("&NINTEGRATION", f"&NINTEGRATION\n {field}={value},", 1)
    targets = observations()
    out.mkdir(parents=True)
    shutil.copytree(stage / "inputs", out / "inputs")
    shutil.copyfile(config, out / "frozen_2a.nml")
    (out / "NIntegration.nml.tpl").write_text("ptf ~\n" + text, encoding="ascii")
    pd.DataFrame(BOUNDS, columns=["name", "init", "lower", "upper"]).to_csv(out / "bounds.csv", index=False)
    targets.to_csv(out / "observations.csv", index=False)
    (out / "input_receipt.json").write_text(json.dumps({
        "engine_sha256": receipt["engine_sha256"],
        "passed_stage_2a_sha256": digest(assessment),
        "frozen_config_sha256": digest(config),
        "stage_files_sha256": {file.name: digest(file) for file in out.iterdir() if file.is_file()},
        "target_count_by_group": targets.groupby("group").size().to_dict(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "stage", "assessment", "config", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.engine, args.stage, args.assessment, args.config, args.out)
