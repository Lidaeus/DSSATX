"""Rebuild the local 26SP off/A/B audit with explicitly selected engines."""

import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from verify_p1 import audit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from portable_dssat import prepare_case, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "t3-engine", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
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
    for arm, mode in (("off-t3", 0), ("off", 0), ("A", 1), ("B", 2)):
        case = prepare_case(SimpleNamespace(config=config, out=out / arm))
        nml = case / "NIntegration.nml"
        nml.write_text(config.read_text().replace("rnk_mode=1,", f"rnk_mode={mode},"))
        run([str(engines[arm]), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
        if mode:
            results.append(audit(case, arm, 12))
        elif (case / "LayerRootNUptake.csv").exists():
            raise ValueError(f"{arm}: root ledger unexpectedly enabled")
    reference = sorted((out / "off-t3").glob("*.csv"))
    if not reference:
        raise ValueError("Missing baseline ledgers")
    for file in reference:
        if file.read_bytes() != (out / "off" / file.name).read_bytes():
            raise ValueError(f"Off-mode ledger changed: {file.name}")
    receipt = {"matching_off_csv": [file.name for file in reference], "active_arms": results}
    (out / "audit.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
