"""Rebuild the 20260803 six-treatment E02 case with corrected 25SP data.

The archived retry3 PST is retained as the parameter-contract template
(108 total / 101 adjustable parameters).  Observation values, weights,
instructions and the IES observation ensemble are rebuilt from the corrected
8-treatment base PST, then compacted to the original six-treatment order.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
import pandas as pd
import pyemu

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build_six_treatment_nresp_pst import _transform_instruction


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260803_retry3"
TEMPLATE_CASE = TEMPLATE.name
BASE = ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_200x5_20260805_corrected_base"
BASE_CASE = BASE.name
TARGET_CASE = "e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_corrected"
TARGET = ROOT / "workspace/runs" / TARGET_CASE
RUN_RENUMBER = {8: 1, 7: 2, 6: 3, 4: 4, 3: 5, 2: 6}
TREATMENTS = (13, 12, 11, 5, 4, 3)


def _rename_run(name: str) -> str:
    match = re.search(r"_R(\d+)(?=_|$)", name, flags=re.I)
    if not match or int(match.group(1)) not in RUN_RENUMBER:
        return name
    return re.sub(rf"_R{int(match.group(1))}(?=_|$)", f"_R{RUN_RENUMBER[int(match.group(1))]}", name, flags=re.I)


def _rename_observation(name: str) -> str:
    """Compact run and soil-layer tokens to match six-run DSSAT output."""
    match = re.search(r"_R(\d+)(?=_|$)", name, flags=re.I)
    if match is None or int(match.group(1)) not in RUN_RENUMBER:
        return name
    old_run = int(match.group(1))
    new_run = RUN_RENUMBER[old_run]
    renamed = _rename_run(name)
    token = re.search(r"_SW(\d{4})([SM])_R\d+", renamed, flags=re.I)
    if token is None:
        return renamed
    old_token = int(token.group(1))
    new_token = old_token - (old_run - new_run) * 10
    if not 1 <= new_token <= 60:
        raise ValueError(f"unexpected soil token {old_token} for R{old_run}")
    return re.sub(
        rf"_SW{old_token:04d}([SM])_R{new_run}",
        f"_SW{new_token:04d}\\1_R{new_run}",
        renamed,
        flags=re.I,
    )


def _copy_template_files() -> None:
    TARGET.mkdir(parents=True)
    for source in TEMPLATE.iterdir():
        if source.is_file():
            target_name = source.name.replace(TEMPLATE_CASE, TARGET_CASE)
            shutil.copy2(source, TARGET / target_name)


def _transform_instructions(base_pst: pyemu.Pst) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for output in (
        "PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT",
        "PestNResponse.OUT", "PestSoilWat.OUT",
    ):
        source = next(Path(path) for path in base_pst.instruction_files if output in path)
        target_name = f"{TARGET_CASE}_{output}.ins"
        _transform_instruction(
            BASE / source.name,
            TARGET / target_name,
            soil=(output == "PestSoilWat.OUT"),
            preserve_source_order=(output == "PestNResponse.OUT"),
        )
        mapping[output] = target_name
    return mapping


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(TARGET)
    if not TEMPLATE.is_dir() or not BASE.is_dir():
        raise FileNotFoundError(f"template/base missing: {TEMPLATE}, {BASE}")
    _copy_template_files()

    template_pst = pyemu.Pst(str(TEMPLATE / f"{TEMPLATE_CASE}.pst"))
    base_pst = pyemu.Pst(str(BASE / f"{BASE_CASE}.pst"))
    obs = base_pst.observation_data.copy()
    run_map = pd.read_csv(BASE / f"{BASE_CASE}_run_mapping.csv")
    selected_global = [int(run_map.loc[run_map.treatment.eq(t), "global_run"].iloc[0]) for t in TREATMENTS]
    selected = obs[obs.index.astype(str).str.extract(r"_R(\d+)", expand=False, flags=re.I).astype(float).isin(selected_global)].copy()
    selected.index = selected.index.astype(str).map(_rename_observation).str.lower()
    selected["obsnme"] = selected.index
    if selected.index.duplicated().any():
        raise RuntimeError("duplicate observation names after six-treatment compaction")

    # Keep only the six-treatment mapping and update the design's audited
    # bundle hash without mutating the historical design.
    design = json.loads((TEMPLATE / "six_treatment_design.json").read_text(encoding="utf-8"))
    design["design_id"] = TARGET_CASE
    design["seasons"][0]["treatments"] = list(TREATMENTS)
    design["seasons"][0]["bundle_manifest_sha256"] = "f8a249a4e6282b6b52b0101673a0d77abd531d5d3fedb12fb6a2a69a19352707"
    design["nitrogen_response_objective"]["mapping_csv"] = "configs/runs/e02_v2_25sp_water_n_mapping_corrected_20260805.csv"
    design["formal"] = {"n_reals": 150, "noptmax": 4, "initial_ensemble_method": "sobol"}
    design["nitrogen_response_objective"]["levels"] = ["N1", "N2"]
    (TARGET / "six_treatment_design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    instruction_map = _transform_instructions(base_pst)
    template_pst.observation_data = selected
    template_pst.model_input_data = pd.DataFrame(
        {"pest_file": [f"{TARGET_CASE}_params.csv.tpl"], "model_file": [f"{TARGET_CASE}_params.csv"]},
        index=[f"{TARGET_CASE}_params.csv.tpl"],
    )
    template_pst.model_output_data = pd.DataFrame(
        {"pest_file": list(instruction_map.values()), "model_file": list(instruction_map.keys())},
        index=list(instruction_map.values()),
    )
    transform_name = f"{TARGET_CASE}.observation_transforms.json"
    template_pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{(TARGET / "six_treatment_design.json").as_posix()}" '
        f"--param-csv {TARGET_CASE}_params.csv --harvest-var CHPDT --keep-nitrogen-outputs "
        f"--prefix {TARGET_CASE} --observation-transform-config {transform_name}"
    ]
    template_pst.control_data.noptmax = 4
    template_pst.pestpp_options["ies_num_reals"] = "150"
    template_pst.pestpp_options["rand_seed"] = "20260803"

    # Rebuild the observation ensemble from corrected values and sigmas.
    registry = pd.read_csv(BASE / f"{BASE_CASE}_observation_registry.csv")
    registry = registry[registry.obsnme.astype(str).str.extract(r"_R(\d+)", expand=False, flags=re.I).astype(float).isin(selected_global)].copy()
    registry["obsnme"] = registry["obsnme"].astype(str).map(_rename_observation).str.lower()
    registry = registry.set_index("obsnme")
    rng = np.random.default_rng(20260803)
    ensemble = pd.DataFrame({"real_name": np.arange(150, dtype=float)})
    for name, row in template_pst.observation_data.iterrows():
        sigma = float(registry.loc[name, "sigma"]) if name in registry.index and pd.notna(registry.loc[name, "sigma"]) else 1.0
        ensemble[name] = float(row.obsval) + rng.normal(0.0, sigma, size=150)
    ensemble_name = f"{TARGET_CASE}.observation_ensemble.csv"
    ensemble.to_csv(TARGET / ensemble_name, index=False)
    template_pst.pestpp_options["ies_observation_ensemble"] = ensemble_name

    target_pst = TARGET / f"{TARGET_CASE}.pst"
    template_pst.write(str(target_pst))

    selected_map = pd.DataFrame([
        {"global_run": i, "season_id": "25SP", "experiment_code": "XXQL2501", "treatment": t, "local_run": i}
        for i, t in enumerate(TREATMENTS, 1)
    ])
    selected_map.to_csv(TARGET / f"{TARGET_CASE}_run_mapping.csv", index=False, encoding="utf-8-sig")
    registry.reset_index().to_csv(TARGET / f"{TARGET_CASE}_observation_registry.csv", index=False, encoding="utf-8-sig")
    (TARGET / "formal_launch_receipt.json").write_text(json.dumps({
        "run_id": TARGET_CASE,
        "source_parameter_template": str(TEMPLATE),
        "corrected_observation_base": str(BASE),
        "n_parameters": int(template_pst.npar),
        "n_parameters_adjustable": int(template_pst.npar_adj),
        "n_observations": int(template_pst.nobs),
        "n_active_observations": int((template_pst.observation_data.weight > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "custom_dssat": "windows/windows_nresp_20260803/dscsm048_nresp.exe",
        "corrected_filex_manifest_sha256": design["seasons"][0]["bundle_manifest_sha256"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target": str(TARGET), "npar": int(template_pst.npar), "npar_adj": int(template_pst.npar_adj), "nobs": int(template_pst.nobs), "active": int((template_pst.observation_data.weight > 0).sum())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
