"""Rebuild the local 26SP off/steady audit with explicitly selected engines."""

import argparse
import hashlib
import json
import math
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
    parser.add_argument("--organic-buffer", action="store_true",
                        help="Use the S1-inspired leaf/stem organic buffer in the active steady run")
    parser.add_argument("--nstfac", type=float,
                        help="Set NSTFAC in prepared species files (organic-buffer default: 0.60)")
    parser.add_argument("--penetration-coeff", type=float, default=0.0,
                        help="Test a positive NH4 penetration coefficient on the steady case")
    args = parser.parse_args()
    if not math.isfinite(args.penetration_coeff) or args.penetration_coeff < 0:
        parser.error("--penetration-coeff must be finite and nonnegative")
    nstfac = args.nstfac if args.nstfac is not None else (0.60 if args.organic_buffer else None)
    if nstfac is not None and not 0.1 <= nstfac <= 1.0:
        parser.error("--nstfac must be in [0.1, 1.0]")
    engines = {
        arm: (args.t3_engine if arm == "off-t3" else args.engine).resolve(strict=True)
        for arm in ("off-t3", "off", "A")
    }
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    config = HERE / "p1_smoke.nml"
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE="1")
    env.pop("DSSAT_N_CONFIG", None)
    config_inputs = {}
    base_text = config.read_text()
    active_config = HERE / "p1_organic.nml" if args.organic_buffer else config
    template = (HERE.parent / "source/RootNUptake.nml.template").read_text()
    template = template.replace("rnk_penetration_coeff=0.", f"rnk_penetration_coeff={args.penetration_coeff:.16e}", 1)
    experiment_text = active_config.read_text() + template
    off_text = base_text + "\n&ROOTNUPTAKE rnk_mode=0 /\n"
    for arm in engines:
        case = prepare_case(SimpleNamespace(config=config, out=out / arm))
        nml = case / "NIntegration.nml"
        nml.write_text(experiment_text if arm == "A" else off_text)
        if nstfac is not None:
            write_nstfac(case / "TMGRO048.SPE", nstfac)
        config_inputs[arm] = hashlib.sha256(nml.read_bytes()).hexdigest()
        run([str(engines[arm]), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
        if arm == "A":
            steady_audit = audit(case, 12)
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
        "nh4_penetration_coeff": args.penetration_coeff,
        "nstfac_override": nstfac,
        "common_arm_config_sha256": hashlib.sha256(experiment_text.encode()).hexdigest(),
        "arm_config_sha256": config_inputs,
        "matching_off_csv": [file.name for file in reference],
        "steady": steady_audit,
    }
    (out / "audit.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
