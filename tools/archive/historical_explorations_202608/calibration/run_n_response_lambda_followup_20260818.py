"""Prepare and run the N_RESPONSE NSE lambda 1.0/2.0 follow-up trials.

The completed 1.5 arm from 20260817 is reused for the middle dose.  Both new
arms use the identical 80-member posterior subset, observation-noise ensemble,
and four-iteration contract used by that arm.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest import _write_observation_noise_ensemble
from tools.calibration.launch_dry_nse_formal_20260817 import _restore, _swap
from tools.calibration.prepare_dry_nse_factorial_20260815 import replace_case
from tools.calibration.run_nw_nse_microtrials_20260817 import (
    BASE_CASE,
    BASE_DIR,
    N_REALS,
    NOPTMAX,
    SEED,
    _family_for_group,
    _ignore,
    _parameter_subset,
    _season_from_obs,
)

TRIALS = {
    "10": {"lambda": 1.0, "case": "e02_nresp_nse_lam10_80x4_20260818", "port": 4080},
    "20": {"lambda": 2.0, "case": "e02_nresp_nse_lam20_80x4_20260818", "port": 4081},
}


def prepare(tag: str) -> Path:
    spec = TRIALS[tag]
    target = ROOT / "workspace/runs" / spec["case"]
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    shutil.copytree(BASE_DIR, target, ignore=_ignore)
    replace_case(target, BASE_CASE, spec["case"])
    _parameter_subset(target)

    case = target.name
    pst_path = target / f"{case}.pst"
    audit_path = target / f"{case}.weights.audit.csv"
    registry_path = target / f"{case}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit.index = audit["obsnme"].astype(str).str.lower()
    registry.index = registry["obsnme"].astype(str).str.lower()
    rows = audit[audit["obgnme"].astype(str).map(_family_for_group).eq("N_RESPONSE")].copy()
    rows["season_id"] = rows["obsnme"].map(_season_from_obs)
    weight_audit = {}
    for season, group in rows.groupby("season_id", sort=True):
        values = pd.to_numeric(group["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(values - values.mean()).sum())
        weight = math.sqrt(float(spec["lambda"]) / sst)
        for name in group["obsnme"].astype(str):
            key = name.lower()
            pst.observation_data.loc[key, "weight"] = weight
            audit.loc[key, ["weight", "weight_mode", "nse_lambda", "nse_sst"]] = [
                weight, "season_nse", float(spec["lambda"]), sst,
            ]
            registry.loc[key, "weight"] = weight
        weight_audit[season] = {"n": len(group), "sst": sst, "lambda": spec["lambda"], "weight": weight}

    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{case}.0.par.csv",
        "ies_observation_ensemble": f"{case}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    pst.write(str(pst_path))
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    _write_observation_noise_ensemble(pst_path, audit_path, target, case, N_REALS, SEED)

    design_path = target / "joint_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["design_id"] = f"n_response_nse_lambda_{spec['lambda']}_followup_20260818"
    design["nitrogen_response_objective"].update({"weighting": "nse", "nse_lambda": spec["lambda"]})
    design["water_response_objective"].update({"weighting": "static", "nse_lambda": None})
    design["n_response_lambda_followup"] = {
        "anchor_source_member": "126", "anchor_local_realization": "0",
        "n_reals": N_REALS, "noptmax": NOPTMAX, "agents": 4, "seed": SEED,
        "comparison_arm_lambda_1_5": "e02_nw_nse_micro_B_n_response_nse_80x4_20260817",
    }
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "n_response_lambda_contract.json").write_text(
        json.dumps({"case": case, "lambda": spec["lambda"], "weight_audit": weight_audit}, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def run(target: Path, port: int) -> int:
    return subprocess.run([
        sys.executable, "tools/parallel/run_parallel.py", "--run-dir", str(target),
        "--case", target.name, "--mode", "ies", "--n-agents", "4", "--port", str(port), "--wait",
    ], cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--trial", choices=sorted(TRIALS))
    args = parser.parse_args()
    tags = [args.trial] if args.trial else list(TRIALS)
    prepared = {}
    for tag in tags:
        expected = ROOT / "workspace/runs" / TRIALS[tag]["case"]
        target = expected if expected.exists() and not args.prepare_only else prepare(tag)
        prepared[tag] = str(target)
    if args.prepare_only:
        print(json.dumps({"status": "prepared", "trials": prepared}, indent=2))
        return 0
    replacements = _swap()
    try:
        for tag in tags:
            rc = run(Path(prepared[tag]), TRIALS[tag]["port"])
            if rc:
                return rc
    finally:
        _restore(replacements)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
