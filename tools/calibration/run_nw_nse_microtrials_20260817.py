"""Prepare and launch the four-arm N/W response-NSE micro-trial.

The four arms share the final formal-run posterior subset containing member
126 and the same observation-noise seed.  A keeps the current static N/W
budgets; B/C/D replace the selected response-family weights with an
independent season-wise NSE contract.
"""
from __future__ import annotations

import argparse
import csv
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
from tools.calibration.prepare_dry_nse_factorial_20260815 import replace_case

BASE_CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
BASE_DIR = ROOT / "workspace/runs" / BASE_CASE
N_REALS = 80
NOPTMAX = 4
SEED = 20260818
AGENTS = 4
PORTS = {"A": 4070, "B": 4071, "C": 4072, "D": 4073}
LAMBDA_N = 1.5
LAMBDA_W = 0.75

ARMS = {
    "A": {"label": "baseline_static", "nse_families": {}},
    "B": {"label": "n_response_nse", "nse_families": {"N_RESPONSE": LAMBDA_N}},
    "C": {"label": "w_response_nse", "nse_families": {"W_RESPONSE": LAMBDA_W}},
    "D": {"label": "nw_response_nse", "nse_families": {"N_RESPONSE": LAMBDA_N, "W_RESPONSE": LAMBDA_W}},
}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    dynamic = {"_agents", "manager", "ies_quality", "calibration_finalize", "deterministic_candidates"}
    ignored: set[str] = set()
    for name in names:
        low = name.lower()
        if name in dynamic or low.startswith(("final_", "failed_dssat")):
            ignored.add(name)
        elif low in {"run_status.json", "multiseason_run_status.json", "formal_pipeline_status.json"}:
            ignored.add(name)
        elif low.endswith((".rec", ".rmr", ".rns", ".rei", ".res", ".jcb", ".log", ".pid", ".stp", ".out")):
            ignored.add(name)
        elif ".phi." in low or low.endswith((".base.par", ".base.rei", ".0.par.csv", ".observation_ensemble.csv", ".observation_ensemble.json")):
            ignored.add(name)
        elif any(f".{i}.{kind}.csv" in low for i in range(20) for kind in ("par", "obs", "pcs", "pdc")):
            ignored.add(name)
    return ignored


def _normal_real(value: object) -> str:
    return str(value).removesuffix(".0")


def _parameter_subset(target: Path) -> str:
    source = pd.read_csv(BASE_DIR / f"{BASE_CASE}.6.par.csv")
    real_col = next((c for c in source.columns if str(c).lower() in {"real_name", "realization"}), source.columns[0])
    ids = source[real_col].map(_normal_real)
    anchor = source.loc[ids.eq("126")]
    if len(anchor) != 1:
        raise ValueError(f"formal final ensemble must contain member126 exactly once; found {len(anchor)}")
    # Keep the anchor and a deterministic posterior subset.  The same rows
    # are used by all arms, so any change is attributable to the objective.
    rest = source.loc[~ids.eq("126")].sort_values(real_col, key=lambda s: s.astype(str)).head(N_REALS - 1)
    subset = pd.concat([anchor, rest], ignore_index=True)
    # PEST++ requires parameter and observation ensembles to share identical
    # realization names and row positions.  Preserve member 126's parameter
    # vector as row 0, while using a local 0..79 realization namespace.
    subset[real_col] = [str(i) for i in range(len(subset))]
    subset.to_csv(target / f"{target.name}.0.par.csv", index=False)
    return "126"


def _family_for_group(group: str) -> str:
    root = str(group).strip().upper()
    # Observation groups are commonly prefixed by the season, e.g.
    # ``25SP_NRESPM_H1``.  Strip that prefix before family classification.
    if "_" in root:
        first, remainder = root.split("_", 1)
        if first in {"25SP", "26SP", "25FA", "26FA"}:
            root = remainder
    if root.startswith("NRESP"):
        return "N_RESPONSE"
    if root.startswith("WRESP"):
        return "W_RESPONSE"
    if root.startswith("CHPDT"):
        return "HARVEST_DRY_TOTAL"
    if root.startswith("HPODW"):
        return "HARVEST_DRY_INCREMENT"
    if root.startswith("CHFPW"):
        return "HARVEST_FRESH"
    if root.startswith("LAID"):
        return "CANOPY"
    if root.startswith("LWAD") or root.startswith("SWAD"):
        return "BIOMASS"
    if root.startswith("SOILW") or root.startswith("SW"):
        return "SOIL_WATER"
    if root.startswith(("PDAP", "ADAP", "MDAP")):
        return "PHENO"
    if root.startswith(("LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM")):
        return "CANOPY"
    return "OTHER"


def _season_from_obs(name: str) -> str:
    token = str(name).upper().split("_", 1)[0]
    if token.startswith("25SP"):
        return "25SP"
    if token.startswith("26SP"):
        return "26SP"
    raise ValueError(f"cannot infer season from observation {name!r}")


def _apply_response_weights(target: Path, arm: str) -> dict[str, dict[str, float]]:
    case = target.name
    pst_path = target / f"{case}.pst"
    audit_path = target / f"{case}.weights.audit.csv"
    registry_path = target / f"{case}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit.index = audit["obsnme"].astype(str).str.lower()
    registry.index = registry["obsnme"].astype(str).str.lower()
    selected = audit[audit["obgnme"].astype(str).map(_family_for_group).isin({"N_RESPONSE", "W_RESPONSE"})].copy()
    specs = ARMS[arm]["nse_families"]
    summary: dict[str, dict[str, float]] = {}
    for family, lam in specs.items():
        rows = selected[selected["obgnme"].astype(str).map(_family_for_group).eq(family)].copy()
        if rows.empty:
            raise ValueError(f"{arm}: no observations found for {family}")
        rows["season_id"] = rows["obsnme"].map(_season_from_obs)
        for season, group in rows.groupby("season_id", sort=True):
            values = pd.to_numeric(group["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(values - values.mean()).sum())
            if not sst > 0:
                raise ValueError(f"{arm} {season}:{family}: non-positive SST")
            weight = float(math.sqrt(float(lam) / sst))
            for name in group["obsnme"].astype(str):
                key = name.lower()
                # pyemu normalizes observation names to lower-case in its
                # dataframe index; using the original mixed-case name would
                # silently append a new NaN row when assigning.
                pst.observation_data.loc[key, "weight"] = weight
                audit.loc[key, "weight"] = weight
                audit.loc[key, "weight_mode"] = "season_nse"
                audit.loc[key, "nse_lambda"] = float(lam)
                audit.loc[key, "nse_sst"] = sst
                registry.loc[key, "weight"] = weight
            summary[f"{season}:{family}"] = {"n": int(len(group)), "sst": sst, "lambda": float(lam), "weight": weight}
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
    return summary


def _prepare_arm(arm: str) -> tuple[Path, dict[str, dict[str, float]]]:
    case = f"e02_nw_nse_micro_{arm}_{ARMS[arm]['label']}_80x4_20260817"
    target = ROOT / "workspace/runs" / case
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing trial: {target}")
    shutil.copytree(BASE_DIR, target, ignore=_ignore)
    replace_case(target, BASE_CASE, case)
    anchor = _parameter_subset(target)
    summary = _apply_response_weights(target, arm)
    design_path = target / "joint_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["design_id"] = f"nw_response_nse_micro_{arm.lower()}_20260817"
    design["microtrial"] = {
        "arm": arm, "label": ARMS[arm]["label"], "anchor_member": anchor,
        "n_reals": N_REALS, "noptmax": NOPTMAX, "agents": AGENTS,
        "seed": SEED, "nse_response_lambdas": ARMS[arm]["nse_families"],
        "weight_identity": "weight=sqrt(lambda/SST) independently per season and response family",
    }
    design["nitrogen_response_objective"]["weighting"] = "nse" if "N_RESPONSE" in ARMS[arm]["nse_families"] else "static"
    design["nitrogen_response_objective"]["nse_lambda"] = ARMS[arm]["nse_families"].get("N_RESPONSE")
    design["water_response_objective"]["weighting"] = "nse" if "W_RESPONSE" in ARMS[arm]["nse_families"] else "static"
    design["water_response_objective"]["nse_lambda"] = ARMS[arm]["nse_families"].get("W_RESPONSE")
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "nw_nse_microtrial_contract.json").write_text(json.dumps({"case": case, "arm": arm, "anchor_member": anchor, "settings": ARMS[arm], "weight_audit": summary}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, summary


def _run_arm(target: Path, arm: str) -> int:
    command = [
        sys.executable, "tools/parallel/run_parallel.py",
        "--run-dir", str(target), "--case", target.name,
        "--mode", "ies", "--n-agents", str(AGENTS), "--port", str(PORTS[arm]), "--wait",
    ]
    return int(subprocess.run(command, cwd=ROOT, check=False).returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--arm", choices=["A", "B", "C", "D"])
    args = parser.parse_args()
    arms = [args.arm] if args.arm else list(ARMS)
    prepared: dict[str, str] = {}
    replacements = []
    if not args.prepare_only:
        from tools.calibration.launch_dry_nse_formal_20260817 import _swap
        replacements = _swap()
    try:
        for arm in arms:
            expected = ROOT / "workspace/runs" / f"e02_nw_nse_micro_{arm}_{ARMS[arm]['label']}_80x4_20260817"
            if expected.exists() and not args.prepare_only:
                # Allow a prepared trial to be launched after a transient
                # launcher interruption without rebuilding its sandbox.
                target, summary = expected, {}
            else:
                target, summary = _prepare_arm(arm)
            prepared[arm] = str(target)
            print(json.dumps({"arm": arm, "run_dir": str(target), "weight_audit": summary}, ensure_ascii=False))
            if not args.prepare_only:
                rc = _run_arm(target, arm)
                if rc:
                    return rc
    finally:
        if replacements:
            from tools.calibration.launch_dry_nse_formal_20260817 import _restore
            _restore(replacements)
    print(json.dumps({"status": "prepared" if args.prepare_only else "completed", "arms": prepared}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
