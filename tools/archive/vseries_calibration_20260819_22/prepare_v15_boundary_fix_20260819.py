"""Build the v15 boundary pressure fix IES run on corrected spring bundles."""
from __future__ import annotations

import hashlib
import json
import math
import os
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
from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv

CASE = "e02_v15_boundary_fix_official_200x6_20260819"
DESIGN = ROOT / "configs/runs/eggplant_e02_v15_boundary_fix_20260819.json"
BOUNDS_ID = "eggplant_e02_v15_boundary_pressure_fix_20260819"
BOUNDS = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
SOURCE_CASE = "e02_selected8_water_formal_measuredmoisture_official_200x6_20260819"
SOURCE_REALIZATION = "42"
N_REALS = 200
NOPTMAX = 6
SEED = 20260819

DRY_LAMBDA = 75.0
WATER_LAMBDA_PER_SEASON = 1.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_anchor() -> dict[str, float]:
    source = ROOT / "workspace/runs" / SOURCE_CASE / f"{SOURCE_CASE}.6.par.csv"
    frame = pd.read_csv(source)
    real_col = frame.columns[0]
    row = frame.loc[
        frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(SOURCE_REALIZATION)
    ]
    if len(row) != 1:
        raise ValueError(f"expected source realization {SOURCE_REALIZATION} exactly once in {source}")
    return {
        str(key).lower(): float(value)
        for key, value in row.iloc[0].items()
        if key != real_col and pd.notna(value)
    }


def _nse_weights(
    pst: pyemu.Pst,
    registry: pd.DataFrame,
    audit: pd.DataFrame,
    *,
    run_dir: Path,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()

    dry_summary: dict[str, dict[str, float]] = {}
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    for season, rows in dry.groupby("season_id", sort=True):
        values = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(values - values.mean()).sum())
        if sst <= 0:
            raise ValueError(f"{season}: dry cumulative SST must be positive")
        weight = float(math.sqrt(DRY_LAMBDA / sst))
        sigma = float(math.sqrt(sst / len(rows)))
        for name, row in rows.iterrows():
            value = float(row["raw_obsval"])
            pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [value, weight, "drynse"]
            for table in (registry, audit):
                table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                    value, weight, sigma, "nse_sst_normalized_raw", "raw", "DRYNSE"
                ]
                table.loc[name, "group_multiplier"] = weight * sigma
        dry_summary[str(season)] = {
            "n": int(len(rows)), "sst": sst, "lambda": DRY_LAMBDA, "weight": weight,
        }

    design = json.loads((run_dir / "joint_design.json").read_text(encoding="utf-8"))
    mapping_path = Path(design["water_response_objective"]["mapping_csv"])
    if not mapping_path.is_absolute():
        mapping_path = ROOT / mapping_path
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["season_id"] = mapping["season_id"].astype(str)
    mapping["treatment"] = pd.to_numeric(mapping["treatment"], errors="raise").astype(int)
    mapping["nitrogen_level"] = mapping["nitrogen_level"].astype(str).str.upper()
    water = registry.loc[registry["obgnme"].astype(str).str.upper().str.contains("WRESP")].copy()
    water["treatment"] = pd.to_numeric(water["treatment"], errors="raise").astype(int)
    water = water.merge(
        mapping[["season_id", "treatment", "nitrogen_level"]],
        on=["season_id", "treatment"], how="left", validate="many_to_one",
    )
    if water["nitrogen_level"].isna().any():
        raise ValueError("W_RESPONSE observations contain unmapped treatments")
    water = water.loc[water["nitrogen_level"].isin(["N0", "N3"])]
    water_summary: dict[str, dict[str, float]] = {}
    lambda_per_stratum = WATER_LAMBDA_PER_SEASON / 2.0
    for (season, nitrogen), rows in water.groupby(["season_id", "nitrogen_level"], sort=True):
        values = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(values - values.mean()).sum())
        if sst <= 0:
            raise ValueError(f"{season}:{nitrogen}: W_RESPONSE SST must be positive")
        weight = float(math.sqrt(lambda_per_stratum / sst))
        for raw_name in rows["obsnme"].astype(str):
            name = raw_name.lower()
            pst.observation_data.loc[name, "weight"] = weight
            for table in (registry, audit):
                table.loc[name, ["weight", "weight_mode", "nse_lambda", "nse_sst"]] = [
                    weight, "season_nlevel_nse", lambda_per_stratum, sst
                ]
        water_summary[f"{season}:{nitrogen}"] = {
            "n": int(len(rows)), "sst": sst, "lambda": lambda_per_stratum, "weight": weight,
        }
    return dry_summary, water_summary


def main() -> int:
    run_dir = ROOT / "workspace/runs" / CASE
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite {run_dir}")
    if not BOUNDS.is_file():
        raise FileNotFoundError(f"bounds {BOUNDS} not found")

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"[1/6] Running base PST build...")
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
            "--variant", "official", "--case", CASE, "--design", str(DESIGN),
            "--bounds-id", BOUNDS_ID, "--noptmax", str(NOPTMAX),
            "--ies-num-reals", str(N_REALS), "--random-seed", str(SEED),
        ],
        cwd=ROOT, env=env, check=True,
    )

    print(f"[2/6] Updating parameter initial values and bounds from frozen bounds...")
    pst_path = run_dir / f"{CASE}.pst"
    audit_path = run_dir / f"{CASE}.weights.audit.csv"
    registry_path = run_dir / f"{CASE}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    frozen = pd.read_csv(BOUNDS, encoding="utf-8-sig")
    frozen["name"] = frozen["name"].astype(str).str.lower()
    frozen = frozen.set_index("name")
    for name in pst.parameter_data.index:
        if name in frozen.index:
            status = str(frozen.at[name, "status"]).lower()
            if status == "fixed":
                pst.parameter_data.at[name, "partrans"] = "fixed"
                pst.parameter_data.at[name, "parval1"] = float(frozen.at[name, "init"])
                pst.parameter_data.at[name, "parlbnd"] = float(frozen.at[name, "lower"])
                pst.parameter_data.at[name, "parubnd"] = float(frozen.at[name, "upper"])
            else:
                value = float(frozen.at[name, "init"])
                lower = float(frozen.at[name, "lower"])
                upper = float(frozen.at[name, "upper"])
                pst.parameter_data.at[name, "parlbnd"] = lower
                pst.parameter_data.at[name, "parubnd"] = upper
                pst.parameter_data.at[name, "parval1"] = min(max(value, lower), upper)

    print(f"[3/6] Applying NSE weights...")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    dry_summary, water_summary = _nse_weights(pst, registry, audit, run_dir=run_dir)
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{CASE}.0.par.csv",
        "ies_observation_ensemble": f"{CASE}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    pst.write(str(pst_path))
    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")
    (run_dir / f"{CASE}.observation_transforms.json").write_text(
        json.dumps({"version": "observation_policy_v2", "files": {}}, indent=2) + "\n",
        encoding="utf-8",
    )

    params_path = run_dir / f"{CASE}_params.csv"
    params = pd.read_csv(params_path)
    lookup = pst.parameter_data["parval1"].to_dict()
    params["value"] = params.apply(
        lambda row: lookup.get(str(row["name"]).lower(), row["value"]), axis=1
    )
    params.to_csv(params_path, index=False)

    print(f"[4/6] Generating initial parameter ensemble with Sobol sampling + anchor member...")
    par = pst.parameter_data
    ensemble_bounds = pd.DataFrame({
        "name": par.index,
        "init": par.parval1,
        "lower": par.parlbnd,
        "upper": par.parubnd,
        "status": np.where(par.partrans.astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, ensemble_bounds, SEED, method="sobol")
    anchor = _source_anchor()
    real_col = ensemble.columns[0]
    first = ensemble.index[0]
    for name in ensemble.columns[1:]:
        key = str(name).lower()
        if key in anchor:
            lower = float(par.at[key, "parlbnd"])
            upper = float(par.at[key, "parubnd"])
            ensemble.at[first, name] = min(max(anchor[key], lower), upper)
    ensemble.at[first, real_col] = f"anchor_member{SOURCE_REALIZATION}"
    ensemble_path = run_dir / f"{CASE}.0.par.csv"
    write_ensemble_csv(ensemble, ensemble_path)

    print(f"[5/6] Generating observation noise ensemble...")
    observation_path, _, _ = _write_observation_noise_ensemble(
        pst_path, audit_path, run_dir, CASE, N_REALS, SEED
    )

    print(f"[6/6] Finalizing run manifest and contract...")
    design = json.loads((run_dir / "joint_design.json").read_text(encoding="utf-8"))
    design["raw_dry_nse_override"] = {
        "enabled": True, "lambda_per_season": DRY_LAMBDA, "scale": "raw_cumulative"
    }
    (run_dir / "joint_design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle_manifests = {
        season["season_id"]: _sha256(Path(season["bundle_path"]) / "input_manifest.json")
        for season in design["seasons"]
    }
    contract = {
        "schema_version": 1,
        "case": CASE,
        "source_case": SOURCE_CASE,
        "source_realization": SOURCE_REALIZATION,
        "official_dssat_required": True,
        "n_reals": N_REALS,
        "noptmax": NOPTMAX,
        "agents": 6,
        "n_adjustable": int(pst.npar_adj),
        "treatments": {"25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]},
        "bundle_manifest_sha256": bundle_manifests,
        "fruit_moisture_contract": "measured_nearest_by_plot_date_for_25SP_and_26SP",
        "dry_nse": dry_summary,
        "water_response_nse": water_summary,
        "parameter_ensemble_sha256": _sha256(ensemble_path),
        "observation_ensemble_sha256": _sha256(Path(observation_path)),
    }
    (run_dir / "v15_boundary_fix_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    print(f"\nTask built successfully in: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
