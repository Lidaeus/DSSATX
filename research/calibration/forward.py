"""Run a private CRGRO case and extract explicitly mapped PEST observations."""

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import traceback

import pandas as pd

from crop_cards import VALUES, materialize, read_values
from data import native_table


def render_template(template, values):
    header, body = template.read_text().split("\n", 1)
    marker = re.escape(header.split()[1])

    def replace(match):
        name = match[1].strip().lower()
        value = str(float(values[name]))
        width = len(match[0])
        if len(value) > width:
            raise ValueError(f"Template field for {name} is too narrow for a precise replay")
        return value.rjust(width)

    return re.sub(fr"{marker}([^\r\n{marker}]+){marker}", replace, body)


def evaluate(case, executable, targets, overrides, log):
    environment = os.environ.copy()
    for key in ("DSSAT_N_CONFIG", "DSSAT_ROOT_UPTAKE_NML", "DSSAT_NSTATE_NML"):
        environment.pop(key, None)
    environment["DSSAT_HOME"] = f".{os.sep}"
    with TemporaryDirectory(prefix="dssatx-forward-") as directory:
        scratch = Path(directory)
        shutil.copytree(case, scratch, dirs_exist_ok=True)
        for source, filename in overrides.items():
            shutil.copyfile(source, scratch / filename)
        with log.open("wb") as stream:
            subprocess.run(
                [str(executable), "CRGRO048", "B", "DSSBatch.v48"],
                cwd=scratch, env=environment, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, timeout=300, check=True,
            )
        values = {}
        for filename, group in targets.groupby("file", sort=False):
            output = native_table(scratch / filename, allow_numeric_overflow=True).sort_values("yrdoy")
            for row in group.itertuples(index=False):
                rows = output.loc[output.treatment.eq(row.treatment)]
                if not pd.isna(row.yrdoy):
                    rows = rows.loc[rows.yrdoy.eq(row.yrdoy)]
                if rows.run.nunique() != 1:
                    raise ValueError(f"{row.name}: treatment has missing or ambiguous runs")
                value = float(rows.iloc[-1][row.column])
                if not math.isfinite(value) or value <= -99:
                    raise ValueError(f"{row.name}: invalid or overflowed {filename} column {row.column}: {value}")
                values[row.name] = value
        return [values[name] for name in targets.name]


def main():
    case = Path.cwd()
    result = case / "simulated.txt"
    result.unlink(missing_ok=True)
    config = json.loads((case / "forward.json").read_text())
    inputs = case / "inputs"
    overrides = {case / filename: filename for filename in config["templates"]}
    card_receipt = case / "crop_readback.json"
    card_receipt.unlink(missing_ok=True)
    with TemporaryDirectory(prefix="dssatx-crop-cards-") as directory:
        readback = {}
        if config.get("crop_cards"):
            crops, readback = materialize(config["crop_cards"], inputs, read_values(case / VALUES), Path(directory))
            overrides.update(crops)
        values = evaluate(inputs, Path(config["engine"]),
                          pd.read_csv(case / "observations.csv", dtype={"name": str}),
                          overrides, case / "dssat.log")
    if readback:
        card_receipt.write_text(json.dumps(readback, indent=2) + "\n", encoding="ascii")
    result.write_text("".join(f"{value:.17g}\n" for value in values), encoding="ascii")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        with Path("forward_errors.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        raise
