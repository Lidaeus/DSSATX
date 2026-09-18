"""Build the four-corner 25SP calibration case from the prior formal case.

This is an audit-friendly migration helper for the 2026-08-03 wide-k0025 run.
It preserves the original 99-adjustable-parameter PEST contract while reducing
the 25SP treatment domain to TN2/TN5/TN10/TN13 and replacing the N2 response
observations with N3-minus-N0 observations.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pyemu


PROJECT = Path(r"D:/Tomato_Cal")
SOURCE = PROJECT / "workspace/runs/e02_v2_formal25sp_state_terminal_n2response_200x5_20260802"
TARGET = PROJECT / "workspace/runs/e02_v2_formal25sp_4corner_n3response_widek0025_200x5_20260803_formal"
OLD_PREFIX = "e02_v2_formal25sp_state_terminal_n2response_200x5_20260802"
PREFIX = "e02_v2_formal25sp_4corner_n3response_widek0025_200x5_20260803_formal"
OLD_RUNS = (1, 4, 5, 8)
RUN_RENUMBER = {1: 1, 4: 2, 5: 3, 8: 4}
# Original source case has ten soil observations per treatment, in the
# original R1..R8 order.  Selected blocks begin at 1, 31, 41, 71 and are
# compacted to 1, 11, 21, 31 for the four-treatment runtime batch.
SOIL_TOKEN_OFFSET = {1: 0, 4: 20, 5: 20, 8: 40}


def _rename_run_token(text: str, old_run: int) -> str:
    new_run = RUN_RENUMBER[old_run]
    return re.sub(rf"_R{old_run}(?=_|!|$)", f"_R{new_run}", text, flags=re.IGNORECASE)


def _transform_instruction(source: Path, target: Path, soil: bool = False) -> None:
    out: list[str] = []
    for line in source.read_text(encoding="utf-8", errors="strict").splitlines():
        if line.lower().startswith("pif "):
            out.append(line)
            continue
        match = re.search(r"_R(\d+)(?=_|!)", line, flags=re.IGNORECASE)
        if not match:
            continue
        old_run = int(match.group(1))
        if old_run not in OLD_RUNS:
            continue
        line = _rename_run_token(line, old_run)
        if soil:
            token_match = re.search(r"SW(\d{4})([SM])_R\d+", line, flags=re.IGNORECASE)
            if token_match is None:
                continue
            old_token = int(token_match.group(1))
            new_token = old_token - SOIL_TOKEN_OFFSET[old_run]
            if not 1 <= new_token <= 40:
                raise ValueError(f"unexpected soil token {old_token} for R{old_run}")
            line = re.sub(
                rf"SW{old_token:04d}([SM])",
                lambda m: f"SW{new_token:04d}{m.group(1)}",
                line,
                flags=re.IGNORECASE,
            )
        out.append(line)
    if not out or not out[0].lower().startswith("pif "):
        raise ValueError(f"instruction transformation produced no header: {source}")
    target.write_text("\n".join(out) + "\n", encoding="utf-8")


def _rename_obs(obs: str, old_run: int) -> str:
    return _rename_run_token(obs, old_run)


def _make_nresponse_rows(reg: pd.DataFrame) -> pd.DataFrame:
    # Terminal observed CHPDT and sigma from the original formal observation
    # registry.  The selected pairs are W3: TN2-TN5 and W1: TN10-TN13.
    terminal = reg[reg["obsnme"].str.match(r"25SP_CHPDTS_R\d+_H11", case=False, na=False)].copy()
    terminal = terminal[terminal["global_run"].isin(OLD_RUNS)].set_index("global_run")
    pairs = [(1, 4), (5, 8)]  # high N minus N0; W3 then W1 in source order
    rows: list[dict[str, object]] = []
    for high_run, zero_run in pairs:
        high = terminal.loc[high_run]
        zero = terminal.loc[zero_run]
        sigma = ((float(high["sigma"]) ** 2 + float(zero["sigma"]) ** 2 + 50.0**2) ** 0.5)
        new_run = RUN_RENUMBER[high_run]
        rows.append(
            {
                "obsnme": f"25SP_NRESPS_R{new_run}_H11",
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "treatment": int(high["treatment"]),
                "global_run": new_run,
                "obgnme": "25SP_NRESPM_H11",
                "obsval": float(high["obsval"]) - float(zero["obsval"]),
                "weight": 0.6123724356957945 / sigma,
                "sigma": sigma,
                "sigma_source": "paired_raw_difference_plus_static_floor",
                "dataset_role": "calibration",
                "raw_obsval": float(high["obsval"]) - float(zero["obsval"]),
                "raw_sigma": sigma,
                "base_weight": 0.6123724356957945 / sigma,
                "group_multiplier": 0.6123724356957945,
                "transform": "raw",
                "transform_offset": 0.0,
                "transform_reference": 1.0,
                "sim_token": "NRESPS",
                "model_output_file": "PestNResponse.OUT",
                "weight_policy_id": "observation_policy_v2",
                "phi_role": "calibration",
                "note": "N3-minus-N0 within the same water level; terminal CHPDT",
            }
        )
    return pd.DataFrame(rows)


def _old_ensemble_column(target_name: str) -> str:
    """Map a selected/renumbered target observation to old ensemble column."""
    name = target_name.lower()
    if "_nresps_r3_h11" in name:
        return "__derive_w1_n3_n0__"
    if "_nresps_r1_h11" in name:
        return "__derive_w3_n3_n0__"
    run_match = re.search(r"_r([1-4])(?=_|$)", name)
    if run_match is None:
        raise KeyError(f"target observation has no selected run ID: {target_name}")
    new_run = int(run_match.group(1))
    old_run = {new: old for old, new in RUN_RENUMBER.items()}[new_run]
    if re.search(r"_sw\d{4}[sm]_r[1-4]", name):
        token_match = re.search(r"_sw(\d{4})([sm])_r[1-4]", name)
        if token_match is None:
            raise KeyError(f"soil observation has no compact token: {target_name}")
        token = int(token_match.group(1)) + SOIL_TOKEN_OFFSET[old_run]
        name = re.sub(r"_sw\d{4}([sm])_r[1-4]", f"_sw{token:04d}\\1_r{old_run}", name)
    else:
        name = re.sub(rf"_r{new_run}(?=_|$)", f"_r{old_run}", name)
    return name


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(f"target already exists: {TARGET}")
    TARGET.mkdir(parents=True)
    source_pst = SOURCE / f"{OLD_PREFIX}.pst"
    pst = pyemu.Pst(str(source_pst))

    # Preserve the original 106-parameter / 99-adjustable contract.
    source_params = SOURCE / f"{OLD_PREFIX}_params.csv"
    source_tpl = SOURCE / f"{OLD_PREFIX}_params.csv.tpl"
    target_params_name = f"{PREFIX}_params.csv"
    target_tpl_name = f"{PREFIX}_params.csv.tpl"
    shutil.copy2(source_params, TARGET / target_params_name)
    shutil.copy2(source_tpl, TARGET / target_tpl_name)

    # Frozen data contract: selected four treatments, with compact run IDs.
    registry_path = SOURCE / f"{OLD_PREFIX}_observation_registry.csv"
    reg = pd.read_csv(registry_path)
    selected = reg[reg["global_run"].isin(OLD_RUNS)].copy()
    selected = selected[~selected["obsnme"].str.contains("NRESPS", case=False, na=False)]
    selected["global_run"] = selected["global_run"].map(RUN_RENUMBER).astype(int)
    for old_run in OLD_RUNS:
        mask = reg.loc[selected.index, "global_run"].eq(old_run)
        selected.loc[mask, "obsnme"] = selected.loc[mask, "obsnme"].map(lambda x: _rename_obs(x, old_run))
    nrows = _make_nresponse_rows(reg)
    selected = pd.concat([selected, nrows], ignore_index=True)
    selected.to_csv(TARGET / f"{PREFIX}_observation_registry.csv", index=False, encoding="utf-8-sig")

    # Filter/renumber observations in the copied PEST control object.
    obs = pst.observation_data.copy()
    original_names = obs["obsnme"].astype(str).str.upper()
    keep = []
    rename: dict[str, str] = {}
    for idx, name in zip(obs.index, original_names):
        m = re.search(r"_R(\d+)(?=_|$)", name, flags=re.IGNORECASE)
        if not m:
            keep.append(idx)
            continue
        old_run = int(m.group(1))
        if old_run in OLD_RUNS:
            keep.append(idx)
            new_name = _rename_obs(name, old_run).lower()
            if "_sw" in name.lower():
                sm = re.search(r"_SW(\d{4})([SM])_R\d+", name, flags=re.IGNORECASE)
                if sm:
                    old_token = int(sm.group(1))
                    new_token = old_token - SOIL_TOKEN_OFFSET[old_run]
                    new_name = re.sub(
                        rf"sw{old_token:04d}([sm])",
                        f"sw{new_token:04d}\\1",
                        new_name,
                        flags=re.IGNORECASE,
                    )
            rename[idx] = new_name
        # all other run-specific observations are excluded
    obs = obs.loc[keep].copy()
    obs["obsnme"] = [rename.get(idx, str(name).lower()) for idx, name in zip(obs.index, obs["obsnme"])]
    obs.index = obs["obsnme"].str.lower()

    # Replace the old N2 response rows with N3 response rows.  The two new
    # rows are ordered to match write_simulated_n_response: W1 then W3.
    nobs = pd.DataFrame(
        [
            {"obsnme": "25sp_nresps_r3_h11", "obsval": 784.0, "weight": float(nrows.iloc[1]["weight"]), "obgnme": "25sp_nrespm_h11", "extra": None},
            {"obsnme": "25sp_nresps_r1_h11", "obsval": 399.0, "weight": float(nrows.iloc[0]["weight"]), "obgnme": "25sp_nrespm_h11", "extra": None},
        ]
    ).set_index("obsnme")
    nobs["obsnme"] = nobs.index
    obs = pd.concat([obs[~obs.index.str.contains("nresps", case=False)], nobs], axis=0)
    pst.observation_data = obs

    # Replace instruction files with selected/renumbered versions.
    instruction_names = {
        "PestEval.OUT": f"{PREFIX}_PestEval.OUT.ins",
        "PestJoint.OUT": f"{PREFIX}_PestJoint.OUT.ins",
        "PestHarvest.OUT": f"{PREFIX}_PestHarvest.OUT.ins",
        "PestTmtGrow.OUT": f"{PREFIX}_PestTmtGrow.OUT.ins",
        "PestSoilWat.OUT": f"{PREFIX}_PestSoilWat.OUT.ins",
    }
    for output, new_name in instruction_names.items():
        old_name = next(x for x in pst.instruction_files if output in x)
        _transform_instruction(SOURCE / old_name, TARGET / new_name, soil=(output == "PestSoilWat.OUT"))
    nresp_name = f"{PREFIX}_PestNResponse.OUT.ins"
    (TARGET / nresp_name).write_text(
        "pif @\n"
        "l1 @NRESPS@ w !25SP_NRESPS_R3_H11!\n"
        "l1 @NRESPS@ w !25SP_NRESPS_R1_H11!\n",
        encoding="utf-8",
    )
    pst.model_command = [
        f'python "D:/Tomato_Cal/src/calibration/run_multiseason.py" '
        f'--design "{TARGET.as_posix()}/four_corner_design.json" '
        f"--param-csv {target_params_name} --harvest-var CHPDT --keep-nitrogen-outputs "
        f"--prefix {PREFIX} --observation-transform-config {PREFIX}.observation_transforms.json"
    ]
    new_instruction_files = [
        instruction_names["PestEval.OUT"],
        instruction_names["PestJoint.OUT"],
        instruction_names["PestHarvest.OUT"],
        instruction_names["PestTmtGrow.OUT"],
        nresp_name,
        instruction_names["PestSoilWat.OUT"],
    ]
    pst.model_input_data = pd.DataFrame(
        {
            "pest_file": [target_tpl_name],
            "model_file": [target_params_name],
        },
        index=[target_tpl_name],
    )
    pst.model_output_data = pd.DataFrame(
        {
            "pest_file": new_instruction_files,
            "model_file": ["PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT", "PestNResponse.OUT", "PestSoilWat.OUT"],
        },
        index=new_instruction_files,
    )

    # PEST++ IES loads an observation ensemble by the literal filename in
    # pestpp_options.  Rebuild that table for the selected/renumbered active
    # observation set instead of leaving the source-case filename behind.
    source_ensemble = pd.read_csv(
        SOURCE / f"{OLD_PREFIX}.observation_ensemble.csv"
    )
    source_ensemble = source_ensemble.set_index("real_name")
    active_names = pst.observation_data.loc[
        pst.observation_data["weight"] > 0, "obsnme"
    ].astype(str).str.lower().tolist()
    ensemble = pd.DataFrame(index=source_ensemble.index)
    for name in active_names:
        source_name = _old_ensemble_column(name)
        if source_name == "__derive_w1_n3_n0__":
            values = source_ensemble["25sp_chpdts_r5_h11"] - source_ensemble["25sp_chpdts_r8_h11"]
        elif source_name == "__derive_w3_n3_n0__":
            values = source_ensemble["25sp_chpdts_r1_h11"] - source_ensemble["25sp_chpdts_r4_h11"]
        else:
            values = source_ensemble[source_name]
        ensemble[name] = values.to_numpy()
    ensemble.insert(0, "real_name", ensemble.index)
    ensemble_name = f"{PREFIX}.observation_ensemble.csv"
    ensemble.to_csv(TARGET / ensemble_name, index=False)
    pst.pestpp_options["ies_observation_ensemble"] = ensemble_name
    pst.pestpp_options["rand_seed"] = "20260803"

    # Copy the design and observation-transform contract into the run root.
    design_source = PROJECT / "workspace/runs/e02_v2_formal25sp_4corner_n3response_widek0025_200x5_20260803/four_corner_design.json"
    shutil.copy2(design_source, TARGET / "four_corner_design.json")
    transform_source = SOURCE / f"{OLD_PREFIX}.observation_transforms.json"
    shutil.copy2(transform_source, TARGET / f"{PREFIX}.observation_transforms.json")

    # Add a compact batch for provenance; run_multiseason materializes its own
    # selected batch from the authoritative bundle.
    batch_source = PROJECT / "workspace/runs/e02_v2_formal25sp_4corner_n3response_widek0025_200x5_20260803/DSSBatch.4corner.v48"
    shutil.copy2(batch_source, TARGET / "DSSBatch.4corner.v48")

    target_pst = TARGET / f"{PREFIX}.pst"
    pst.write(str(target_pst))

    # Re-open and verify the generated control contract before any PEST++ call.
    check = pyemu.Pst(str(target_pst))
    if check.npar_adj != 99 or check.npar != 106:
        raise RuntimeError(f"unexpected parameter count: total={check.npar}, adjustable={check.npar_adj}")
    if check.nobs != 262:
        raise RuntimeError(f"unexpected observation count: {check.nobs}, expected 262")
    manifest = {
        "source_pst": str(source_pst),
        "target_pst": str(target_pst),
        "selected_original_global_runs": list(OLD_RUNS),
        "selected_treatments_in_model_order": [2, 5, 10, 13],
        "run_renumbering": RUN_RENUMBER,
        "soil_token_compaction": "old R1/R4/R5/R8 blocks -> SW0001..SW0040",
        "n_response": "terminal CHPDT N3-minus-N0 within W1 and W3; W1 instruction first",
        "observation_ensemble": ensemble_name,
        "parameter_count": {"total": int(check.npar), "adjustable": int(check.npar_adj)},
        "observation_count": int(check.nobs),
        "model_command": check.model_command,
    }
    (TARGET / "four_corner_case_build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
