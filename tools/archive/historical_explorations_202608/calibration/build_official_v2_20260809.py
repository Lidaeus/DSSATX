"""Build official-DSSAT joint calibration (20260809).

Based on the v2 joint calibration
(e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808) with:
  - DSSAT version swapped from the custom a3_nr_zp build to the OFFICIAL
    DSSAT v4.8 executable (D:\\Tomato_Cal\\DSCSM048.EXE == C:\\DSSAT48\\DSCSM048.EXE).
  - Custom genetic parameters REMOVED (they only exist in the custom SPE):
      NREXP, NRMIN   (XPODF extension: A3 threshold / zero-hold NR)
      NUPK50, NUPCMN (NUPT line: hill soil-N uptake response)
    The official SPE (C:\\DSSAT48\\Genotype\\TMGRO048.SPE) has no such lines.
  - Everything else unchanged: 200 reals x 5 iters, rawdiff_terminal objective,
    25SP+26SP actual_trial bundles (22 treatments), IC params, soil physical
    params (SBDM/SLPF/SSKS/SLCL/SLSI), observation/group policies.

Usage:
    python tools/calibration/build_official_v2_20260809.py
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809"
V2_CASE = "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808"
V2_RUN = ROOT / f"workspace/runs/{V2_CASE}"

# Custom genetic parameters that exist only in the a3_nr_zp SPE (XPODF/NUPT
# extension lines).  Removed for the official-DSSAT run.
CUSTOM_PARAMS = ["nrexp", "nrmin", "nupk50", "nupcmn"]

# Official DSSAT v4.8 (stock, Dec 2024).  Byte-identical to C:\\DSSAT48\\DSCSM048.EXE.
OFFICIAL_EXE = ROOT / "DSCSM048.EXE"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")


def main():
    OUT = ROOT / "workspace/runs" / CASE
    if OUT.exists():
        raise FileExistsError(OUT)
    if not V2_RUN.is_dir():
        raise FileNotFoundError(V2_RUN)
    if not OFFICIAL_EXE.is_file():
        raise FileNotFoundError(OFFICIAL_EXE)
    if not OFFICIAL_SPE.is_file():
        raise FileNotFoundError(OFFICIAL_SPE)

    print("[1/5] copying v2 joint calibration as base")
    shutil.copytree(V2_RUN, OUT)
    # Remove v2 run artifacts (keep build files only)
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

    # Rename all files from v2 case to new case
    for p in OUT.iterdir():
        if p.is_file() and V2_CASE in p.name:
            p.rename(OUT / p.name.replace(V2_CASE, CASE))

    print("[2/5] loading PST and removing custom genetic params")
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    remove = [n for n in CUSTOM_PARAMS if n in pst.parameter_data.index]
    missing = [n for n in CUSTOM_PARAMS if n not in pst.parameter_data.index]
    if missing:
        print(f"  WARNING: params not in PST (already removed?): {missing}")
    pst.parameter_data = pst.parameter_data.drop(remove)
    print(f"  removed {len(remove)} custom params: {remove}")

    # Remove from params.csv + tpl so PEST never writes them back
    params_path = OUT / f"{CASE}_params.csv"
    tpl_path = OUT / f"{CASE}_params.csv.tpl"
    params = pd.read_csv(params_path)
    mask = params["name"].astype(str).str.lower().isin(CUSTOM_PARAMS)
    print(f"  params.csv rows removed: {int(mask.sum())}")
    params = params[~mask]
    params.to_csv(params_path, index=False)
    tpl_lines = [l for l in tpl_path.read_text(encoding="utf-8").splitlines()
                 if not any(l.lower().startswith(f"{n},") for n in CUSTOM_PARAMS)]
    tpl_path.write_text("\n".join(tpl_lines) + "\n", encoding="utf-8")

    # Fix bounds issues (same policy as v2 build)
    print("[3/5] fixing bounds")
    for name in pst.parameter_data.index:
        r = pst.parameter_data.loc[name]
        if str(r.partrans) == "fixed":
            v = float(r.parval1)
            pst.parameter_data.at[name, "parlbnd"] = v * 0.999999
            pst.parameter_data.at[name, "parubnd"] = v * 1.000001
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

    # Write PST
    pst.control_data.noptmax = 5
    pst.pestpp_options["ies_num_reals"] = "200"
    pst.pestpp_options["rand_seed"] = "20260809"
    pst.write(str(OUT / f"{CASE}.pst"))

    # PST internal references still point at v2 case names; rewrite them
    pst_path = OUT / f"{CASE}.pst"
    text = pst_path.read_text(encoding="utf-8")
    n = text.count(V2_CASE)
    pst_path.write_text(text.replace(V2_CASE, CASE), encoding="utf-8")
    print(f"  rewrote {n} internal v2 case references -> {CASE}")

    # Manifest: fresh run — drop v2 finalize provenance
    manifest = OUT / "run_manifest.yaml"
    if manifest.is_file():
        lines = [l for l in manifest.read_text(encoding="utf-8").splitlines()
                 if not l.startswith("stage_representative_")]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Observation-ensemble metadata: update run_id to the new case
    oe_json = OUT / f"{CASE}.observation_ensemble.json"
    if oe_json.is_file():
        meta = json.loads(oe_json.read_text(encoding="utf-8"))
        meta["run_id"] = CASE
        oe_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Verify
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    leftover = [n for n in CUSTOM_PARAMS if n in pst2.parameter_data.index]
    tpl_text = tpl_path.read_text(encoding="utf-8").lower()
    tpl_leftover = [n for n in CUSTOM_PARAMS if f"{n}," in tpl_text]
    print(f"\n[4/5] verify: npar={pst2.npar} npar_adj={pst2.npar_adj} nobs={pst2.nobs}")
    print(f"  custom params still in PST: {leftover}")
    print(f"  custom params still in tpl: {tpl_leftover}")
    print(f"  official exe: {OFFICIAL_EXE} ({OFFICIAL_EXE.stat().st_size} bytes)")
    print(f"  official SPE: {OFFICIAL_SPE}")

    receipt = {
        "run_id": CASE,
        "base": "v2 joint calibration (genetic + soilN + soil physical)",
        "dssat_version": "OFFICIAL DSSAT v4.8 (D:\\Tomato_Cal\\DSCSM048.EXE, identical to C:\\DSSAT48\\DSCSM048.EXE)",
        "species_file": str(OFFICIAL_SPE),
        "removed_custom_params": CUSTOM_PARAMS,
        "n_parameters": int(pst2.npar),
        "n_adjustable": int(pst2.npar_adj),
        "n_reals": 200,
        "noptmax": 5,
        "note": "official exe/SPE swapped in at launch; custom genetic params removed",
    }
    (OUT / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print("\n[5/5] done — run smoke test, then launch with launch_official_v2_20260809.py")


if __name__ == "__main__":
    main()
