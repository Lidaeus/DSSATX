"""Prepare the audited A3 (0805) E02 S1/S2 calibration contract.

The script is intentionally deterministic: the Morris top-95 frozen rows are
copied verbatim, the four A3-0805 SPE parameters are appended from the
versioned A3 formal PST, and the staged design keeps every other parameter
explicitly fixed.  It does not launch PEST++.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
MORRIS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_two_spring_morris_top95_genetic_precal_20260804.csv"
SOURCE_PST = ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_6treat_150x4_20260805_a3_0805/e02_v2_rawdiff_terminal_nresp01_soil02_6treat_150x4_20260805_a3_0805.pst"
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_e02_s1s2_morris_top95_plus_a3_0805_v3_20260806.csv"
DESIGN = ROOT / "configs/runs/eggplant_e02_s1s2_morris_top95_plus_a3_0805_20260806.json"
SPLIT = ROOT / "configs/runs/eggplant_e02_s1s2_25sp_six_treatment_split_20260806.json"
MULTI = ROOT / "configs/runs/eggplant_e02_s1s2_a3_0805_multiseason_20260806.json"
BUNDLE = ROOT / "data/user/experiments/xxql2501_corrected_management_layermean_20260806"

CUSTOM = {
    "NREXP": (0.65, 0.50, 1.00),
    "NRMIN": (0.70, 0.60, 0.80),
    "NUPK50": (8.664, 1.00, 40.00),
    "NUPCMN": (0.50, 0.01, 2.00),
}

S1 = [
    "CMOBMX", "EM-FL", "EM-V1", "FL-SD", "FRLFF", "LFMAX", "NMOBMX",
    "NVSMOB", "PM06", "RWUMX", "SENDAY", "TB1", "TB2", "TO11", "TO12",
    "TRIFL", "XFINT",
]
S2 = [
    "PROLFF", "PROLFG", "PROLFI", "PRORTF", "PRORTG", "PRORTI", "PROSHF",
    "PROSHI", "PROSTF", "PROSTG", "PROSTI", "RTNH4", "RTNO3", "XFRT",
    "NREXP", "NRMIN", "NUPK50", "NUPCMN",
]
BASE_NAMES = [
    "CMOBMX", "CSDL", "EM-FL", "EM-V1", "FL-LF", "FL-SD", "FL-SH", "FRLFF",
    "JU-R0", "KC_SLOPE", "LFMAX", "NMOBMX", "NRCVR", "NREXP", "NRMIN",
    "NSTFAC", "NUPCMN", "NUPK50", "NVSMOB", "PL-EM", "PM06", "PODUR", "PPSEN",
    "PROLFF", "PROLFG", "PROLFI", "PRORTF", "PRORTG", "PRORTI", "PROSHF", "PROSHI",
    "PROSTF", "PROSTG", "PROSTI", "RHGHT", "RTEXF", "RTNH4", "RTNO3", "RWDTH", "RWUMX",
    "SD-PM", "SDPDV", "SENDAY", "SFDUR", "SIZLF", "SLAVR",
    *[f"SOIL_SBDM_{i:02d}" for i in range(1, 9)],
    "TB1", "TB2", "TB3", "THRSH", "TM1", "TM2", "TM3", "TO11", "TO12", "TO13", "TO21", "TO22", "TO23",
    "TRIFL", "V1-JU", "VSSINK", "WTPSD", "XFINT", "XFPHT", "XFRT", "XMAGE", "FL-VS",
]


def main() -> None:
    if len(set(S1 + S2)) != len(S1) + len(S2):
        raise RuntimeError("S1/S2 active parameter lists overlap")
    morris = pd.read_csv(MORRIS, encoding="utf-8-sig")
    morris["name"] = morris["name"].astype(str).str.strip().str.upper()
    active = morris[morris["status"].astype(str).str.lower().eq("active")].copy()
    if len(active) != 31:
        raise RuntimeError(f"expected 31 Morris active rows, got {len(active)}")
    if set(S1 + S2) - set(active["name"]) - set(CUSTOM):
        missing = sorted(set(S1 + S2) - set(active["name"]) - set(CUSTOM))
        raise RuntimeError(f"staged list is not based on the Morris active set: {missing}")

    source = pyemu.Pst(str(SOURCE_PST)).parameter_data
    rows = []
    for _, row in active.iterrows():
        rows.append(dict(row))
    for name, (init, lower, upper) in CUSTOM.items():
        if name.lower() not in source.index:
            raise RuntimeError(f"A3-0805 source PST lacks {name}")
        sr = source.loc[name.lower()]
        rows.append(
            {
                "name": name,
                "init": init,
                "lower": lower,
                "upper": upper,
                "status": "active",
                "pargp": "SPE_N_UPTAKE_A3",
                "location": "SPE",
                "file": "TMGRO048.SPE",
                "cultivar": "TM0008",
                "ecotype": "TM0001",
                "mode": "eggplant_stage2",
                "source_init": float(sr.parval1),
                "source_lower": float(sr.parlbnd),
                "source_upper": float(sr.parubnd),
                "evidence": "A3 0805 custom SPE parameter; bounds copied from audited A3-0805 formal contract",
            }
        )
    out = pd.DataFrame(rows)
    out = out.drop_duplicates("name", keep="last")
    if set(out.loc[out["status"].astype(str).str.lower().eq("active"), "name"]) != set(S1 + S2):
        raise RuntimeError("combined bounds are not exactly Morris active + A3 custom parameters")
    out = pd.concat([out, pd.DataFrame([{
        "name": "FL-VS", "init": 120.0, "lower": 120.0, "upper": 120.0, "status": "fixed",
        "pargp": "structure", "location": "ECO", "file": "TMGRO048.ECO", "cultivar": "TM0008",
        "ecotype": "TM0001", "mode": "eggplant_stage2", "evidence": "project invariant; FL-VS fixed at 120"
    }])], ignore_index=True)
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")

    all_params = list(dict.fromkeys(BASE_NAMES))
    fixed_s1 = [p for p in all_params if p not in S1]
    fixed_s2 = [p for p in all_params if p not in S2]
    payload = {
        "schema_version": 1,
        "design_table_id": "eggplant_e02_s1s2_morris_top95_plus_a3_0805_v3_20260806",
        "bounds_id": "eggplant_e02_s1s2_morris_top95_plus_a3_0805_v3_20260806",
        "input_bundle": "xxql2501_corrected_management_layermean_20260806",
        "observation_policy_id": "e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805",
        "approval_scope": "science_use",
        "validation_split_id": SPLIT.stem,
        "stages": {
            "S1": {
                "active_params": S1,
                "fixed_params": fixed_s1,
                "observation_outputs": {
                    "PestEval.OUT": ["ADAP"],
                    "PestJoint.OUT": ["LAIX", "CNAM"],
                    "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD"],
                },
                "representative_outputs": {"PestEval.OUT": ["ADAP"], "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD"]},
                "purpose": "冠层形态建成预率定；S2 释放前固定全部收获/终值及 A3 氮响应参数",
            },
            "S2": {
                "active_params": S2,
                "fixed_params": fixed_s2,
                "observation_outputs": {
                    "PestJoint.OUT": ["LAIX", "CNAM"],
                    "PestHarvest.OUT": ["CHFPW", "CHPDT", "HPODW"],
                    "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD"],
                    "PestNResponse.OUT": ["NRESP"],
                },
                "representative_outputs": {
                    "PestHarvest.OUT": ["CHPDT", "HPODW"],
                    "PestJoint.OUT": ["LAIX", "CNAM"],
                },
                "purpose": "收获过程和终值预率定；继承 S1 代表参数",
            },
        },
    }
    DESIGN.parent.mkdir(parents=True, exist_ok=True)
    DESIGN.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SPLIT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "split_id": SPLIT.stem,
                "treatment_roles": {"calibration": [3, 4, 5, 11, 12, 13], "validation": [], "diagnostic": []},
                "notes": "E02 S1/S2 pre-calibration uses corrected 25SP six-treatment bundle; no autumn season.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_sha = __import__("hashlib").sha256((BUNDLE / "input_manifest.json").read_bytes()).hexdigest()
    multi = {
        "schema_version": 1,
        "design_id": "eggplant_e02_s1s2_a3_0805_multiseason_20260806",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Morris top-95 active parameters plus A3 0805 custom SPE parameters",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260805.csv",
        "nitrogen_response_objective": {
            "enabled": True,
            "mapping_csv": "configs/runs/e02_v2_25sp_water_n_mapping_corrected_20260805.csv",
            "source_variable": "CHPDT",
            "contrast": "N2_minus_N0_within_same_water",
            "contrast_scale": "raw_difference",
            "response_target": "observed_shape",
            "levels": ["N1", "N2"],
            "harvest_scope": "all",
            "sigma_floor": 50.0,
            "budget_rule": "0.10 static N_RESPONSE budget within corrected 25SP six-treatment design",
        },
        "harvest_dry_objective": {"enabled": True, "mode": "increment_plus_terminal", "increment_source": "measured_hpodw", "terminal_variable": "CHPDT"},
        "process_state_objective": {"enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]},
        "seasonal_parameterization": None,
        "seasons": [{
            "season_id": "25SP",
            "experiment_code": "XXQL2501",
            "bundle_path": "data/user/experiments/xxql2501_corrected_management_layermean_20260806",
            "bundle_manifest_sha256": manifest_sha,
            "role": "calibration",
            "treatments": [13, 12, 11, 5, 4, 3],
        }],
        "formal": {"n_reals": 100, "noptmax": 3, "initial_ensemble_method": "sobol"},
        "diagnostic_single_season": True,
        "custom_dssat_executable": str((ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe").resolve()),
        "custom_spe": str((ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE").resolve()),
        "fl_vs_fixed": 120.0,
    }
    MULTI.parent.mkdir(parents=True, exist_ok=True)
    MULTI.write_text(json.dumps(multi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"proposal": str(PROPOSAL), "design": str(DESIGN), "split": str(SPLIT), "multiseason": str(MULTI), "all_fixed_count": len(all_params), "s1_active": len(S1), "s2_active": len(S2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
