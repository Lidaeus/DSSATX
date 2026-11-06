"""Build joint genetic + soil N + soil physical params calibration (v2, 20260808).

Extends the joint genetic+soilN calibration with:
  - Soil bulk density (SBDM): small range around current values
  - Soil fertility (SLPF): 0.86-0.96
  - Saturated hydraulic conductivity (SSKS): 5% float
  - Clay/silt texture (SLCL/SLSI): 5% float

All soil physical params are per-layer (8 layers), shared across both seasons.
Only layers with measured values (not -99) get texture/hydraulic params.

Usage:
    python tools/calibration/build_joint_v2_20260808.py
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
# Reuse the v1 joint build as base, then add soil physical params
V1_SCRIPT = ROOT / "tools/calibration/build_joint_genetic_soiln_20260808.py"
CASE = "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808"
V1_CASE = "e02_v2_joint_genetic_soiln_25sp26sp_200x5_20260808"
V1_RUN = ROOT / f"workspace/runs/{V1_CASE}"

# Soil physical params from SOIL.SOL profile IBTM910017 (8 layers)
# Layer data: [SLB, SSKS, SBDM, SLOC, SLCL, SLSI]
SOIL_LAYERS = [
    {"layer": 1, "slb": 20,  "ssks": 0.23, "sbdm": 1.36, "slcl": 35, "slsi": 30},
    {"layer": 2, "slb": 40,  "ssks": 0.23, "sbdm": 1.55, "slcl": 35, "slsi": 30},
    {"layer": 3, "slb": 60,  "ssks": 0.23, "sbdm": 1.56, "slcl": 35, "slsi": 30},
    {"layer": 4, "slb": 80,  "ssks": 0.23, "sbdm": 1.51, "slcl": 35, "slsi": 30},
    {"layer": 5, "slb": 100, "ssks": 0.23, "sbdm": 1.47, "slcl": 35, "slsi": 30},
    {"layer": 6, "slb": 145, "ssks": None, "sbdm": 1.59, "slcl": None, "slsi": None},
    {"layer": 7, "slb": 175, "ssks": None, "sbdm": 1.61, "slcl": None, "slsi": None},
    {"layer": 8, "slb": 203, "ssks": None, "sbdm": 1.58, "slcl": None, "slsi": None},
]


def main():
    OUT = ROOT / "workspace/runs" / CASE
    if OUT.exists():
        raise FileExistsError(OUT)

    print("[1/4] copying v1 joint calibration as base")
    shutil.copytree(V1_RUN, OUT)
    # Remove v1 run artifacts (keep build files only)
    for pattern in ["*.rec", "*.rmr", "*.phi.*", "*.par.csv", "*.obs.csv",
                    "*.pcs.csv", "*.pdc.csv", "*.base.*", "run_status.json",
                    "*.log", "calibration_finalize", "_agents", "ies_quality",
                    "manager", "*.pid", "multiseason_run_status.json",
                    "PestEval.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT",
                    "PestNResponse.OUT", "PestSoilWat.OUT", "PestJoint.OUT"]:
        for p in OUT.glob(pattern):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)

    # Rename all files from v1 case to new case
    for p in OUT.iterdir():
        if p.is_file() and V1_CASE in p.name:
            p.rename(OUT / p.name.replace(V1_CASE, CASE))

    print("[2/4] loading PST and adding soil physical params")
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))

    # SLPF: override to 0.86-0.96
    if "soil_slpf" in pst.parameter_data.index:
        pst.parameter_data.at["soil_slpf", "partrans"] = "none"
        pst.parameter_data.at["soil_slpf", "parval1"] = 0.91  # midpoint
        pst.parameter_data.at["soil_slpf", "parlbnd"] = 0.86
        pst.parameter_data.at["soil_slpf", "parubnd"] = 0.96
        print("  SLPF: 0.86-0.96 (was fixed)")

    # SBDM: already in PST (8 layers), widen to ±3% around current init
    for lyr in SOIL_LAYERS:
        key = f"soil_sbdm_{lyr['layer']:02d}"
        if key in pst.parameter_data.index:
            r = pst.parameter_data.loc[key]
            init = float(r.parval1)
            margin = init * 0.03
            pst.parameter_data.at[key, "partrans"] = "none"
            pst.parameter_data.at[key, "parlbnd"] = init - margin
            pst.parameter_data.at[key, "parubnd"] = init + margin
            print(f"  {key}: {init-margin:.4f} - {init+margin:.4f}")

    # New params: SSKS, SLCL, SLSI
    new_soil_params = []
    for lyr in SOIL_LAYERS:
        li = lyr["layer"]
        # SSKS (only layers 1-5 have measured values)
        if lyr["ssks"] is not None:
            val = lyr["ssks"]
            margin = max(val * 0.05, 0.01)
            new_soil_params.append(("SOIL_SSKS", li, val, max(0, val - margin), val + margin))
        # SLCL (only layers 1-5)
        if lyr["slcl"] is not None:
            val = float(lyr["slcl"])
            margin = val * 0.05
            new_soil_params.append(("SOIL_SLCL", li, val, max(0, val - margin), val + margin))
        # SLSI (only layers 1-5)
        if lyr["slsi"] is not None:
            val = float(lyr["slsi"])
            margin = val * 0.05
            new_soil_params.append(("SOIL_SLSI", li, val, max(0, val - margin), val + margin))

    existing = set(pst.parameter_data.index.astype(str).str.lower())
    par_rows = []
    for base, li, init, lo, hi in new_soil_params:
        # base is e.g. "SOIL_SSKS"; strip the SOIL_ prefix so the PEST name
        # is soil_ssks_01 — run_dssat._as_layer_key() produces SOIL_SSKS_01
        # for the params.csv lookup, so both sides must share the same name.
        pname = f"soil_{base[5:].lower()}_{li:02d}"
        if pname in existing:
            # Update existing (SBDM already exists; SSKS/SLCL/SLSI are new)
            pst.parameter_data.at[pname, "partrans"] = "none"
            pst.parameter_data.at[pname, "parval1"] = init
            pst.parameter_data.at[pname, "parlbnd"] = lo
            pst.parameter_data.at[pname, "parubnd"] = hi
        else:
            par_rows.append({
                "parnme": pname, "partrans": "none", "parchglim": "factor",
                "parval1": init, "parlbnd": lo, "parubnd": hi,
                "pargp": "soil", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": "",
            })

    if par_rows:
        new_df = pd.DataFrame(par_rows).set_index("parnme")
        new_df = new_df.reindex(columns=pst.parameter_data.columns)
        new_df["parnme"] = new_df.index
        pst.parameter_data = pd.concat([pst.parameter_data, new_df])
    print(f"  added {len(par_rows)} new soil params (SSKS/SLCL/SLSI)")

    # Update params.csv + tpl
    params = pd.read_csv(OUT / f"{CASE}_params.csv")
    tpl_lines = (OUT / f"{CASE}_params.csv.tpl").read_text(encoding="utf-8").splitlines()
    for base, li, init, _, _ in new_soil_params:
        pname = f"SOIL_{base[5:]}_{li:02d}"
        if pname.upper() not in params["name"].astype(str).str.upper().values:
            params = pd.concat([params, pd.DataFrame([{"name": pname, "value": init}])], ignore_index=True)
        if not any(l.lower().startswith(pname.lower() + ",") for l in tpl_lines):
            tpl_lines.append(f"{pname},~ {pname} ~")
    # Update SLPF value
    slpf_mask = params["name"].astype(str).str.upper() == "SOIL_SLPF"
    if slpf_mask.any():
        params.loc[slpf_mask, "value"] = 0.91
    params.to_csv(OUT / f"{CASE}_params.csv", index=False)
    (OUT / f"{CASE}_params.csv.tpl").write_text("\n".join(tpl_lines) + "\n", encoding="utf-8")

    # Fix any bounds issues (clip init to bounds, margin for fixed params)
    print("[3/4] fixing bounds")
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
    pst.pestpp_options["rand_seed"] = "20260808"
    pst.write(str(OUT / f"{CASE}.pst"))

    # The copied v1 PST/tpl/ins still reference the v1 case name internally
    # (template/instruction filenames, model command, ies_observation_ensemble).
    # Rewrite them to the v2 case so the PST is self-consistent.
    pst_path = OUT / f"{CASE}.pst"
    text = pst_path.read_text(encoding="utf-8")
    n = text.count(V1_CASE)
    pst_path.write_text(text.replace(V1_CASE, CASE), encoding="utf-8")
    print(f"  rewrote {n} internal v1 case references -> {CASE}")

    # Manifest: fresh run — drop v1 finalize provenance
    manifest = OUT / "run_manifest.yaml"
    if manifest.is_file():
        lines = [l for l in manifest.read_text(encoding="utf-8").splitlines()
                 if not l.startswith("stage_representative_")]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Remove v1 evaluation leftovers copied from the base run
    for leftover in OUT.glob("best_member_*"):
        shutil.rmtree(leftover, ignore_errors=True)
    for season in (OUT / "_seasons").glob("*") if (OUT / "_seasons").is_dir() else []:
        audit = season / "dssat_input_resolution_audit.json"
        if audit.is_file():
            audit.unlink()

    # Verify
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    soil_phys = [n for n in pst2.parameter_data.index if any(
        n.lower().startswith(p) for p in ["soil_ssks_", "soil_slcl_", "soil_slsi_"])]
    print(f"\n[4/4] verify: npar={pst2.npar} npar_adj={pst2.npar_adj} nobs={pst2.nobs}")
    print(f"  new soil physical params (SSKS/SLCL/SLSI): {len(soil_phys)}")
    print(f"  SLPF range: [{pst2.parameter_data.at['soil_slpf','parlbnd']}, {pst2.parameter_data.at['soil_slpf','parubnd']}]")

    receipt = {
        "run_id": CASE, "base": "joint genetic+soilN v1 + soil physical params",
        "n_parameters": int(pst2.npar), "n_adjustable": int(pst2.npar_adj),
        "n_reals": 200, "noptmax": 5,
        "new_params": f"SLPF(0.86-0.96), SBDM(±3%), SSKS/SLCL/SLSI(±5%, layers 1-5 only)",
    }
    (OUT / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
