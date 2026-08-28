"""Build the selected-treatment official IES run from the 20260817 parameter contract."""
from __future__ import annotations

import hashlib
import json
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

SOURCE_CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
CASE = "e02_selected8_fixedsoil_nse_official_200x6_20260818"
DESIGN = ROOT / "configs/runs/eggplant_e02_selected8_fixedsoil_nse_20260818.json"
N_REALS = 200
NOPTMAX = 6
SEED = 20260818
NSE_LAMBDA = 75.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def set_raw_dry_nse(pst: pyemu.Pst, run_dir: Path) -> dict[str, dict[str, float]]:
    registry_path = run_dir / f"{CASE}_observation_registry.csv"
    audit_path = run_dir / f"{CASE}.weights.audit.csv"
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()
    selected = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    if selected.empty or set(selected["season_id"].astype(str)) != {"25SP", "26SP"}:
        raise ValueError("raw cumulative dry-NSE observations are incomplete")
    result: dict[str, dict[str, float]] = {}
    for season, rows in selected.groupby("season_id", sort=True):
        values = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(values - values.mean()).sum())
        if sst <= 0:
            raise ValueError(f"{season}: dry cumulative SST must be positive")
        weight = float(np.sqrt(NSE_LAMBDA / sst))
        sigma = float(np.sqrt(sst / len(rows)))
        multiplier = weight * sigma
        for obs_name, row in rows.iterrows():
            value = float(row["raw_obsval"])
            pst.observation_data.loc[obs_name, ["obsval", "weight", "obgnme"]] = [value, weight, "drynse"]
            for table in (registry, audit):
                table.loc[obs_name, "obsval"] = value
                table.loc[obs_name, "weight"] = weight
                table.loc[obs_name, "sigma"] = sigma
                table.loc[obs_name, "sigma_source"] = "nse_sst_normalized_raw"
                table.loc[obs_name, "group_multiplier"] = multiplier
                table.loc[obs_name, "transform"] = "raw"
                table.loc[obs_name, "obgnme"] = "DRYNSE"
        result[str(season)] = {
            "n": int(len(rows)), "sst": sst, "lambda": NSE_LAMBDA,
            "weight": weight, "identity": "phi=75*(1-NSE)",
        }
    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")
    (run_dir / f"{CASE}.observation_transforms.json").write_text(
        json.dumps({"version": "observation_policy_v2", "files": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    target = ROOT / "workspace/runs" / CASE
    source_pst_path = ROOT / "workspace/runs" / SOURCE_CASE / f"{SOURCE_CASE}.pst"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
            "--variant", "official", "--case", CASE, "--design", str(DESIGN),
            "--bounds-id", "eggplant_e02_fixedsoil_formal_nse_20260817",
            "--noptmax", str(NOPTMAX), "--ies-num-reals", str(N_REALS),
            "--random-seed", str(SEED),
        ],
        cwd=ROOT, env=env, check=True,
    )

    pst_path = target / f"{CASE}.pst"
    pst = pyemu.Pst(str(pst_path))
    source = pyemu.Pst(str(source_pst_path))
    src_par = source.parameter_data
    active_source = set(src_par.index[~src_par.partrans.astype(str).str.lower().eq("fixed")])
    active_target = set(pst.parameter_data.index[~pst.parameter_data.partrans.astype(str).str.lower().eq("fixed")])
    if active_target != active_source:
        raise AssertionError(
            f"active parameter mismatch: missing={sorted(active_source-active_target)}, "
            f"extra={sorted(active_target-active_source)}"
        )
    copied_columns = ["partrans", "parchglim", "parval1", "parlbnd", "parubnd", "pargp", "scale", "offset"]
    pst.parameter_data.loc[sorted(active_source), copied_columns] = src_par.loc[sorted(active_source), copied_columns]
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options = dict(source.pestpp_options)
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS, "rand_seed": SEED,
        "ies_parameter_ensemble": f"{CASE}.0.par.csv",
        "ies_observation_ensemble": f"{CASE}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    dry_nse = set_raw_dry_nse(pst, target)
    pst.write(str(pst_path))

    params_path = target / f"{CASE}_params.csv"
    params = pd.read_csv(params_path)
    lookup = pst.parameter_data["parval1"].to_dict()
    params["value"] = params.apply(
        lambda row: lookup.get(str(row["name"]).lower(), row["value"]), axis=1
    )
    params.to_csv(params_path, index=False)

    par = pst.parameter_data
    bounds = pd.DataFrame({
        "name": par.index, "init": par.parval1, "lower": par.parlbnd, "upper": par.parubnd,
        "status": np.where(par.partrans.astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, bounds, SEED, method="sobol")
    ensemble_path = target / f"{CASE}.0.par.csv"
    write_ensemble_csv(ensemble, ensemble_path)
    observation_path, _, _ = _write_observation_noise_ensemble(
        pst_path, target / f"{CASE}.weights.audit.csv", target, CASE, N_REALS, SEED
    )

    design = json.loads((target / "joint_design.json").read_text(encoding="utf-8"))
    design["raw_dry_nse_override"] = {
        "enabled": True, "lambda_per_season": NSE_LAMBDA, "scale": "raw_cumulative"
    }
    (target / "joint_design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    obs = pst.observation_data
    weight_audit = pd.read_csv(
        target / f"{CASE}_group_weight_audit.csv", encoding="utf-8-sig"
    )
    response_budgets = {
        f"{row.season_id}:{row.variable_family}": float(row.phi_budget)
        for row in weight_audit.itertuples(index=False)
        if str(row.variable_family).upper() in {"N_RESPONSE", "W_RESPONSE"}
    }
    contract = {
        "schema_version": 1, "case": CASE, "source_case": SOURCE_CASE,
        "official_dssat_required": True, "n_reals": N_REALS, "noptmax": NOPTMAX, "agents": 6,
        "n_adjustable": int(pst.npar_adj), "active_parameter_configuration_exact_match": True,
        "treatments": {"25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]},
        "nitrogen_response": "N3-N0 within each selected water level",
        "water_response": {"25SP": "W3-W1", "26SP": "W2-W1"},
        "response_observation_counts": {
            "N_RESPONSE": int(obs.obgnme.astype(str).str.upper().str.contains("NRESP").sum()),
            "W_RESPONSE": int(obs.obgnme.astype(str).str.upper().str.contains("WRESP").sum()),
        },
        "response_phi_budgets": response_budgets,
        "dry_nse": dry_nse,
        "source_pst_sha256": sha256(source_pst_path),
        "parameter_ensemble_sha256": sha256(ensemble_path),
        "observation_ensemble_sha256": sha256(Path(observation_path)),
    }
    (target / "selected8_calibration_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
