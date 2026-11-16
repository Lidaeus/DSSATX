"""Run a private CRGRO case and extract explicitly mapped PEST observations."""

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

import pandas as pd

from data import native_table


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
            output = native_table(scratch / filename).sort_values("yrdoy")
            for row in group.itertuples(index=False):
                rows = output.loc[output.treatment.eq(row.treatment)]
                if not pd.isna(row.yrdoy):
                    rows = rows.loc[rows.yrdoy.eq(row.yrdoy)]
                if rows.run.nunique() != 1:
                    raise ValueError(f"{row.name}: treatment has missing or ambiguous runs")
                value = float(rows.iloc[-1][row.column])
                if not math.isfinite(value) or value <= -99:
                    raise ValueError(f"{row.name}: invalid {row.column} value {value}")
                values[row.name] = value
        return [values[name] for name in targets.name]


def main():
    case = Path.cwd()
    result = case / "simulated.txt"
    result.unlink(missing_ok=True)
    config = json.loads((case / "forward.json").read_text())
    values = evaluate(
        case / "inputs", Path(config["engine"]),
        pd.read_csv(case / "observations.csv", dtype={"name": str}),
        {case / filename: filename for filename in config["templates"]},
        case / "dssat.log",
    )
    result.write_text("".join(f"{value:.17g}\n" for value in values), encoding="ascii")


if __name__ == "__main__":
    main()
