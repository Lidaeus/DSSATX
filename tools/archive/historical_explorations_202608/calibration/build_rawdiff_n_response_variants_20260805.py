"""Build four custom-DSSAT PSTs under the 2025SP raw-difference contract."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
BASE_CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_6treat_150x4_20260805_base"
BASE_DIR = ROOT / "workspace/runs" / BASE_CASE
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_formal25sp_rawdiff_terminal_nresp01_soil02_20260805.json"
OBS_POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
BOUNDS = "eggplant_e02_v2_formal25sp_nreleased_20260802"
OLD_TEMPLATES = {
    "a3": ROOT / "workspace/runs/a3_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804",
    "a4": ROOT / "workspace/runs/a4_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804",
}
VARIANTS = {
    "a3_0805": ("a3", "windows/windows_a3_20260805/dscsm048_a3.exe", "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"),
    "a4_0805": ("a4", "windows/windows_a4_20260805/dscsm048_a4.exe", "windows/windows_a4_20260805/Genotype/TMGRO048.SPE"),
    "a3_nr_zp_0805": ("a3", "windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe", "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE"),
    "a4_nr_zp_0805": ("a4", "windows/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe", "windows/windows_a4_nr_zp_20260805/Genotype/TMGRO048.SPE"),
}


def case_name(variant: str) -> str:
    return f"e02_v2_rawdiff_terminal_nresp01_soil02_6treat_150x4_20260805_{variant}"


def _rename_base_files(target: Path, old_prefix: str, new_prefix: str) -> None:
    for path in list(target.iterdir()):
        if path.name.startswith(old_prefix):
            path.rename(target / path.name.replace(old_prefix, new_prefix, 1))


def _patch_parameter_template(source: Path, target: Path, case: str) -> tuple[str, str]:
    old_case = source.name
    tpl_lines = (source / f"{old_case}_params.csv.tpl").read_text(encoding="utf-8").splitlines()
    tpl_lines = [line for line in tpl_lines if not re.match(r"NUPQ,", line, flags=re.I)]
    tpl_name = f"{case}_params.csv.tpl"
    (target / tpl_name).write_text("\n".join(tpl_lines) + "\n", encoding="utf-8")

    params = pd.read_csv(source / f"{old_case}_params.csv")
    params = params[~params.name.astype(str).str.upper().eq("NUPQ")]
    params.to_csv(target / f"{case}_params.csv", index=False)
    return tpl_name, f"{case}_params.csv"


def build_variant(variant: str, family: str, exe: str, spe: str) -> Path:
    if not BASE_DIR.is_dir():
        raise FileNotFoundError(f"build the base PST first: {BASE_DIR}")
    source = OLD_TEMPLATES[family]
    old_case = source.name
    case = case_name(variant)
    target = ROOT / "workspace/runs" / case
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(BASE_DIR, target)
    _rename_base_files(target, BASE_CASE, case)

    base_pst = pyemu.Pst(str(target / f"{case}.pst"))
    old_pst = pyemu.Pst(str(source / f"{old_case}.pst"))
    old_params = old_pst.parameter_data.copy()
    old_params = old_params.loc[old_params.index.astype(str).str.upper() != "NUPQ"].copy()
    base_pst.parameter_data = old_params
    tpl_name, csv_name = _patch_parameter_template(source, target, case)
    base_pst.model_input_data = pd.DataFrame(
        {"pest_file": [tpl_name], "model_file": [csv_name]}, index=[tpl_name]
    )

    # Rename all input/output references after copying the base artifacts.
    model_outputs = []
    for _, row in base_pst.model_output_data.iterrows():
        pest_file = str(row["pest_file"]).replace(BASE_CASE, case, 1)
        model_outputs.append({"pest_file": pest_file, "model_file": row["model_file"]})
    base_pst.model_output_data = pd.DataFrame(model_outputs)
    base_pst.pestpp_options["ies_observation_ensemble"] = f"{case}.observation_ensemble.csv"

    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    design["design_id"] = case
    design["custom_dssat_executable"] = str((ROOT / exe).resolve())
    design["custom_spe"] = str((ROOT / spe).resolve())
    design_path = target / "six_treatment_design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base_pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{design_path.as_posix()}" --param-csv {csv_name} '
        f"--harvest-var CHPDT --keep-nitrogen-outputs --prefix {case}"
    ]
    base_pst.control_data.noptmax = 4
    base_pst.pestpp_options["ies_num_reals"] = "150"
    base_pst.pestpp_options["rand_seed"] = "20260805"
    base_pst.write(str(target / f"{case}.pst"))

    # Keep a compact, auditable receipt; all observation/weight artifacts came
    # from the new base contract and have already been renamed above.
    receipt = {
        "run_id": case,
        "objective_contract": "raw_scale_difference_plus_terminal_20260805",
        "family": family,
        "custom_executable": str((ROOT / exe).resolve()),
        "custom_spe": str((ROOT / spe).resolve()),
        "bounds_id": BOUNDS,
        "n_parameters": int(base_pst.npar),
        "n_parameters_adjustable": int(base_pst.npar_adj),
        "n_observations": int(base_pst.nobs),
        "n_observations_active": int((base_pst.observation_data.weight > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "removed_obsolete_parameter": "NUPQ",
        "status": "built",
    }
    (target / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False))
    return target


def main() -> None:
    for variant, (family, exe, spe) in VARIANTS.items():
        build_variant(variant, family, exe, spe)


if __name__ == "__main__":
    main()
