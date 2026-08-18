"""Build corrected-data six-treatment PSTs for the four 2025-08 N-response DSSAT variants."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
OBS_TEMPLATE = ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_corrected"
TEMPLATES = {
    "a3": ROOT / "workspace/runs/a3_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804",
    "a4": ROOT / "workspace/runs/a4_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804",
}
VARIANTS = {
    "a3_0805": {
        "family": "a3",
        "exe": "windows/windows_a3_20260805/dscsm048_a3.exe",
        "spe": "windows/windows_a3_20260805/Genotype/TMGRO048.SPE",
    },
    "a4_0805": {
        "family": "a4",
        "exe": "windows/windows_a4_20260805/dscsm048_a4.exe",
        "spe": "windows/windows_a4_20260805/Genotype/TMGRO048.SPE",
    },
    "a3_nr_zp_0805": {
        "family": "a3",
        "exe": "windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe",
        "spe": "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE",
    },
    "a4_nr_zp_0805": {
        "family": "a4",
        "exe": "windows/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe",
        "spe": "windows/windows_a4_nr_zp_20260805/Genotype/TMGRO048.SPE",
    },
}


def _case(name: str) -> str:
    return f"e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_{name}"


def _copy_instruction(source: Path, target: Path, case: str, output: str) -> str:
    target_name = f"{case}_{output}.ins"
    shutil.copy2(source, target / target_name)
    return target_name


def _parameter_template(source: Path, target: Path, case: str, family: str) -> str:
    """Copy the old template while removing obsolete 0804 NUPQ injection."""
    old_case = source.name
    source_tpl = source / f"{old_case}_params.csv.tpl"
    lines = source_tpl.read_text(encoding="utf-8").splitlines()
    if family in {"a3", "a4"}:
        lines = [line for line in lines if not re.match(r"NUPQ,", line, flags=re.I)]
    name = f"{case}_params.csv.tpl"
    (target / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return name


def _build_variant(name: str, spec: dict[str, str]) -> Path:
    source = TEMPLATES[spec["family"]]
    target = ROOT / "workspace/runs" / _case(name)
    if target.exists():
        raise FileExistsError(target)
    if not source.is_dir() or not OBS_TEMPLATE.is_dir():
        raise FileNotFoundError(f"missing source: {source} or {OBS_TEMPLATE}")
    target.mkdir(parents=True)

    old_case = source.name
    old_pst = pyemu.Pst(str(source / f"{old_case}.pst"))
    corrected_pst = pyemu.Pst(str(OBS_TEMPLATE / f"{OBS_TEMPLATE.name}.pst"))

    # Start from the corrected observation contract: 400 observations, 298 active,
    # corrected harvest events, compacted soil-layer names and 40 N-response rows.
    old_pst.observation_data = corrected_pst.observation_data.copy()
    old_pst.model_input_data = pd.DataFrame(
        {"pest_file": [f"{_case(name)}_params.csv.tpl"], "model_file": [f"{_case(name)}_params.csv"]},
        index=[f"{_case(name)}_params.csv.tpl"],
    )

    # 0805 SPE contracts: A3 uses NUPK50/NUPCMN; A4 uses NUPK50/NUPAV.
    drop = "nupq"
    old_pst.parameter_data = old_pst.parameter_data.loc[
        old_pst.parameter_data.index.astype(str).str.lower() != drop
    ].copy()

    instruction_map: dict[str, str] = {}
    for output in (
        "PestEval.OUT",
        "PestJoint.OUT",
        "PestHarvest.OUT",
        "PestTmtGrow.OUT",
        "PestNResponse.OUT",
        "PestSoilWat.OUT",
    ):
        source_ins = OBS_TEMPLATE / f"{OBS_TEMPLATE.name}_{output}.ins"
        if not source_ins.is_file():
            raise FileNotFoundError(source_ins)
        instruction_map[output] = _copy_instruction(source_ins, target, _case(name), output)
    old_pst.model_output_data = pd.DataFrame(
        {"pest_file": list(instruction_map.values()), "model_file": list(instruction_map.keys())},
        index=list(instruction_map.values()),
    )

    design = json.loads((OBS_TEMPLATE / "six_treatment_design.json").read_text(encoding="utf-8"))
    case = _case(name)
    design["design_id"] = case
    design["custom_dssat_executable"] = str((ROOT / spec["exe"]).resolve())
    design["custom_spe"] = str((ROOT / spec["spe"]).resolve())
    design["seasons"][0]["bundle_manifest_sha256"] = "f8a249a4e6282b6b52b0101673a0d77abd531d5d3fedb12fb6a2a69a19352707"
    design["nitrogen_response_objective"]["mapping_csv"] = "configs/runs/e02_v2_25sp_water_n_mapping_corrected_20260805.csv"
    design["formal"] = {"n_reals": 150, "noptmax": 4, "initial_ensemble_method": "sobol"}
    (target / "six_treatment_design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(OBS_TEMPLATE / f"{OBS_TEMPLATE.name}.observation_transforms.json", target / f"{case}.observation_transforms.json")

    old_pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{(target / "six_treatment_design.json").as_posix()}" '
        f"--param-csv {case}_params.csv --harvest-var CHPDT --keep-nitrogen-outputs "
        f"--prefix {case} --observation-transform-config {case}.observation_transforms.json"
    ]
    old_pst.control_data.noptmax = 4
    old_pst.pestpp_options["ies_num_reals"] = "150"
    old_pst.pestpp_options["rand_seed"] = "20260805"

    tpl_name = _parameter_template(source, target, case, spec["family"])
    # Keep the corrected observation ensemble and registry exactly aligned with
    # the common e02 contract.
    ensemble_name = f"{case}.observation_ensemble.csv"
    shutil.copy2(OBS_TEMPLATE / f"{OBS_TEMPLATE.name}.observation_ensemble.csv", target / ensemble_name)
    old_pst.pestpp_options["ies_observation_ensemble"] = ensemble_name
    shutil.copy2(OBS_TEMPLATE / f"{OBS_TEMPLATE.name}_run_mapping.csv", target / f"{case}_run_mapping.csv")
    registry = pd.read_csv(OBS_TEMPLATE / f"{OBS_TEMPLATE.name}_observation_registry.csv")
    registry.to_csv(target / f"{case}_observation_registry.csv", index=False, encoding="utf-8-sig")

    # Copy only the parameter CSV contract and a manifest; never copy stale
    # PEST output/agent trees from the historical A3/A4 runs.
    params = pd.read_csv(source / f"{old_case}_params.csv")
    params = params[~params.name.astype(str).str.lower().eq("nupq")]
    params.to_csv(target / f"{case}_params.csv", index=False)
    old_pst.write(str(target / f"{case}.pst"))
    receipt = {
        "run_id": case,
        "variant": name,
        "parameter_template": str(source),
        "custom_executable": str((ROOT / spec["exe"]).resolve()),
        "custom_spe": str((ROOT / spec["spe"]).resolve()),
        "corrected_bundle_manifest_sha256": design["seasons"][0]["bundle_manifest_sha256"],
        "n_parameters": int(old_pst.npar),
        "n_parameters_adjustable": int(old_pst.npar_adj),
        "n_observations": int(old_pst.nobs),
        "n_observations_active": int((old_pst.observation_data.weight > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "removed_obsolete_parameter": "NUPQ",
        "status": "built",
    }
    (target / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return target


def main() -> None:
    for name, spec in VARIANTS.items():
        _build_variant(name, spec)


if __name__ == "__main__":
    main()
