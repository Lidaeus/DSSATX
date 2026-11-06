"""Full rebuild of fixed-soil joint calibration with water response (20260812).

Rebuilds the PST from scratch (rather than copying the v2 run dir) so the new
water-response objective (WRESPM: same-nitrogen W3-W1 yield contrast) and the
re-weighted Phi budgets enter the PST at build time:

  * build_pest.py --multiseason-design with the new 20260812 design json
    (observation_policy + group_policy with W_RESPONSE budget 0.01)
  * genetic init values from a3_nr_zp #103
  * IC (220) and soil physical (48) params FIXED to user-approved values
    (SLPF = 0.93)
  * a3 variant keeps NREXP/NRMIN/NUPK50/NUPCMN; official variant removes them

Usage:
    python tools/calibration/build_fixed_soil_joint_v2_20260812.py --variant a3|official
"""

from __future__ import annotations

import argparse
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
FIX_DIR = ROOT / "figture/soil_param_export_three_20260810"
SOIL_FIX_XLSX = FIX_DIR / "soil_physical_Fix.csv.xlsx"
IC_FIX_CSV = FIX_DIR / "soil_n_ic_Fix.csv"
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_fixedsoil_joint_25sp26sp_20260812.json"
BOUNDS_ID = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260812.csv"
BATCH_25SP = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/DSSBatch.v48"

SLPF_FIXED = 0.93

VARIANTS = {
    "a3": {
        "exe": ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe",
        "spe": ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE",
        "remove_custom": [],
    },
    "official": {
        "exe": ROOT / "DSCSM048.EXE",
        "spe": Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE"),
        "remove_custom": ["nrexp", "nrmin", "nupk50", "nupcmn"],
    },
}
SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2,3,4,5,9,10,11,12,13,14],
     "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"},
    {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1,13)),
     "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"},
]
A3_RUN = ROOT / "workspace/runs/e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260808"
A3_CASE = "e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260808"
A3_BEST = "103"


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _read_ic_n_from_filex(filex_path):
    """Read ICBL SNH4/SNO3 per treatment/layer from the bundle FileX."""
    lines = open(filex_path, encoding="utf-8", errors="ignore").read().splitlines()
    ic_start = next((i for i, l in enumerate(lines) if "*INITIAL CONDITIONS" in l.upper()), None)
    if ic_start is None:
        raise ValueError(f"No IC section in {filex_path}")
    results = {}
    in_layer = False
    layer = 0
    current_tn = None
    for i in range(ic_start + 1, len(lines)):
        line = lines[i]
        if line.startswith("*") and "INITIAL CONDITIONS" not in line.upper():
            break
        upper = line.upper()
        if "@C" in upper and "PCR" in upper:
            in_layer = False
            continue
        if "@C" in upper and "ICBL" in upper:
            in_layer = True
            layer = 0
            continue
        if in_layer and line.strip():
            tokens = line.split()
            if len(tokens) >= 5 and tokens[0].isdigit():
                try:
                    current_tn = int(float(tokens[0]))
                    depth = int(float(tokens[1]))
                    snh4 = float(tokens[3])
                    sno3 = float(tokens[4])
                    layer = depth // 20
                    if 1 <= layer <= 5:
                        results[(current_tn, layer)] = {"snh4": snh4, "sno3": sno3}
                except (ValueError, IndexError):
                    pass
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(VARIANTS), required=True)
    args = ap.parse_args()
    variant = VARIANTS[args.variant]

    CASE = f"e02_v2_fixedsoil_joint_{args.variant}_25sp26sp_200x5_20260812"
    OUT = ROOT / "workspace/runs" / CASE
    if OUT.exists():
        raise FileExistsError(OUT)
    if not variant["exe"].is_file() or not variant["spe"].is_file():
        raise FileNotFoundError("variant exe/SPE missing")

    print(f"[1/7] building base PST (dual-season rawdiff_terminal + water response)")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(variant["spe"].resolve())
    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(SEASONS[0]["bundle"]),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", CASE, "--noptmax", "5", "--ies-num-reals", "200",
        "--random-seed", "20260812", "--bad-phi-sigma", "1e300",
        "--batch", str(BATCH_25SP), "--harvest-var", "CHPDT",
        "--include-soil", "--out-dir", str(OUT),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol", "--no-include-n-uptake",
    ]
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    print("[2/7] updating genetic init values to a3_nr_zp #103")
    a3_par = pd.read_csv(A3_RUN / f"{A3_CASE}.4.par.csv")
    real_col = next((c for c in a3_par.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = a3_par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(A3_BEST)
    a3_best = a3_par.loc[mask].iloc[0]
    gen_lookup = {str(c).lower(): float(a3_best[c]) for c in a3_par.columns if c != real_col}
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    n_upd = 0
    for name in pst.parameter_data.index:
        key = str(name).lower()
        if key in gen_lookup and not key.startswith(("ic_", "soil_", "sa_")):
            pst.parameter_data.at[name, "parval1"] = gen_lookup[key]
            n_upd += 1
    print(f"  updated {n_upd} genetic init values")

    print("[3/7] fixing IC + soil params to approved values (SLPF=0.93)")
    soil_fix = pd.read_excel(SOIL_FIX_XLSX)
    soil_fixes = dict(zip(soil_fix["param"].astype(str), soil_fix["Fix"].astype(float)))
    soil_fixes["SOIL_SLPF"] = SLPF_FIXED
    ic_fix = pd.read_csv(IC_FIX_CSV)
    ic_fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))
    all_fixes = {**soil_fixes, **ic_fixes}

    # NUPK50/NUPCMN (a3 variant only): the base flow drops them under
    # --no-include-n-uptake; re-inject as adjustable species params.
    if args.variant == "a3":
        for pname, (init, lower, upper) in {"nupk50": (8.664, 1.0, 40.0),
                                            "nupcmn": (0.50, 0.0, 2.0)}.items():
            if pname in pst.parameter_data.index:
                continue
            pst.parameter_data.loc[pname] = {
                "parnme": pname, "partrans": "none", "parchglim": "factor",
                "parval1": init, "parlbnd": lower, "parubnd": upper,
                "pargp": "species", "scale": 1.0, "offset": 0.0,
                "dercom": 1, "extra": "",
            }
        print("  injected NUPK50/NUPCMN (a3)")

    # SSKS/SLCL/SLSI (layers 1-5) are not produced by the base flow; inject
    # them as fixed params with the approved values.
    ssks_injected = 0
    for layer in range(1, 6):
        for name in ("SSKS", "SLCL", "SLSI"):
            key = f"SOIL_{name}_{layer:02d}"
            pname = key.lower()
            if pname in pst.parameter_data.index or key not in all_fixes:
                continue
            v = float(all_fixes[key])
            pst.parameter_data.loc[pname] = {
                "parnme": pname, "partrans": "fixed", "parchglim": "factor",
                "parval1": v, "parlbnd": v, "parubnd": v,
                "pargp": "soil", "scale": 1.0, "offset": 0.0,
                "dercom": 1, "extra": "",
            }
            ssks_injected += 1
    print(f"  injected {ssks_injected} SSKS/SLCL/SLSI soil params")

    # IC params are NOT produced by the base build_pest flow; inject them as
    # fixed params with the user-approved values (read from the bundle FileX).
    ic_injected = 0
    for s in SEASONS:
        ex = s["excode"]
        filex = s["bundle"] / f"{ex}.TMX"
        ic = _read_ic_n_from_filex(filex)
        for tn in s["treatments"]:
            for layer in range(1, 6):
                if (tn, layer) not in ic:
                    continue
                v = ic[(tn, layer)]
                for species, init_val in (("SNH4", v["snh4"]), ("SNO3", v["sno3"])):
                    pname = f"IC_{species}_{ex}_TN{tn:02d}_L{layer:02d}".lower()
                    if pname in pst.parameter_data.index:
                        continue
                    pst.parameter_data.loc[pname] = {
                        "parnme": pname, "partrans": "fixed", "parchglim": "factor",
                        "parval1": init_val, "parlbnd": init_val, "parubnd": init_val,
                        "pargp": "initial_conditions", "scale": 1.0, "offset": 0.0,
                        "dercom": 1, "extra": "",
                    }
                    ic_injected += 1
    print(f"  injected {ic_injected} fixed IC params")

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
    print(f"  fixed {fixed_count} IC/soil params (approved values)")

    if args.variant == "official":
        remove = [n for n in variant["remove_custom"] if n in pst.parameter_data.index]
        pst.parameter_data = pst.parameter_data.drop(remove)
        print(f"  removed {len(remove)} custom params for official")

    print("[4/7] fixing bounds")
    for name in pst.parameter_data.index:
        r = pst.parameter_data.loc[name]
        if str(r.partrans) == "fixed":
            continue
        init, lo, hi = float(r.parval1), float(r.parlbnd), float(r.parubnd)
        if init < lo:
            pst.parameter_data.at[name, "parval1"] = lo
        elif init > hi:
            pst.parameter_data.at[name, "parval1"] = hi
        pv = float(pst.parameter_data.at[name, "parval1"])
        if abs(pv - lo) < 1e-6 and lo > 0:
            pst.parameter_data.at[name, "parval1"] = lo + abs(lo) * 1e-6
        elif abs(pv - hi) < 1e-6 and hi > 0:
            pst.parameter_data.at[name, "parval1"] = hi - abs(hi) * 1e-6

    print("[5/7] writing PST + tpl/params sync")
    pst.control_data.noptmax = 5
    pst.pestpp_options["ies_num_reals"] = "200"
    pst.pestpp_options["rand_seed"] = "20260812"
    pst.write(str(OUT / f"{CASE}.pst"))

    params_path = OUT / f"{CASE}_params.csv"
    tpl_path = OUT / f"{CASE}_params.csv.tpl"
    params = pd.read_csv(params_path)
    tpl_lines = tpl_path.read_text(encoding="utf-8").splitlines()
    # append injected params (IC + SSKS/SLCL/SLSI + a3 NUPK/NUPCMN) to csv+tpl
    for name in pst.parameter_data.index:
        up = name.upper()
        in_csv = up in params["name"].astype(str).str.upper().values
        in_tpl = any(l.lower().startswith(f"{name},") for l in tpl_lines)
        if not in_csv:
            params = pd.concat([params, pd.DataFrame([{"name": up, "value": pst.parameter_data.at[name, "parval1"]}])], ignore_index=True)
        if not in_tpl:
            tpl_lines.append(f"{name},~ {name} ~")
    params["name_upper"] = params["name"].astype(str).str.upper()
    for key, v in all_fixes.items():
        mask = params["name_upper"] == key.upper()
        if mask.any():
            params.loc[mask, "value"] = v
    if args.variant == "official":
        drop = params["name_upper"].isin([c.upper() for c in variant["remove_custom"]])
        params = params[~drop]
    params = params.drop(columns=["name_upper"])
    params.to_csv(params_path, index=False)
    tpl_lines = [l for l in tpl_lines
                 if not (args.variant == "official" and
                         any(l.lower().startswith(f"{c},") for c in variant["remove_custom"]))]
    tpl_path.write_text("\n".join(tpl_lines) + "\n", encoding="utf-8")

    # internal case refs (design_id inside design json already new)
    pst_path = OUT / f"{CASE}.pst"
    pst_path.write_text(pst_path.read_text(encoding="utf-8"), encoding="utf-8")

    print("[6/7] design json localization")
    run_design = OUT / "joint_design.json"
    d = json.loads(DESIGN.read_text(encoding="utf-8"))
    for season in d["seasons"]:
        manifest = Path(season["bundle_path"]) / "input_manifest.json"
        if manifest.is_file():
            season["bundle_manifest_sha256"] = _sha256(manifest)
    run_design.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pst2 = pyemu.Pst(str(pst_path))
    pst2.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{run_design.as_posix()}" '
        f'--param-csv {CASE}_params.csv --harvest-var CHPDT '
        f'--keep-nitrogen-outputs --prefix {CASE}'
    ]
    pst2.write(str(pst_path))

    print("[7/7] verify")
    pst3 = pyemu.Pst(str(pst_path))
    obs = pst3.observation_data
    wresp = obs[obs["obgnme"].astype(str).str.upper().str.contains("WRESP")]
    nresp = obs[obs["obgnme"].astype(str).str.upper().str.contains("NRESP")]
    ic_fixed = len([n for n in pst3.parameter_data.index if n.lower().startswith("ic_")])
    soil_fixed = len([n for n in pst3.parameter_data.index if n.lower().startswith("soil_")])
    print(f"  npar={pst3.npar} npar_adj={pst3.npar_adj} nobs={pst3.nobs}")
    print(f"  WRESPM obs: {len(wresp)} | NRESPM obs: {len(nresp)}")
    print(f"  IC fixed: {ic_fixed} | soil fixed: {soil_fixed}")
    if len(wresp):
        print(f"  WRESPM mean weight: {wresp['weight'].mean():.6f}")
    slpf = pst3.parameter_data.loc["soil_slpf", "parval1"] if "soil_slpf" in pst3.parameter_data.index else None
    print(f"  soil_slpf fixed = {slpf}")

    receipt = {
        "run_id": CASE, "variant": args.variant,
        "dssat_exe": str(variant["exe"]), "species_file": str(variant["spe"]),
        "slpf": SLPF_FIXED,
        "n_parameters": int(pst3.npar), "n_adjustable": int(pst3.npar_adj),
        "n_observations": int(pst3.nobs),
        "wresp_observations": int(len(wresp)),
        "water_response": "W3-W1 within same nitrogen, raw_difference, W_RESPONSE budget 0.01",
        "group_policy": "t10_rawdiff_terminal_nresp01_soil02_group_policy_20260812.csv",
    }
    (OUT / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
