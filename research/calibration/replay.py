"""Replay the lowest actual-Phi member of the final IES iteration."""

import argparse
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import pandas as pd
from ies import sha
from forward import evaluate


def render_template(template, values):
    header, body = template.read_text().split("\n", 1)
    marker = re.escape(header.split()[1])

    def replace(match):
        name = match[1].strip().lower()
        value = format(values[name], ".17g")
        width = len(match[0])
        if len(value) > width:
            raise ValueError(f"Template field for {name} is too narrow for a precise replay")
        return value.rjust(width)

    return re.sub(fr"{marker}([^\r\n{marker}]+){marker}", replace, body)


def replay(work, out):
    manifest = json.loads((work / "run_manifest.json").read_text())
    config = json.loads((work / "forward.json").read_text())
    engine = Path(config["engine"])
    if sha(engine) != manifest["engine_sha256"]:
        raise ValueError("Engine checksum changed since calibration")
    for name, digest in manifest["inputs_sha256"].items():
        if sha(work / name) != digest:
            raise ValueError(f"Frozen calibration input changed: {name}")
    history = pd.read_csv(work / "mechanism.phi.actual.csv")
    final = history.iloc[-1]
    iteration = int(final["iteration"])
    parameters = pd.read_csv(
        work / f"mechanism.{iteration}.par.csv", index_col=0, float_precision="round_trip",
    )
    parameters.index = parameters.index.astype(str)
    phi = final.reindex(parameters.index).dropna()
    member = phi.idxmin()
    best = parameters.loc[member].rename(str.lower)
    targets = pd.read_csv(work / "observations.csv", dtype={"name": str})
    out.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="dssatx-replay-") as directory:
        files = {}
        for filename in config["templates"]:
            generated = Path(directory) / filename
            generated.write_text(render_template(work / f"{filename}.tpl", best), encoding="utf-8")
            files[generated] = filename
        predicted = evaluate(work / "inputs", engine, targets, files, out / "dssat.log")
    comparison = targets.assign(simulated=predicted)
    comparison["phi_contribution"] = (
        (comparison.simulated - comparison.observed) * comparison.weight
    ) ** 2
    actual = float(comparison.phi_contribution.sum())
    recorded = float(phi.loc[member])
    comparison.to_csv(out / "comparison.csv", index=False)
    best.to_csv(out / "parameters.csv", header=["value"])
    (out / "receipt.json").write_text(json.dumps({
        "iteration": iteration, "member": member, "phi_recorded": recorded,
        "phi_replayed": actual, "engine_sha256": manifest["engine_sha256"],
    }, indent=2) + "\n")
    if not math.isclose(actual, recorded, rel_tol=1e-5, abs_tol=1e-7):
        raise ValueError("Replayed Phi differs from the final ensemble record")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    replay(args.case.resolve(strict=True), args.out.resolve())


if __name__ == "__main__":
    main()
