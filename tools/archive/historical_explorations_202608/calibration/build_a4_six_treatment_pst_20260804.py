"""Build the A4 six-treatment 25SP calibration case.

The observation/weight/design contract is copied from the audited E02 retry3
case.  Only the A4 SPE parameter contract is extended: NUPK50 and NUPAV are
active in the first A4 search, with NUPQ using the documented 0.50-1.50
working domain.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(r"D:/Tomato_Cal")
SOURCE = ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260803_retry3"
PREFIX = "a4_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804"
TARGET = ROOT / "workspace/runs" / PREFIX
SOURCE_CASE = SOURCE.name


def _copy_required(name: str) -> None:
    source = SOURCE / name
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, TARGET / name.replace(SOURCE_CASE, PREFIX))


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(TARGET)
    if not (SOURCE / f"{SOURCE_CASE}.pst").is_file():
        raise FileNotFoundError(SOURCE)
    TARGET.mkdir(parents=True)

    # Reuse exactly the six-treatment observation and weight contract.
    for path in SOURCE.iterdir():
        name = path.name
        if not path.is_file():
            continue
        if (
            name.endswith("_PestEval.OUT.ins")
            or name.endswith("_PestJoint.OUT.ins")
            or name.endswith("_PestHarvest.OUT.ins")
            or name.endswith("_PestTmtGrow.OUT.ins")
            or name.endswith("_PestNResponse.OUT.ins")
            or name.endswith("_PestSoilWat.OUT.ins")
            or name in {"DSSBatch.six_treatment.v48", f"{SOURCE_CASE}.observation_ensemble.csv", f"{SOURCE_CASE}.observation_transforms.json", "six_treatment_design.json"}
            or name.endswith("_observation_registry.csv")
            or name.endswith("_run_mapping.csv")
        ):
            shutil.copy2(path, TARGET / name.replace(SOURCE_CASE, PREFIX))

    source_pst = SOURCE / f"{SOURCE_CASE}.pst"
    pst = pyemu.Pst(str(source_pst))

    source_params = SOURCE / f"{SOURCE_CASE}_params.csv"
    source_tpl = SOURCE / f"{SOURCE_CASE}_params.csv.tpl"
    params = pd.read_csv(source_params)
    params = pd.concat(
        [
            params,
            pd.DataFrame(
                [
                    {"name": "NUPK50", "value": 8.664},
                    {"name": "NUPQ", "value": 1.00},
                    {"name": "NUPAV", "value": 1.00},
                ]
            ),
        ],
        ignore_index=True,
    )
    params_name = f"{PREFIX}_params.csv"
    tpl_name = f"{PREFIX}_params.csv.tpl"
    params.to_csv(TARGET / params_name, index=False)
    tpl_text = source_tpl.read_text(encoding="utf-8")
    if not tpl_text.endswith("\n"):
        tpl_text += "\n"
    tpl_text += "NUPK50,~ NUPK50 ~\nNUPQ,~ NUPQ ~\nNUPAV,~ NUPAV ~\n"
    (TARGET / tpl_name).write_text(tpl_text, encoding="utf-8")

    # A4 first-round working domains from the method note.
    new_par = pd.DataFrame(
        {
            "parnme": ["nupk50", "nupq", "nupav"],
            "partrans": ["none", "none", "none"],
            "parchglim": ["factor", "factor", "factor"],
            "parval1": [8.664, 1.00, 1.00],
            "parlbnd": [1.0, 0.50, 0.50],
            "parubnd": [40.0, 1.50, 1.00],
            "pargp": ["species", "species", "species"],
            "scale": [1.0, 1.0, 1.0],
            "offset": [0.0, 0.0, 0.0],
            "dercom": [1, 1, 1],
            "extra": ["", "", ""],
        },
        index=["nupk50", "nupq", "nupav"],
    )
    pst.parameter_data = pd.concat([pst.parameter_data, new_par])

    # Rename the copied contract files in the PEST control tables.
    rename = {str(x): str(x).replace(SOURCE_CASE, PREFIX) for x in pst.instruction_files}
    pst.model_output_data.index = [rename.get(str(x), str(x)) for x in pst.model_output_data.index]
    pst.model_output_data["pest_file"] = [rename.get(str(x), str(x)) for x in pst.model_output_data["pest_file"]]

    pst.model_input_data.index = [tpl_name]
    pst.model_input_data.loc[tpl_name, "pest_file"] = tpl_name
    pst.model_input_data.loc[tpl_name, "model_file"] = params_name

    ensemble_name = f"{PREFIX}.observation_ensemble.csv"
    pst.pestpp_options["ies_observation_ensemble"] = ensemble_name
    pst.pestpp_options["ies_num_reals"] = "150"
    pst.pestpp_options["rand_seed"] = "20260803"
    pst.control_data.noptmax = 4

    design_name = "six_treatment_design.json"
    design = json.loads((TARGET / design_name).read_text(encoding="utf-8"))
    design["design_id"] = PREFIX
    design["bounds_id"] = PREFIX
    design["formal"]["n_reals"] = 150
    design["formal"]["noptmax"] = 4
    (TARGET / design_name).write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    transform_name = f"{PREFIX}.observation_transforms.json"
    pst.model_command = (
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{(TARGET / design_name).as_posix()}" '
        f"--param-csv {params_name} --harvest-var CHPDT --keep-nitrogen-outputs "
        f"--prefix {PREFIX} --observation-transform-config {transform_name}"
    )

    target_pst = TARGET / f"{PREFIX}.pst"
    pst.write(str(target_pst))
    check = pyemu.Pst(str(target_pst))
    expected_names = {"nupk50", "nupq", "nupav"}
    if not expected_names.issubset(set(check.parameter_data.index)):
        raise RuntimeError("A4 NUP parameters missing from PST")
    if check.npar != 111 or check.npar_adj != 104:
        raise RuntimeError(f"unexpected A4 parameter count: total={check.npar}, adjustable={check.npar_adj}")
    if check.nobs != 434:
        raise RuntimeError(f"unexpected observation count: {check.nobs}")

    manifest = {
        "source_run": str(SOURCE),
        "target_run": str(TARGET),
        "configuration_source": SOURCE_CASE,
        "selected_treatments": [13, 12, 11, 5, 4, 3],
        "nupk50": {"init": 8.664, "lower": 1.0, "upper": 40.0, "status": "active", "location": "SPE NUPT"},
        "nupq": {"init": 1.0, "lower": 0.50, "upper": 1.50, "status": "active", "location": "SPE NUPT"},
        "nupav": {"init": 1.0, "lower": 0.50, "upper": 1.00, "status": "active", "location": "SPE NUPT"},
        "parameter_count": {"total": int(check.npar), "adjustable": int(check.npar_adj)},
        "observation_count": int(check.nobs),
        "active_observation_count": int((check.observation_data["weight"] > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "custom_executable": str(ROOT / "windows/windows_a4_20260804/dscsm048_a4.exe"),
        "genotype_source": str(ROOT / "windows/windows_a4_20260804/Genotype/TMGRO048.SPE"),
        "nupq_first_round_policy": "active 0.50-1.50 per CROPGRO_N_UPTAKE_AVAILABILITY_A4.zh-CN.md",
    }
    proposal_rows = []
    for name, row in check.parameter_data.iterrows():
        upper_name = str(name).upper()
        group = str(row["pargp"]).lower()
        if group == "soil":
            location, target_file = "SOIL", "SOIL.SOL"
        elif group == "cultivar":
            location, target_file = "CUL", "TMGRO048.CUL"
        elif group == "ecotype":
            location, target_file = "ECO", "TMGRO048.ECO"
        else:
            location, target_file = "SPE", "TMGRO048.SPE"
        status = "fixed" if str(row["partrans"]).lower() == "fixed" else "active"
        proposal_rows.append(
            {
                "name": upper_name,
                "init": float(row["parval1"]),
                "lower": float(row["parlbnd"]),
                "upper": float(row["parubnd"]),
                "status": status,
                "pargp": group,
                "location": location,
                "file": target_file,
                "cultivar": "TM0008",
                "ecotype": "TM0001",
                "mode": "a4_25sp_nreleased",
                "review_note": "A4 custom N-uptake parameters; NUPQ active at 0.50-1.50" if upper_name in {"NUPK50", "NUPQ", "NUPAV"} else "inherited from audited E02 retry3 contract",
                "decision_role": "a4_n_uptake_extension" if upper_name in {"NUPK50", "NUPQ", "NUPAV"} else "inherited_e02_contract",
                "evidence_basis": "CROPGRO_N_UPTAKE_AVAILABILITY_A4.zh-CN.md" if upper_name in {"NUPK50", "NUPQ", "NUPAV"} else SOURCE_CASE,
                "notes": "",
            }
        )
    proposal_name = f"{PREFIX}.csv"
    pd.DataFrame(proposal_rows).to_csv(
        ROOT / "data/parameter_registry/bounds_proposals/eggplant" / proposal_name,
        index=False,
        encoding="utf-8-sig",
    )
    manifest["bounds_proposal"] = str(ROOT / "data/parameter_registry/bounds_proposals/eggplant" / proposal_name)
    (TARGET / "a4_case_build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
