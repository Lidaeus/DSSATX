"""Build the official 200-realization x 6-iteration dry-NSE confirmation run."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.finalize_calibration import _upsert_manifest_fields
from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv
from src.calibration.stage_representative import clear_stage_representative_manifest_fields
from tools.calibration.prepare_dry_nse_factorial_20260815 import replace_case

BASE_CASE = "e02_fs2x2_nse_bnd_120x4_20260815"
CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
SOURCE_BOUNDS = "eggplant_e02_fixedsoil_factorial_selective_20260815"
BOUNDS_ID = "eggplant_e02_fixedsoil_formal_nse_20260817"
N_REALS = 200
NOPTMAX = 6
SEED = 20260817
NSE_LAMBDA = 75.0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    dynamic_dirs = {"_agents", "manager", "ies_quality", "calibration_finalize", "deterministic_candidates"}
    ignored: set[str] = set()
    for name in names:
        low = name.lower()
        if name in dynamic_dirs or low.startswith(("final_", "failed_dssat")):
            ignored.add(name)
        elif low in {
            "run_status.json", "multiseason_run_status.json", "agent_failure_evidence.json",
            "member_failure_evidence.json", "factorial_contract.json", "formal_pipeline_status.json",
        }:
            ignored.add(name)
        elif low.endswith((".rec", ".rmr", ".rns", ".rei", ".res", ".jcb", ".log", ".pid", ".stp", ".out")):
            ignored.add(name)
        elif ".phi." in low or low.endswith((".base.par", ".base.rei", ".0.par.csv", ".observation_ensemble.csv", ".observation_ensemble.json")):
            ignored.add(name)
        elif any(f".{i}.{kind}.csv" in low for i in range(20) for kind in ("par", "obs", "pcs", "pdc")):
            ignored.add(name)
    return ignored


def _write_bounds() -> Path:
    folder = ROOT / "data/parameter_registry/bounds_frozen/eggplant"
    source = folder / f"{SOURCE_BOUNDS}.csv"
    target = folder / f"{BOUNDS_ID}.csv"
    before = pd.read_csv(source, encoding="utf-8-sig")
    after = before.copy()
    names = after["name"].astype(str).str.lower()
    pht, pod = names.eq("phtmax"), names.eq("podur")
    if int(pht.sum()) != 1 or int(pod.sum()) != 1:
        raise ValueError("Frozen bounds must contain exactly one PHTMAX and PODUR")
    after.loc[pht, ["lower", "upper"]] = [45.0, 75.0]
    after.loc[pod, ["lower", "upper"]] = [12.0, 58.0]
    if "notes" in after:
        after.loc[pht, "notes"] = "20260817 formal confirmation: frozen PHTMAX 45-75"
        after.loc[pod, "notes"] = "20260817 formal confirmation: frozen PODUR 12-58"
    compare_cols = [c for c in before.columns if c != "notes"]
    untouched = ~(pht | pod)
    if not before.loc[untouched, compare_cols].reset_index(drop=True).equals(after.loc[untouched, compare_cols].reset_index(drop=True)):
        raise AssertionError("A non-approved parameter bound changed")
    after.to_csv(target, index=False, encoding="utf-8")
    return target


def _audit_objective(run_dir: Path, pst: pyemu.Pst) -> dict:
    registry = pd.read_csv(run_dir / f"{CASE}_observation_registry.csv", encoding="utf-8-sig")
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    if len(dry) != 160 or (dry["sim_token"] == "CHPDTS_T").sum() != 138:
        raise AssertionError("Expected 138 intermediate plus 22 terminal cumulative-dry observations")
    if set(dry["transform"].astype(str).str.lower()) != {"raw"}:
        raise AssertionError("Formal dry-NSE observations must remain on the raw cumulative scale")
    seasons = {}
    for season, rows in dry.groupby("season_id", sort=True):
        obs = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(obs - obs.mean()).sum())
        names = rows["obsnme"].astype(str).str.lower().tolist()
        weights = pd.to_numeric(pst.observation_data.loc[names, "weight"], errors="raise").to_numpy(float)
        expected = np.sqrt(NSE_LAMBDA / sst)
        if not np.allclose(weights, expected, rtol=5e-7, atol=1e-12):
            raise AssertionError(f"{season}: weights do not implement lambda*(1-NSE)")
        seasons[str(season)] = {"n": len(rows), "sst": sst, "lambda": NSE_LAMBDA, "weight": expected}
    return {"family": "DRY_CUMULATIVE", "raw_observations": len(dry), "identity": "phi_season = 75 * (1 - NSE_season)", "seasons": seasons}


def main() -> int:
    source = ROOT / "workspace/runs" / BASE_CASE
    target = ROOT / "workspace/runs" / CASE
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing formal run: {target}")
    bounds_path = _write_bounds()
    shutil.copytree(source, target, ignore=_copy_ignore)
    replace_case(target, BASE_CASE, CASE)
    manifest_path = target / "run_manifest.yaml"
    clear_stage_representative_manifest_fields(manifest_path)

    pst_path = target / f"{CASE}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{CASE}.0.par.csv",
        "ies_observation_ensemble": f"{CASE}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    pst.parameter_data.loc["phtmax", ["parlbnd", "parubnd"]] = [45.0, 75.0]
    pst.parameter_data.loc["podur", ["parlbnd", "parubnd"]] = [12.0, 58.0]
    pst.write(str(pst_path))

    par = pst.parameter_data
    bounds = pd.DataFrame({
        "name": par.index, "init": par["parval1"], "lower": par["parlbnd"], "upper": par["parubnd"],
        "status": np.where(par["partrans"].astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, bounds, SEED, method="sobol")
    par_path = target / f"{CASE}.0.par.csv"
    write_ensemble_csv(ensemble, par_path)
    from src.calibration.build_pest import _write_observation_noise_ensemble
    obs_path, _, _ = _write_observation_noise_ensemble(
        pst_path, target / f"{CASE}.weights.audit.csv", target, CASE, N_REALS, SEED
    )

    design_path = target / "joint_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["design_id"] = "fixedsoil_dry_nse_formal_confirmation_20260817"
    design["bounds_id"] = BOUNDS_ID
    design["formal_confirmation"] = {
        "dssat": "official_v4.8", "n_reals": N_REALS, "noptmax": NOPTMAX,
        "agents": 6, "initial_ensemble": "sobol", "seed": SEED,
        "nse_lambda_per_season": NSE_LAMBDA,
        "candidate_rules": ["minimum_phi", "highest_nse_within_final_phi_q10", "final_ensemble_parameter_median"],
    }
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _upsert_manifest_fields(manifest_path, {
        "run_id": CASE, "design_id": design["design_id"], "bounds_id": BOUNDS_ID,
        "formal_confirmation": True, "dssat_variant": "official_v4.8",
        "raw_dry_nse": True, "nse_lambda_per_season": NSE_LAMBDA,
        "ies_num_reals": N_REALS, "noptmax": NOPTMAX, "n_agents": 6,
        "initial_ensemble_method": "sobol", "initial_ensemble_seed": SEED,
        "shared_ensemble_seed": SEED, "observation_noise_seed": SEED,
        "observation_ensemble": Path(obs_path).name,
    })
    objective = _audit_objective(target, pst)
    contract = {
        "schema_version": 1, "case": CASE, "base_case": BASE_CASE,
        "official_dssat_required": True, "n_reals": N_REALS, "noptmax": NOPTMAX, "agents": 6,
        "bounds_id": BOUNDS_ID, "bounds": {"PHTMAX": [45.0, 75.0], "PODUR": [12.0, 58.0]},
        "other_bounds_unchanged_from": SOURCE_BOUNDS, "objective": objective,
        "parameter_ensemble_sha256": _sha256(par_path), "observation_ensemble_sha256": _sha256(Path(obs_path)),
    }
    (target / "formal_confirmation_contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    print(f"run_dir={target}")
    print(f"frozen_bounds={bounds_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
