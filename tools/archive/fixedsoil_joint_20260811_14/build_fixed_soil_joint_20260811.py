"""Build fixed-soil joint calibration: a3 & official variants (20260811).

Based on the v2 joint calibration (e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808)
with three changes:

  1. Soil physical (SOIL_*) and initial soil-N (IC_*) parameters are FIXED
     to the user-approved values from soil_physical_Fix.csv.xlsx and
     soil_n_ic_Fix.csv — they are no longer inverted; the bundles already
     carry these fixed values in SOIL.SOL / FileX.
  2. T8 Phi budgets are re-weighted (new group policy
     t10_rawdiff_terminal_nresp01_soil02_group_policy_20260811.csv):
       SOIL_WATER     0.20 -> 0.05   (x1/4)
       N_RESPONSE     0.10 -> 0.025  (x1/4)
       HARVEST_DRY_TOTAL 0.50 -> 1.50 (x3)
  3. Two DSSAT variants:
       a3       — windows/windows_a3_20260805/dscsm048_a3.exe + its SPE
                  (keeps NREXP/NRMIN/NUPK50/NUPCMN adjustable)
       official — D:\\Tomato_Cal\\DSCSM048.EXE + C:\\DSSAT48\\Genotype\\TMGRO048.SPE
                  (removes the 4 custom genetic params)

Everything else (genetic init values from a3_nr_zp #103, rawdiff_terminal
objective, 25SP+26SP actual_trial bundles, 200x5) is unchanged.

Usage:
    python tools/calibration/build_fixed_soil_joint_20260811.py --variant a3|official
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
V2_CASE = "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808"
V2_RUN = ROOT / f"workspace/runs/{V2_CASE}"
FIX_DIR = ROOT / "figture/soil_param_export_three_20260810"
SOIL_FIX_XLSX = FIX_DIR / "soil_physical_Fix.csv.xlsx"
IC_FIX_CSV = FIX_DIR / "soil_n_ic_Fix.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260811.csv"

VARIANTS = {
    "a3": {
        "suffix": "a3",
        "exe": ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe",
        "spe": ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE",
        "custom_params": ["nrexp", "nrmin", "nupk50", "nupcmn"],  # kept
    },
    "official": {
        "suffix": "official",
        "exe": ROOT / "DSCSM048.EXE",
        "spe": Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE"),
        "custom_params": [],  # already removed below
    },
}
REMOVED_FOR_OFFICIAL = ["nrexp", "nrmin", "nupk50", "nupcmn"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["a3", "official"], required=True)
    args = ap.parse_args()
    variant = VARIANTS[args.variant]

    CASE = f"e02_v2_fixedsoil_joint_{variant['suffix']}_25sp26sp_200x5_20260811"
    OUT = ROOT / "workspace/runs" / CASE
    if OUT.exists():
        raise FileExistsError(OUT)
    if not V2_RUN.is_dir():
        raise FileNotFoundError(V2_RUN)
    if not variant["exe"].is_file():
        raise FileNotFoundError(variant["exe"])
    if not variant["spe"].is_file():
        raise FileNotFoundError(variant["spe"])

    print(f"[1/5] copying v2 joint calibration as base -> {CASE}")
    shutil.copytree(V2_RUN, OUT)
    for pattern in ["*.rec", "*.rmr", "*.phi.*", "*.par.csv", "*.obs.csv",
                    "*.pcs.csv", "*.pdc.csv", "*.base.*", "run_status.json",
                    "*.log", "calibration_finalize", "_agents", "ies_quality",
                    "manager", "*.pid", "multiseason_run_status.json",
                    "best_member_*", "PestEval.OUT", "PestHarvest.OUT",
                    "PestTmtGrow.OUT", "PestNResponse.OUT", "PestSoilWat.OUT",
                    "PestJoint.OUT", "failed_dssat_artifacts"]:
        for p in OUT.glob(pattern):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
    for p in OUT.iterdir():
        if p.is_file() and V2_CASE in p.name:
            p.rename(OUT / p.name.replace(V2_CASE, CASE))

    print("[2/5] loading PST")
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))

    # ---- fix IC/soil params to user-approved values, mark fixed ----
    soil_fix = pd.read_excel(SOIL_FIX_XLSX)
    soil_fixes = dict(zip(soil_fix["param"].astype(str), soil_fix["Fix"].astype(float)))
    ic_fix = pd.read_csv(IC_FIX_CSV)
    ic_fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))
    all_fixes = {**soil_fixes, **ic_fixes}

    fixed_count = 0
    for name in pst.parameter_data.index:
        key = str(name).upper()
        if key not in all_fixes:
            continue
        v = float(all_fixes[key])
        pst.parameter_data.at[name, "parval1"] = v
        pst.parameter_data.at[name, "parlbnd"] = v
        pst.parameter_data.at[name, "parubnd"] = v
        pst.parameter_data.at[name, "partrans"] = "fixed"
        fixed_count += 1
    print(f"  fixed {fixed_count} IC/soil params to approved values")

    # ---- official variant: remove custom genetic params ----
    if args.variant == "official":
        remove = [n for n in REMOVED_FOR_OFFICIAL if n in pst.parameter_data.index]
        pst.parameter_data = pst.parameter_data.drop(remove)
        print(f"  removed {len(remove)} custom params for official variant: {remove}")

    # ---- bounds fix pass ----
    for name in pst.parameter_data.index:
        r = pst.parameter_data.loc[name]
        if str(r.partrans) == "fixed":
            continue
        init = float(r.parval1); lo = float(r.parlbnd); hi = float(r.parubnd)
        if init < lo:
            pst.parameter_data.at[name, "parval1"] = lo
        elif init > hi:
            pst.parameter_data.at[name, "parval1"] = hi
        pv = float(pst.parameter_data.at[name, "parval1"])
        if abs(pv - lo) < 1e-6 and lo > 0:
            pst.parameter_data.at[name, "parval1"] = lo + abs(lo) * 1e-6
        elif abs(pv - hi) < 1e-6 and hi > 0:
            pst.parameter_data.at[name, "parval1"] = hi - abs(hi) * 1e-6

    # ---- params.csv + tpl: update fixed values, drop official customs ----
    params_path = OUT / f"{CASE}_params.csv"
    tpl_path = OUT / f"{CASE}_params.csv.tpl"
    params = pd.read_csv(params_path)
    params["name_upper"] = params["name"].astype(str).str.upper()
    for key, v in all_fixes.items():
        mask = params["name_upper"] == key.upper()
        if mask.any():
            params.loc[mask, "value"] = v
    if args.variant == "official":
        drop = params["name_upper"].isin([c.upper() for c in REMOVED_FOR_OFFICIAL])
        params = params[~drop]
    params = params.drop(columns=["name_upper"])
    params.to_csv(params_path, index=False)
    tpl_lines = [l for l in tpl_path.read_text(encoding="utf-8").splitlines()
                 if not (args.variant == "official" and
                         any(l.lower().startswith(f"{c},") for c in REMOVED_FOR_OFFICIAL))]
    tpl_path.write_text("\n".join(tpl_lines) + "\n", encoding="utf-8")

    # ---- write PST ----
    pst.control_data.noptmax = 5
    pst.pestpp_options["ies_num_reals"] = "200"
    pst.pestpp_options["rand_seed"] = "20260811"
    pst.write(str(OUT / f"{CASE}.pst"))

    # internal case-name references
    pst_path = OUT / f"{CASE}.pst"
    text = pst_path.read_text(encoding="utf-8")
    n = text.count(V2_CASE)
    pst_path.write_text(text.replace(V2_CASE, CASE), encoding="utf-8")
    print(f"  rewrote {n} internal v2 case references -> {CASE}")

    # ---- re-apply T8 weights with the new group policy ----
    print("[3/5] re-applying T8 weights (new Phi budgets)")
    sys.path.insert(0, str(ROOT))
    from src.calibration.build_pest_multiseason import _apply_t8_weights
    mapping = pd.read_csv(OUT / f"{CASE}_run_mapping.csv", encoding="utf-8-sig")
    run_mapping_rows = mapping.to_dict("records")
    _apply_t8_weights(OUT, CASE, GROUP_POLICY, run_mapping_rows)

    # ---- regenerate observation ensemble? weights changed -> ensemble noise
    # uses sigma only (not weight), so the existing ensemble stays valid ----
    oe_json = OUT / f"{CASE}.observation_ensemble.json"
    if oe_json.is_file():
        meta = json.loads(oe_json.read_text(encoding="utf-8"))
        meta["run_id"] = CASE
        oe_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- manifest: drop finalize provenance ----
    manifest = OUT / "run_manifest.yaml"
    if manifest.is_file():
        lines = [l for l in manifest.read_text(encoding="utf-8").splitlines()
                 if not l.startswith("stage_representative_")]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- design: update group_policy + scope ----
    design_path = OUT / "joint_design.json"
    if design_path.is_file():
        d = json.loads(design_path.read_text(encoding="utf-8"))
        d["group_policy"] = "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260811.csv"
        d["shared_parameter_scope"] = (
            f"Joint genetic ({variant['suffix']} DSSAT) only; IC/soil physical params FIXED "
            "to user-approved values (no longer inverted)"
        )
        design_path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- verify ----
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    ic_fixed = len([n for n in pst2.parameter_data.index if n.lower().startswith("ic_")])
    soil_fixed = len([n for n in pst2.parameter_data.index if n.lower().startswith("soil_")])
    adj = [n for n in pst2.parameter_data.index if str(pst2.parameter_data.at[n, "partrans"]) != "fixed"]
    custom = [n for n in adj if n in REMOVED_FOR_OFFICIAL]
    print(f"\n[4/5] verify: npar={pst2.npar} npar_adj={pst2.npar_adj} nobs={pst2.nobs}")
    print(f"  IC params (all fixed): {ic_fixed} | soil params (all fixed): {soil_fixed}")
    print(f"  adjustable ({len(adj)}): custom present={custom}")

    # weight spot checks
    obs = pst2.observation_data
    nres = obs[obs["obgnme"].astype(str).str.upper().str.contains("NRESP")]
    sw = obs[obs["obgnme"].astype(str).str.upper().str.contains("SW0")]
    dry = obs[obs["obgnme"].astype(str).str.upper().str.contains("CHPDT")]
    print(f"  NRESPM mean weight: {nres['weight'].mean():.6f} (v2: 0.0006, expect ~x0.5)")
    print(f"  SOIL_WATER mean weight: {sw['weight'].mean():.4f} (v2: ~3.8, expect ~x0.5)")
    print(f"  DRY_TOTAL(CHPDT) mean weight: {dry['weight'].mean():.6f} (v2: ~0.0014, expect ~x1.73)")

    receipt = {
        "run_id": CASE,
        "variant": args.variant,
        "dssat_exe": str(variant["exe"]),
        "species_file": str(variant["spe"]),
        "fixed_params": {"ic": ic_fixed, "soil": soil_fixed},
        "n_parameters": int(pst2.npar),
        "n_adjustable": int(pst2.npar_adj),
        "n_reals": 200, "noptmax": 5,
        "group_policy": str(GROUP_POLICY),
        "phi_budget_changes": {"SOIL_WATER": "0.20->0.05", "N_RESPONSE": "0.10->0.025", "HARVEST_DRY_TOTAL": "0.50->1.50"},
    }
    (OUT / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print("\n[5/5] done")


if __name__ == "__main__":
    main()
