"""Rebuild the local 26SP off/A/B audit with explicitly selected engines."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from verify_p1 import audit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from portable_dssat import prepare_case, run


def write_nstfac(species_file, value):
    lines = species_file.read_bytes().splitlines(keepends=True)
    records = [i for i, line in enumerate(lines) if b"XPODF, NSTFAC,NREXP,NRMIN" in line]
    if len(records) != 1:
        raise ValueError("Expected one NSTFAC row in the prepared species file")
    index, = records
    line = lines[index]
    field = f"{value:6.3f}".encode("ascii")
    lines[index] = line[:6] + field + line[12:]
    species_file.write_bytes(b"".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "t3-engine", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--radial-cells", type=int, choices=(8, 16), default=8,
                        help="Transient radial grid for the active pair; nominal substeps are fixed at 24")
    parser.add_argument("--organic-buffer", action="store_true",
                        help="Use the S1-inspired leaf/stem organic buffer in active A/B runs")
    parser.add_argument("--nstfac", type=float,
                        help="Set NSTFAC in prepared species files (organic-buffer default: 0.60)")
    args = parser.parse_args()
    nstfac = args.nstfac if args.nstfac is not None else (0.60 if args.organic_buffer else None)
    if nstfac is not None and not 0.1 <= nstfac <= 1.0:
        parser.error("--nstfac must be in [0.1, 1.0]")
    engines = {
        arm: (args.t3_engine if arm == "off-t3" else args.engine).resolve(strict=True)
        for arm in ("off-t3", "off", "A", "B")
    }
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    config = HERE / "p1_smoke.nml"
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE="1")
    env.pop("DSSAT_N_CONFIG", None)
    results = []
    config_inputs = {}
    base_text = config.read_text()
    active_config = HERE / "p1_organic.nml" if args.organic_buffer else config
    experiment_text = active_config.read_text() + (HERE.parent / "source/RootNUptake.nml.template").read_text()
    off_text = base_text + "\n&ROOTNUPTAKE rnk_mode=0 /\n"
    for arm, mode in (("off-t3", 0), ("off", 0), ("A", 1), ("B", 2)):
        case = prepare_case(SimpleNamespace(config=config, out=out / arm))
        nml = case / "NIntegration.nml"
        text = experiment_text if mode else off_text
        config_text = text.replace("rnk_mode=1,", f"rnk_mode={mode},")
        if mode and args.radial_cells == 16:
            config_text = config_text.replace(f"rnk_mode={mode},", f"rnk_mode={mode}, rnk_radial_cells=16,")
        nml.write_text(config_text)
        if nstfac is not None:
            write_nstfac(case / "TMGRO048.SPE", nstfac)
        config_inputs[arm] = hashlib.sha256(nml.read_bytes()).hexdigest()
        run([str(engines[arm]), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
        if mode:
            results.append(audit(case, arm, 12, expected_shared=True))
        elif (case / "LayerRootNUptake.csv").exists():
            raise ValueError(f"{arm}: root ledger unexpectedly enabled")
    reference = sorted((out / "off-t3").glob("*.csv"))
    if not reference:
        raise ValueError("Missing baseline ledgers")
    for file in reference:
        if file.read_bytes() != (out / "off" / file.name).read_bytes():
            raise ValueError(f"Off-mode ledger changed: {file.name}")
    receipt = {
        "shared_transport": True,
        "organic_buffer": args.organic_buffer,
        "nstfac_override": nstfac,
        "radial_cells": args.radial_cells,
        "nominal_substeps": 24,
        "common_arm_config_sha256": hashlib.sha256(experiment_text.encode()).hexdigest(),
        "arm_config_sha256": config_inputs,
        "matching_off_csv": [file.name for file in reference],
        "active_arms": results,
    }
    (out / "audit.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
