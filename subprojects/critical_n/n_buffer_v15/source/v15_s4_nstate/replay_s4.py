#!/usr/bin/env python3
"""replay_s4.py -- deterministic replays for the S4 2x2 factor matrix.

Reuses replay_calibrated.run_replay. Combos:
  (2,2) S3-calibrated params on the S4 binary with both nmls (fused state)
  (1,2) S1-calibrated params on the S4 binary with the state nml only
Prerequisite: replay_calibrated.py has already produced best_params_{s1,s3}
in --diag-dir (the A/B replay dir).
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "subprojects/critical_n/n_buffer_v15"
                       / "source/v15_s3_v4root"))
from replay_calibrated import run_replay  # noqa: E402

V15 = REPO / "subprojects/critical_n/n_buffer_v15/source"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ab-diag-dir", required=True,
                    help="dir holding best_params_s1.csv / best_params_s3.csv")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    ab = Path(args.ab_diag_dir).resolve()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    exe = REPO / ".local/build-v15-s4-nstate/bin/dscsm048"
    combos = [
        ("s4_k2_state2", ab / "best_params_s3.csv",
         REPO / "workspace/runs/v15s3_r2_smoke_50x4_20261107",
         {"DSSAT_ROOT_UPTAKE_NML": str(V15 / "v15_s3_v4root"
                                        / "RootUptake.nml.template"),
          "DSSAT_NSTATE_NML": str(V15 / "v15_s4_nstate"
                                  / "NState.nml.template")}),
        ("s4_k1_state2", ab / "best_params_s1.csv",
         REPO / "workspace/runs/v15s1_smoke_50x4_20261107",
         {"DSSAT_NSTATE_NML": str(V15 / "v15_s4_nstate"
                                  / "NState.nml.template")}),
    ]
    manifest = {}
    for tag, params, case_dir, env_extra in combos:
        dest = run_replay(tag, exe, params, case_dir, out, env_extra)
        manifest[tag] = {"params": params.name, "replay": str(dest)}
        print(f"{tag} -> {dest}")
    (out / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
