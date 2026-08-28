"""Run selected-eight water-response NSE objective trials.

A preserves the selected-eight static objective. B and C replace W_RESPONSE
weights with four independent season x nitrogen-stratum NSE contracts.  The
declared lambda is a per-season budget and is split equally across N0/N3.
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
from tools.calibration.prepare_dry_nse_factorial_20260815 import replace_case

BASE_CASE = "e02_selected8_fixedsoil_nse_official_200x6_20260818"
BASE_DIR = ROOT / "workspace" / "runs" / BASE_CASE
N_REALS = 80
NOPTMAX = 4
AGENTS = 6
SEED = 20260818
PORTS = {"A": 4080, "B": 4081, "C": 4082}
ARMS = {
    "A": {"label": "baseline_static", "lambda_per_season": None},
    "B": {"label": "wresp_nse_lam0p5", "lambda_per_season": 0.5},
    "C": {"label": "wresp_nse_lam1p0", "lambda_per_season": 1.0},
}
CASE_SUFFIX = {"A": "", "B": "_retry1", "C": "_retry1"}


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


def _parameter_subset(target: Path) -> None:
    source = pd.read_csv(BASE_DIR / f"{BASE_CASE}.6.par.csv")
    real_col = next((c for c in source.columns if str(c).lower() in {"real_name", "realization"}), source.columns[0])
    ids = source[real_col].map(_normal_real)
    anchor = source.loc[ids.eq("192")]
    if len(anchor) != 1:
        raise ValueError(f"final ensemble must contain member192 exactly once; found {len(anchor)}")
    rest = source.loc[~ids.eq("192")].sort_values(real_col, key=lambda s: s.astype(str)).head(N_REALS - 1)
    subset = pd.concat([anchor, rest], ignore_index=True)
    subset[real_col] = [str(index) for index in range(len(subset))]
    subset.to_csv(target / f"{target.name}.0.par.csv", index=False)


def _water_rows(audit: pd.DataFrame) -> pd.Series:
    return audit["obgnme"].astype(str).str.upper().str.contains("WRESP")


def _apply_weights(target: Path, arm: str) -> dict[str, dict[str, float]]:
    case = target.name
    pst_path = target / f"{case}.pst"
    audit_path = target / f"{case}.weights.audit.csv"
    registry_path = target / f"{case}_observation_registry.csv"
    design = json.loads((target / "joint_design.json").read_text(encoding="utf-8"))
    mapping_path = Path(design["water_response_objective"]["mapping_csv"])
    if not mapping_path.is_absolute():
        mapping_path = ROOT / mapping_path
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["season_id"] = mapping["season_id"].astype(str)
    mapping["treatment"] = pd.to_numeric(mapping["treatment"], errors="raise").astype(int)
    mapping["nitrogen_level"] = mapping["nitrogen_level"].astype(str).str.upper()

    pst = pyemu.Pst(str(pst_path))
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit.index = audit["obsnme"].astype(str).str.lower()
    registry.index = registry["obsnme"].astype(str).str.lower()
    summary: dict[str, dict[str, float]] = {}
    lam = ARMS[arm]["lambda_per_season"]
    if lam is not None:
        rows = registry.loc[_water_rows(registry)].copy()
        rows["treatment"] = pd.to_numeric(rows["treatment"], errors="raise").astype(int)
        rows = rows.merge(
            mapping[["season_id", "treatment", "nitrogen_level"]],
            on=["season_id", "treatment"], how="left", validate="many_to_one",
        )
        if rows["nitrogen_level"].isna().any():
            raise ValueError("W_RESPONSE registry contains treatments absent from water_n_mapping.csv")
        rows = rows.loc[rows["nitrogen_level"].isin(["N0", "N3"])].copy()
        lambda_per_stratum = float(lam) / 2.0
        for (season, nitrogen), group in rows.groupby(["season_id", "nitrogen_level"], sort=True):
            values = pd.to_numeric(group["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(values - values.mean()).sum())
            if not sst > 0:
                raise ValueError(f"{arm} {season}:{nitrogen}: non-positive SST")
            weight = float(math.sqrt(lambda_per_stratum / sst))
            for name in group["obsnme"].astype(str):
                key = name.lower()
                pst.observation_data.loc[key, "weight"] = weight
                audit.loc[key, ["weight", "weight_mode", "nse_lambda", "nse_sst"]] = [
                    weight, "season_nlevel_nse", lambda_per_stratum, sst
                ]
                registry.loc[key, ["weight", "weight_mode", "nse_lambda", "nse_sst"]] = [
                    weight, "season_nlevel_nse", lambda_per_stratum, sst
                ]
            summary[f"{season}:{nitrogen}"] = {
                "n": int(len(group)), "sst": sst,
                "lambda": lambda_per_stratum, "weight": weight,
            }

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


def _prepare(arm: str) -> Path:
    case = (
        f"e02_selected8_water_{arm}_{ARMS[arm]['label']}_80x4_20260818"
        f"{CASE_SUFFIX[arm]}"
    )
    target = ROOT / "workspace" / "runs" / case
    if target.exists() and (target / "water_nse_trial_contract.json").exists():
        return target
    if target.exists():
        raise RuntimeError(f"incomplete pre-existing trial directory requires removal: {target}")
    shutil.copytree(BASE_DIR, target, ignore=_ignore)
    replace_case(target, BASE_CASE, case)
    _parameter_subset(target)
    summary = _apply_weights(target, arm)
    design_path = target / "joint_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["design_id"] = f"selected8_water_nse_{arm.lower()}_20260818"
    design["water_response_objective"]["nitrogen_levels"] = ["N0", "N3"]
    # ``weighting`` is a schema enum consumed by MultiSeasonDesign and must
    # remain ``static`` or ``nse``.  The separate-SST implementation detail
    # belongs in nse_lambda_allocation, not in the enum itself.
    design["water_response_objective"]["weighting"] = "static" if arm == "A" else "nse"
    design["water_response_objective"]["nse_lambda"] = ARMS[arm]["lambda_per_season"]
    design["water_response_objective"]["nse_lambda_per_season"] = ARMS[arm]["lambda_per_season"]
    design["water_response_objective"]["nse_lambda_allocation"] = "equal_split_N0_N3"
    design["microtrial"] = {
        "arm": arm, "anchor_member": "192", "n_reals": N_REALS,
        "noptmax": NOPTMAX, "agents": AGENTS, "seed": SEED,
        "dry_cumulative_nse_guardrail": "each season decline <= 0.03 absolute versus arm A",
    }
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "water_nse_trial_contract.json").write_text(
        json.dumps({"case": case, "arm": arm, "settings": ARMS[arm], "weight_audit": summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--arm", choices=list(ARMS))
    args = parser.parse_args()
    arms = [args.arm] if args.arm else list(ARMS)
    replacements = []
    if not args.prepare_only:
        from tools.calibration.launch_dry_nse_formal_20260817 import _swap
        replacements = _swap()
    try:
        for arm in arms:
            target = _prepare(arm)
            print(json.dumps({"arm": arm, "run_dir": str(target)}, ensure_ascii=False))
            if not args.prepare_only:
                command = [
                    sys.executable, "tools/parallel/run_parallel.py", "--run-dir", str(target),
                    "--case", target.name, "--mode", "ies", "--n-agents", str(AGENTS),
                    "--port", str(PORTS[arm]), "--wait",
                ]
                rc = subprocess.run(command, cwd=ROOT, check=False).returncode
                if rc:
                    return int(rc)
    finally:
        if replacements:
            from tools.calibration.launch_dry_nse_formal_20260817 import _restore
            _restore(replacements)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
