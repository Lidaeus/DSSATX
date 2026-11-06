"""Build the six-treatment 25SP N-response calibration case.

The case is derived from the completed ``nreleased`` formal run, but keeps
only W1N0/W1N1/W1N2/W3N0/W3N1/W3N2, adds the two parameters exposed by the
modified DSSAT executable (NREXP and NRMIN), and resets the IES design to
150 realisations and four update iterations.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd
import pyemu


PROJECT = Path(r"D:/Tomato_Cal")
SOURCE = PROJECT / "workspace/runs/e02_v2_formal25sp_nreleased_200x5_20260802"
OLD_PREFIX = "e02_v2_formal25sp_nreleased_200x5_20260802"
PREFIX = os.environ.get(
    "SIX_TREATMENT_PREFIX",
    "e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260803_retry3",
)
TARGET = PROJECT / "workspace/runs" / PREFIX
SOURCE_DESIGN = PROJECT / "configs/runs/eggplant_e02_v2_formal25sp_nreleased_20260802.json"
NREXP_UPPER = float(os.environ.get("SIX_TREATMENT_NREXP_UPPER", "1.0"))
EXCLUDE_NRESP_SOILWATER = os.environ.get("SIX_TREATMENT_EXCLUDE_NRESP_SOILWATER", "0") == "1"

# Preserve the user-requested order: W1 N0, N1, N2, then W3 N0, N1, N2.
OLD_RUNS = (8, 7, 6, 4, 3, 2)
TREATMENTS = (13, 12, 11, 5, 4, 3)
RUN_RENUMBER = {old: new for new, old in enumerate(OLD_RUNS, 1)}


def _rename_run_token(text: str, old_run: int) -> str:
    return re.sub(rf"_R{old_run}(?=_|!|$)", f"_R{RUN_RENUMBER[old_run]}", text, flags=re.I)


def _transform_instruction(
    source: Path,
    target: Path,
    soil: bool = False,
    preserve_source_order: bool = False,
) -> None:
    headers: list[str] = []
    body: list[tuple[int, int, str]] = []
    for raw in source.read_text(encoding="utf-8", errors="strict").splitlines():
        if raw.lower().startswith("pif "):
            headers.append(raw)
            continue
        match = re.search(r"_R(\d+)(?=_|!)", raw, flags=re.I)
        if match is None or int(match.group(1)) not in RUN_RENUMBER:
            continue
        old_run = int(match.group(1))
        line = _rename_run_token(raw, old_run)
        if soil:
            token = re.search(r"_SW(\d{4})([SM])_R\d+", line, flags=re.I)
            if token is None:
                continue
            old_token = int(token.group(1))
            new_token = old_token - (old_run - RUN_RENUMBER[old_run]) * 10
            if not 1 <= new_token <= 60:
                raise ValueError(f"unexpected soil token {old_token} for R{old_run}")
            line = re.sub(
                rf"SW{old_token:04d}([SM])",
                lambda m: f"SW{new_token:04d}{m.group(1)}",
                line,
                flags=re.I,
            )
        body.append((RUN_RENUMBER[old_run], len(body), line))
    if not headers or not headers[0].lower().startswith("pif "):
        raise ValueError(f"instruction transformation produced no header: {source}")
    if not preserve_source_order:
        body.sort(key=lambda item: (item[0], item[1]))
    target.write_text("\n".join([headers[0], *(item[2] for item in body)]) + "\n", encoding="utf-8")


def _rename_observation(name: str, old_run: int) -> str:
    renamed = _rename_run_token(name, old_run)
    token = re.search(r"_SW(\d{4})([SM])_R(\d+)", renamed, flags=re.I)
    if token is None:
        return renamed
    old_token = int(token.group(1))
    new_run = RUN_RENUMBER[old_run]
    new_token = old_token - (old_run - new_run) * 10
    if not 1 <= new_token <= 60:
        raise ValueError(f"unexpected soil token {old_token} for R{old_run}")
    return re.sub(
        rf"SW{old_token:04d}([SM])_R{new_run}",
        f"SW{new_token:04d}\\1_R{new_run}",
        renamed,
        flags=re.I,
    )


def _old_ensemble_name(target_name: str) -> str:
    name = target_name.lower()
    match = re.search(r"_r(\d+)(?=_|$)", name)
    if match is None:
        return name
    new_run = int(match.group(1))
    inverse = {new: old for old, new in RUN_RENUMBER.items()}
    old_run = inverse[new_run]
    token = re.search(r"_sw(\d{4})([sm])_r\d+", name, flags=re.I)
    if token is not None:
        compact_token = int(token.group(1))
        old_token = compact_token + (old_run - new_run) * 10
        name = re.sub(
            rf"_sw{compact_token:04d}([sm])_r{new_run}",
            f"_sw{old_token:04d}\\1_r{old_run}",
            name,
            flags=re.I,
        )
    else:
        name = re.sub(rf"_r{new_run}(?=_|$)", f"_r{old_run}", name, flags=re.I)
    return name


def _selected_batch(source: Path, target: Path) -> None:
    rows: list[str] = []
    for raw in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(("$", "!", "@", "*")):
            rows.append(raw)
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) in TREATMENTS:
            rows.append(raw)
    target.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(f"target already exists: {TARGET}")
    if not SOURCE.is_dir() or not (SOURCE / f"{OLD_PREFIX}.pst").is_file():
        raise FileNotFoundError(f"source formal run is incomplete: {SOURCE}")
    TARGET.mkdir(parents=True)

    source_pst = SOURCE / f"{OLD_PREFIX}.pst"
    pst = pyemu.Pst(str(source_pst))

    # Parameter contract: preserve all 106 original rows and add two active
    # species-level parameters used by the modified SPE row.
    source_params = SOURCE / f"{OLD_PREFIX}_params.csv"
    source_tpl = SOURCE / f"{OLD_PREFIX}_params.csv.tpl"
    params = pd.read_csv(source_params)
    params = pd.concat(
        [params, pd.DataFrame([{"name": "NREXP", "value": 0.65}, {"name": "NRMIN", "value": 0.70}])],
        ignore_index=True,
    )
    params_name = f"{PREFIX}_params.csv"
    tpl_name = f"{PREFIX}_params.csv.tpl"
    params.to_csv(TARGET / params_name, index=False)
    tpl_text = source_tpl.read_text(encoding="utf-8")
    if not tpl_text.endswith("\n"):
        tpl_text += "\n"
    tpl_text += "NREXP,~ NREXP ~\nNRMIN,~ NRMIN ~\n"
    (TARGET / tpl_name).write_text(tpl_text, encoding="utf-8")

    new_par = pd.DataFrame(
        {
            "parnme": ["nrexp", "nrmin"],
            "partrans": ["none", "none"],
            "parchglim": ["factor", "factor"],
            "parval1": [0.65, 0.70],
            "parlbnd": [0.50, 0.60],
            "parubnd": [NREXP_UPPER, 0.80],
            "pargp": ["species", "species"],
            "scale": [1.0, 1.0],
            "offset": [0.0, 0.0],
            "dercom": [1, 1],
            "extra": ["", ""],
        },
        index=["nrexp", "nrmin"],
    )
    pst.parameter_data = pd.concat([pst.parameter_data, new_par])

    # Keep only the six requested treatments and compact the run IDs.  This
    # includes the N-response observations for N1/N2; N0 has no NRESPS row.
    obs = pst.observation_data.copy()
    keep_idx: list[str] = []
    rename: dict[str, str] = {}
    for idx, name in zip(obs.index, obs["obsnme"].astype(str)):
        match = re.search(r"_R(\d+)(?=_|$)", name, flags=re.I)
        if match is None:
            keep_idx.append(idx)
            continue
        old_run = int(match.group(1))
        if old_run in RUN_RENUMBER:
            keep_idx.append(idx)
            rename[idx] = _rename_observation(name, old_run).lower()
    obs = obs.loc[keep_idx].copy()
    obs["obsnme"] = [rename.get(idx, str(name).lower()) for idx, name in zip(obs.index, obs["obsnme"])]
    obs.index = obs["obsnme"].astype(str).str.lower()
    if EXCLUDE_NRESP_SOILWATER:
        # Keep these outputs for diagnostics, but remove them from Phi.
        diagnostic_only = (
            obs["obgnme"].astype(str).str.upper().eq("SOIL_WATER")
            | obs["obgnme"].astype(str).str.upper().eq("N_RESPONSE")
            | obs["obsnme"].astype(str).str.lower().str.contains("_nresps_")
            | obs["obsnme"].astype(str).str.lower().str.contains("_sw")
        )
        obs.loc[diagnostic_only, "weight"] = 0.0
    pst.observation_data = obs

    # Frozen observation registry and treatment/run mapping.
    registry_path = SOURCE / f"{OLD_PREFIX}_observation_registry.csv"
    registry = pd.read_csv(registry_path)
    registry = registry[registry["global_run"].isin(OLD_RUNS)].copy()
    registry["obsnme"] = [
        _rename_observation(str(name), int(old_run)).lower()
        for name, old_run in zip(registry["obsnme"], registry["global_run"])
    ]
    registry["global_run"] = registry["global_run"].map(RUN_RENUMBER).astype(int)
    registry["treatment"] = registry["treatment"].astype(int)
    if EXCLUDE_NRESP_SOILWATER:
        diagnostic_only = (
            registry["obgnme"].astype(str).str.upper().eq("SOIL_WATER")
            | registry["obgnme"].astype(str).str.upper().eq("N_RESPONSE")
            | registry["sim_token"].astype(str).str.upper().eq("NRESPS")
            | registry["sim_token"].astype(str).str.upper().str.startswith("SW")
        )
        registry.loc[diagnostic_only, "weight"] = 0.0
    registry.to_csv(TARGET / f"{PREFIX}_observation_registry.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"global_run": i, "season_id": "25SP", "experiment_code": "XXQL2501", "treatment": tn, "local_run": i}
            for i, tn in enumerate(TREATMENTS, 1)
        ]
    ).to_csv(TARGET / f"{PREFIX}_run_mapping.csv", index=False, encoding="utf-8-sig")

    # Transform all PEST instruction files to the compact six-run output.
    instruction_map: dict[str, str] = {}
    for output in ("PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT", "PestNResponse.OUT", "PestSoilWat.OUT"):
        old_file = next(Path(x) for x in pst.instruction_files if output in x)
        target_name = f"{PREFIX}_{output}.ins"
        _transform_instruction(
            SOURCE / old_file.name,
            TARGET / target_name,
            soil=(output == "PestSoilWat.OUT"),
            preserve_source_order=(output == "PestNResponse.OUT"),
        )
        instruction_map[output] = target_name

    pst.model_input_data = pd.DataFrame({"pest_file": [tpl_name], "model_file": [params_name]}, index=[tpl_name])
    pst.model_output_data = pd.DataFrame(
        {"pest_file": list(instruction_map.values()), "model_file": list(instruction_map.keys())},
        index=list(instruction_map.values()),
    )

    # PEST++ IES observation noise must use the renamed active observation
    # columns, otherwise selected-run members receive mismatched noise.
    source_ensemble = pd.read_csv(SOURCE / f"{OLD_PREFIX}.observation_ensemble.csv").set_index("real_name")
    active_names = pst.observation_data.loc[pst.observation_data["weight"] > 0, "obsnme"].astype(str).str.lower()
    ensemble = pd.DataFrame(index=source_ensemble.index)
    missing: list[str] = []
    for target_name in active_names:
        source_name = _old_ensemble_name(target_name)
        if source_name not in source_ensemble.columns:
            missing.append(f"{target_name} -> {source_name}")
        else:
            ensemble[target_name] = source_ensemble[source_name].to_numpy()
    if missing:
        raise KeyError(f"missing observation ensemble columns: {missing[:5]}")
    ensemble.insert(0, "real_name", ensemble.index)
    ensemble_name = f"{PREFIX}.observation_ensemble.csv"
    ensemble.to_csv(TARGET / ensemble_name, index=False)
    pst.pestpp_options["ies_observation_ensemble"] = ensemble_name
    pst.pestpp_options["ies_num_reals"] = "150"
    pst.pestpp_options["rand_seed"] = "20260803"

    # New design contract: six treatments, one season, 150 realisations, 4
    # IES updates.  Keep the original bundle and observation policies intact.
    design = json.loads(SOURCE_DESIGN.read_text(encoding="utf-8"))
    design["design_id"] = PREFIX
    design["seasons"][0]["treatments"] = list(TREATMENTS)
    design["nitrogen_response_objective"]["levels"] = ["N1", "N2"]
    design["formal"]["n_reals"] = 150
    design["formal"]["noptmax"] = 4
    design_name = "six_treatment_design.json"
    (TARGET / design_name).write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    transform_name = f"{PREFIX}.observation_transforms.json"
    shutil.copy2(SOURCE / f"{OLD_PREFIX}.observation_transforms.json", TARGET / transform_name)
    _selected_batch(SOURCE / "DSSBatch.v48", TARGET / "DSSBatch.six_treatment.v48")

    pst.model_command = (
        f'python "{(PROJECT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{(TARGET / design_name).as_posix()}" '
        f"--param-csv {params_name} --harvest-var CHPDT --keep-nitrogen-outputs "
        f"--prefix {PREFIX} --observation-transform-config {transform_name}"
    )
    pst.control_data.noptmax = 4
    target_pst = TARGET / f"{PREFIX}.pst"
    pst.write(str(target_pst))

    check = pyemu.Pst(str(target_pst))
    if check.npar != 108 or check.npar_adj != 101:
        raise RuntimeError(f"unexpected parameter count: total={check.npar}, adjustable={check.npar_adj}")
    if check.nobs != len(obs):
        raise RuntimeError(f"observation count mismatch: PEST={check.nobs}, filtered={len(obs)}")
    if not {"nrexp", "nrmin"}.issubset(set(check.parameter_data.index)):
        raise RuntimeError("NREXP/NRMIN missing from PEST parameter contract")
    if len(active_names) != int((obs["weight"] > 0).sum()):
        raise RuntimeError("active observation count mismatch")

    manifest = {
        "source_run": str(SOURCE),
        "target_run": str(TARGET),
        "selected_treatments": list(TREATMENTS),
        "selected_original_global_runs": list(OLD_RUNS),
        "run_renumbering": RUN_RENUMBER,
        "nrexp": {"init": 0.65, "lower": 0.50, "upper": NREXP_UPPER, "location": "SPE XPODF"},
        "nrmin": {"init": 0.70, "lower": 0.60, "upper": 0.80, "location": "SPE XPODF"},
        "parameter_count": {"total": int(check.npar), "adjustable": int(check.npar_adj)},
        "observation_count": int(check.nobs),
        "active_observation_count": int((check.observation_data["weight"] > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "custom_executable": str(PROJECT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"),
        "genotype_source": str(PROJECT / "windows/windows_nresp_20260803/Genotype"),
        "phi_exclusions": {
            "n_response": bool(EXCLUDE_NRESP_SOILWATER),
            "soil_water": bool(EXCLUDE_NRESP_SOILWATER),
        },
    }
    (TARGET / "six_treatment_case_build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
