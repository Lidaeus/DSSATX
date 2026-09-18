"""Prepare a clean matched 2x2 factorial for dry-NSE objective and bounds."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.stage_representative import clear_stage_representative_manifest_fields

BASE_CASE = "e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260814"
BASE_BOUNDS = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
NEW_BOUNDS = "eggplant_e02_fixedsoil_factorial_selective_20260815"
N_REALS = 120
NOPTMAX = 4
SEED = 20260815
NSE_LAMBDA = 75.0

ARMS = (
    ("r0", False, False),
    ("nse", True, False),
    ("bnd", False, True),
    ("nse_bnd", True, True),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    dynamic_dirs = {"_agents", "manager", "ies_quality", "calibration_finalize"}
    dynamic_files = {
        "run_status.json", "multiseason_run_status.json", "background_launch.pid",
        "background_launch.stdout.log", "background_launch.stderr.log",
        "agent_failure_evidence.json", "member_failure_evidence.json",
    }
    iteration_re = re.compile(rf"^{re.escape(BASE_CASE)}\.\d+\.(?:par|obs|pcs|pdc)\.csv$", re.I)
    for name in names:
        low = name.lower()
        if name in dynamic_dirs or low.startswith(("final_", "failed_dssat")):
            ignored.add(name)
        elif name in dynamic_files or iteration_re.match(name):
            ignored.add(name)
        elif low.endswith((".rec", ".rmr", ".rns", ".rei", ".res", ".jcb", ".log", ".pid", ".stp", ".out")):
            ignored.add(name)
        elif ".phi." in low or low.endswith((".base.par", ".base.rei")):
            ignored.add(name)
        elif low.endswith(".observation_ensemble.csv") or low.endswith(".observation_ensemble.json"):
            ignored.add(name)
        elif low.endswith(".0.par.csv"):
            ignored.add(name)
    return ignored


def replace_case(root: Path, old: str, new: str) -> None:
    old_b = old.encode()
    new_b = new.encode()
    for path in sorted(root.rglob("*"), key=lambda p: len(str(p)), reverse=True):
        if path.is_file():
            data = path.read_bytes()
            if old_b in data:
                path.write_bytes(data.replace(old_b, new_b))
        renamed = path.name.replace(old, new)
        if renamed != path.name:
            path.rename(path.with_name(renamed))


def write_frozen_bounds() -> Path:
    source = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{BASE_BOUNDS}.csv"
    target = source.with_name(f"{NEW_BOUNDS}.csv")
    frame = pd.read_csv(source, encoding="utf-8-sig")
    pht = frame["name"].astype(str).str.lower().eq("phtmax")
    pod = frame["name"].astype(str).str.lower().eq("podur")
    if pht.sum() != 1 or pod.sum() != 1:
        raise ValueError("Expected exactly one PHTMAX and PODUR row in frozen bounds")
    frame.loc[pht, ["lower", "upper"]] = [45.0, 75.0]
    frame.loc[pod, "lower"] = 20.0
    frame.loc[pht, "notes"] = "20260815 matched factorial: symmetric PHTMAX release after boundary reversal"
    frame.loc[pod, "notes"] = "20260815 matched factorial: selective lower release after persistent pressure at 30 and 25"
    frame.to_csv(target, index=False, encoding="utf-8")
    return target


def set_nse_objective(pst: pyemu.Pst, run_dir: Path, case: str) -> dict[str, dict[str, float]]:
    registry_path = run_dir / f"{case}_observation_registry.csv"
    audit_path = run_dir / f"{case}.weights.audit.csv"
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()
    selected = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    if len(selected) != 160 or (selected["sim_token"] == "CHPDTS_T").sum() != 138:
        raise ValueError("Dry NSE contract requires 138 intermediate + 22 terminal observations")

    result: dict[str, dict[str, float]] = {}
    for season, rows in selected.groupby("season_id", sort=True):
        values = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(values - values.mean()).sum())
        n = len(rows)
        weight = float(np.sqrt(NSE_LAMBDA / sst))
        sigma = float(np.sqrt(sst / n))
        group_multiplier = float(weight * sigma)
        for obs_name, row in rows.iterrows():
            value = float(row["raw_obsval"])
            if obs_name not in pst.observation_data.index:
                raise KeyError(f"PST lacks dry observation {obs_name}")
            pst.observation_data.loc[obs_name, ["obsval", "weight", "obgnme"]] = [value, weight, "drynse"]
            for table in (registry, audit):
                table.loc[obs_name, "obsval"] = value
                table.loc[obs_name, "weight"] = weight
                table.loc[obs_name, "sigma"] = sigma
                table.loc[obs_name, "sigma_source"] = "nse_sst_normalized_raw"
                table.loc[obs_name, "group_multiplier"] = group_multiplier
                table.loc[obs_name, "transform"] = "raw"
                table.loc[obs_name, "obgnme"] = "DRYNSE"
        # Numerical identity check on a non-zero deterministic residual vector.
        simulated = values + np.linspace(-50.0, 50.0, n)
        weighted_phi = float(np.square((simulated - values) * weight).sum())
        nse = 1.0 - float(np.square(simulated - values).sum() / sst)
        expected = NSE_LAMBDA * (1.0 - nse)
        if not np.isclose(weighted_phi, expected, rtol=1e-12, atol=1e-12):
            raise AssertionError(f"NSE/Phi identity failed for {season}")
        result[str(season)] = {
            "n": n, "sst": sst, "lambda": NSE_LAMBDA, "weight": weight,
            "sigma": sigma, "group_multiplier": group_multiplier,
            "identity_check_phi": weighted_phi, "identity_check_expected": expected,
        }

    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")
    # No transformation: CHPDTS_T remains raw in PestHarvest.OUT for NSE arms.
    transform_path = run_dir / f"{case}.observation_transforms.json"
    transform_path.write_text(
        json.dumps({"version": "observation_policy_v2", "files": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def update_metadata(run_dir: Path, case: str, arm: str, nse: bool, bounds: bool) -> None:
    design_path = run_dir / "joint_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["design_id"] = f"fixedsoil_dry_nse_factorial_{arm}_20260815"
    design["bounds_id"] = NEW_BOUNDS if bounds else BASE_BOUNDS
    design["factorial_contract"] = {
        "arm": arm, "raw_dry_nse": nse, "released_bounds": bounds,
        "nse_lambda_per_season": NSE_LAMBDA if nse else None,
        "shared_parameter_ensemble_seed": SEED,
        "shared_standard_normal_noise_seed": SEED,
        "n_reals": N_REALS, "noptmax": NOPTMAX,
    }
    if nse:
        # Keep the schema-supported mode consumed by MultiSeasonDesign.  The
        # factorial objective override is carried separately and implemented
        # in the PST weights plus the empty transform config.
        design["harvest_dry_objective"]["mode"] = "increment_plus_terminal"
        design["factorial_dry_nse_override"] = {
            "enabled": True, "mode": "raw_cumulative_nse_equivalent",
            "variable": "CHPDT", "lambda_per_season": NSE_LAMBDA,
        }
    design_path.write_text(json.dumps(design, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_path = run_dir / "run_manifest.yaml"
    clear_stage_representative_manifest_fields(manifest_path)
    text = manifest_path.read_text(encoding="utf-8")
    text += (
        f"\nfactorial_arm: '{arm}'\nraw_dry_nse: {str(nse).lower()}\n"
        f"released_bounds: {str(bounds).lower()}\nnse_lambda_per_season: {NSE_LAMBDA if nse else 'null'}\n"
        f"bounds_id: '{NEW_BOUNDS if bounds else BASE_BOUNDS}'\n"
        f"shared_ensemble_seed: {SEED}\nies_num_reals: {N_REALS}\nnoptmax: {NOPTMAX}\n"
    )
    manifest_path.write_text(text, encoding="utf-8")


def prepare_arm(base_dir: Path, out_root: Path, arm: str, nse: bool, bounds: bool) -> tuple[Path, pyemu.Pst, dict]:
    case = f"e02_fs2x2_{arm}_120x4_20260815"
    target = out_root / case
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(base_dir, target, ignore=_copy_ignore)
    replace_case(target, BASE_CASE, case)
    pst_path = target / f"{case}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options["ies_num_reals"] = N_REALS
    pst.pestpp_options["rand_seed"] = SEED
    pst.pestpp_options["ies_parameter_ensemble"] = f"{case}.0.par.csv"
    pst.pestpp_options["ies_observation_ensemble"] = f"{case}.observation_ensemble.csv"
    pst.pestpp_options["ies_include_base"] = "false"
    if bounds:
        pst.parameter_data.loc["phtmax", ["parlbnd", "parubnd"]] = [45.0, 75.0]
        pst.parameter_data.loc["podur", "parlbnd"] = 20.0
    nse_audit = set_nse_objective(pst, target, case) if nse else {}
    pst.write(str(pst_path))
    update_metadata(target, case, arm, nse, bounds)
    contract = {
        "schema_version": 1, "case": case, "arm": arm,
        "raw_dry_nse": nse, "released_bounds": bounds,
        "n_reals": N_REALS, "noptmax": NOPTMAX, "agents": 6,
        "shared_parameter_ensemble_seed": SEED,
        "shared_standard_normal_noise_seed": SEED,
        "nse_lambda_per_season": NSE_LAMBDA if nse else None,
        "nse_audit": nse_audit,
        "bounds": {"phtmax": [45.0, 75.0], "podur": [20.0, 58.0]} if bounds else "baseline",
        "stale_output_count_at_build": 0,
    }
    return target, pst, contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(ROOT / "workspace/runs" / BASE_CASE))
    parser.add_argument("--out-root", default=str(ROOT / "workspace/runs"))
    args = parser.parse_args()
    base_dir = Path(args.base).resolve()
    out_root = Path(args.out_root).resolve()
    frozen = write_frozen_bounds()

    prepared = [prepare_arm(base_dir, out_root, *spec) for spec in ARMS]
    from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv
    reference_pst = prepared[0][1]
    par = reference_pst.parameter_data
    bounds_frame = pd.DataFrame({
        "name": par.index, "init": par["parval1"], "lower": par["parlbnd"],
        "upper": par["parubnd"],
        "status": np.where(par["partrans"].astype(str).eq("fixed"), "fixed", "active"),
    })
    shared = generate_lhs_ensemble(N_REALS, bounds_frame, SEED, method="sobol")

    from src.calibration.build_pest import _write_observation_noise_ensemble
    z_reference: pd.DataFrame | None = None
    summary = []
    for target, pst, contract in prepared:
        case = target.name
        par_path = target / f"{case}.0.par.csv"
        write_ensemble_csv(shared, par_path)
        noise_path, _, _ = _write_observation_noise_ensemble(
            target / f"{case}.pst", target / f"{case}.weights.audit.csv",
            target, case, N_REALS, SEED,
        )
        noise = pd.read_csv(noise_path).set_index("real_name")
        audit = pd.read_csv(target / f"{case}.weights.audit.csv")
        active = pst.observation_data[pst.observation_data["weight"] > 0]
        audit["key"] = audit["obsnme"].astype(str).str.lower()
        audit = audit.set_index("key")
        names = list(active.index)
        sigma = pd.to_numeric(audit.loc[names, "sigma"], errors="raise")
        observed = pd.to_numeric(active.loc[names, "obsval"], errors="raise")
        z = (noise.loc[:, names] - observed.to_numpy()) / sigma.to_numpy()
        if z_reference is None:
            z_reference = z
        elif not np.allclose(z.to_numpy(), z_reference.to_numpy(), rtol=0.0, atol=2e-8):
            raise AssertionError(f"Standardized observation noise is not shared for {case}")
        contract["shared_parameter_ensemble_sha256"] = sha256(par_path)
        contract["observation_ensemble_sha256"] = sha256(Path(noise_path))
        contract["standardized_noise_max_abs_difference"] = 0.0 if z_reference is z else float(np.max(np.abs(z.to_numpy() - z_reference.to_numpy())))
        contract["frozen_bounds_path"] = str(frozen.relative_to(ROOT)).replace("\\", "/")
        (target / "factorial_contract.json").write_text(
            json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        summary.append({"case": case, "arm": contract["arm"], "run_dir": str(target)})
        print(case)
    (out_root / "e02_fs2x2_20260815_manifest.json").write_text(
        json.dumps({"schema_version": 1, "created_by": Path(__file__).name, "runs": summary}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
