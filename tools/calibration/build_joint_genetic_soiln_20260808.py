"""Build joint genetic + initial soil N calibration (25SP+26SP, 20260808).

Combines:
  - a3_nr_zp genetic config (108 organ_n + NUPK50/NUPCMN = 110, 103 adj)
  - Initial soil N inversion v2 (L01-L03 adjustable mean±2SD, L04-L05 fixed)
  - rawdiff_terminal objective (both seasons)
  - 200 reals × 5 noptmax

Usage:
    python tools/calibration/build_joint_genetic_soiln_20260808.py
"""

from __future__ import annotations

import hashlib
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
CASE = "e02_v2_joint_genetic_soiln_25sp26sp_200x5_20260808"
OUT = ROOT / "workspace/runs" / CASE
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_joint_genetic_soiln_25sp26sp_20260808.json"
BOUNDS_ID = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
BATCH_25SP = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/DSSBatch.v48"

EXE = ROOT / "windows/windows_a3_nr_zp_20260806/DSCSM048.EXE"
SPE = ROOT / "windows/windows_a3_nr_zp_20260806/Genotype/TMGRO048.SPE"

# a3_nr_zp best member #103 (genetic param init values)
A3_RUN = ROOT / "workspace/runs/e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260808"
A3_CASE = "e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260808"
A3_BEST = "103"

SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2,3,4,5,9,10,11,12,13,14],
     "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"},
    {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1,13)),
     "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"},
]

# Custom N-uptake params (a3_nr_zp)
CUSTOM_PARAMS = {"NUPK50": (8.664, 1.0, 40.0), "NUPCMN": (0.50, 0.0, 2.0)}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _read_ic_n_from_filex(filex_path):
    text = open(filex_path, encoding="utf-8", errors="ignore").read()
    lines = text.splitlines()
    ic_start = next((i for i, l in enumerate(lines) if "*INITIAL CONDITIONS" in l.upper()), None)
    if ic_start is None:
        raise ValueError(f"No IC section in {filex_path}")
    results = {}
    in_layer = False
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
            continue
        if in_layer and line.strip():
            tokens = line.split()
            if len(tokens) >= 5:
                try:
                    tn = int(float(tokens[0]))
                    depth = int(float(tokens[1]))
                    snh4 = float(tokens[3])
                    sno3 = float(tokens[4])
                    layer = depth // 20
                    if 1 <= layer <= 5:
                        results[(tn, layer)] = {"snh4": snh4, "sno3": sno3}
                except (ValueError, IndexError):
                    pass
    return results


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(SPE.resolve())

    print("[1/7] building base PST (dual-season rawdiff_terminal)")
    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(SEASONS[0]["bundle"]),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", CASE, "--noptmax", "5", "--ies-num-reals", "200",
        "--random-seed", "20260808", "--bad-phi-sigma", "1e300",
        "--batch", str(BATCH_25SP), "--harvest-var", "CHPDT",
        "--include-soil", "--out-dir", str(OUT),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol", "--no-include-n-uptake",
    ]
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    print("[2/7] updating genetic param init values to a3_nr_zp #103")
    a3_par = pd.read_csv(A3_RUN / f"{A3_CASE}.4.par.csv")
    real_col = next((c for c in a3_par.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = a3_par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(A3_BEST)
    a3_best = a3_par.loc[mask].iloc[0]
    gen_lookup = {str(c).lower(): float(a3_best[c]) for c in a3_par.columns if c != real_col}

    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    n_updated = 0
    for name in pst.parameter_data.index:
        key = str(name).lower()
        if key in gen_lookup and not key.startswith("ic_") and not key.startswith("sa_"):
            pst.parameter_data.at[name, "parval1"] = gen_lookup[key]
            n_updated += 1
    print(f"  updated {n_updated} genetic param init values to #103")

    print("[3/7] injecting NUPK50/NUPCMN")
    existing = set(pst.parameter_data.index.astype(str).str.lower())
    new_rows = []
    for pname, (init, lower, upper) in CUSTOM_PARAMS.items():
        if pname.lower() in existing:
            continue
        new_rows.append({
            "parnme": pname.lower(), "partrans": "none", "parchglim": "factor",
            "parval1": init, "parlbnd": lower, "parubnd": upper,
            "pargp": "species", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": "",
        })
    if new_rows:
        new_df = pd.DataFrame(new_rows).set_index("parnme")
        new_df = new_df.reindex(columns=pst.parameter_data.columns)
        new_df["parnme"] = new_df.index
        pst.parameter_data = pd.concat([pst.parameter_data, new_df])
        # tpl + params.csv
        tpl = OUT / f"{CASE}_params.csv.tpl"
        lines = tpl.read_text(encoding="utf-8").splitlines()
        params = pd.read_csv(OUT / f"{CASE}_params.csv")
        for pname, (init, _, _) in CUSTOM_PARAMS.items():
            if not any(l.lower().startswith(pname.lower() + ",") for l in lines):
                lines.append(f"{pname},~ {pname} ~")
            if pname.upper() not in params["name"].astype(str).str.upper().values:
                params = pd.concat([params, pd.DataFrame([{"name": pname.upper(), "value": init}])], ignore_index=True)
        tpl.write_text("\n".join(lines) + "\n", encoding="utf-8")
        params.to_csv(OUT / f"{CASE}_params.csv", index=False)
        print(f"  injected {len(new_rows)} custom params")

    print("[4/7] computing IC bounds (L01-L03 mean±2SD)")
    pooled = {l: {"snh4": [], "sno3": []} for l in range(1, 4)}
    all_ic = {}
    for s in SEASONS:
        filex = s["bundle"] / f"{s['excode']}.TMX"
        ic = _read_ic_n_from_filex(filex)
        all_ic[s["excode"]] = ic
        for tn in s["treatments"]:
            for layer in range(1, 4):
                if (tn, layer) in ic:
                    pooled[layer]["snh4"].append(ic[(tn, layer)]["snh4"])
                    pooled[layer]["sno3"].append(ic[(tn, layer)]["sno3"])
    layer_bounds = {}
    for layer in range(1, 4):
        for sp in ["snh4", "sno3"]:
            vals = np.array(pooled[layer][sp])
            lo = max(0.0, vals.mean() - 2.0 * vals.std(ddof=1))
            hi = vals.mean() + 2.0 * vals.std(ddof=1)
            layer_bounds[(layer, sp)] = (lo, hi)
            print(f"  L{layer:02d} {sp.upper()}: bounds=[{lo:.3f}, {hi:.3f}]")

    print("[5/7] injecting IC parameters")
    ic_adj = []
    ic_fix = []
    for s in SEASONS:
        ex = s["excode"]
        for tn in s["treatments"]:
            for layer in range(1, 6):
                key = (tn, layer)
                if key not in all_ic[ex]:
                    continue
                v = all_ic[ex][key]
                for species, init_val in [("SNH4", v["snh4"]), ("SNO3", v["sno3"])]:
                    pname = f"IC_{species}_{ex}_TN{tn:02d}_L{layer:02d}"
                    if layer <= 3:
                        lo, hi = layer_bounds[(layer, species.lower())]
                        ic_adj.append({"name": pname, "init": max(lo, min(hi, init_val)), "lower": lo, "upper": hi})
                    else:
                        ic_fix.append({"name": pname, "init": init_val, "lower": init_val, "upper": init_val})
    print(f"  IC adjustable (L01-L03): {len(ic_adj)}, fixed (L04-L05): {len(ic_fix)}")

    # Inject into PST
    existing = set(pst.parameter_data.index.astype(str).str.lower())
    par_rows = []
    for r in ic_adj:
        if r["name"].lower() not in existing:
            par_rows.append({"parnme": r["name"].lower(), "partrans": "none", "parchglim": "factor",
                             "parval1": r["init"], "parlbnd": r["lower"], "parubnd": r["upper"],
                             "pargp": "initial_conditions", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": ""})
    for r in ic_fix:
        if r["name"].lower() not in existing:
            par_rows.append({"parnme": r["name"].lower(), "partrans": "fixed", "parchglim": "factor",
                             "parval1": r["init"], "parlbnd": r["init"], "parubnd": r["init"],
                             "pargp": "initial_conditions", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": ""})
    if par_rows:
        new_df = pd.DataFrame(par_rows).set_index("parnme")
        new_df = new_df.reindex(columns=pst.parameter_data.columns)
        new_df["parnme"] = new_df.index
        pst.parameter_data = pd.concat([pst.parameter_data, new_df])

    # params.csv + tpl
    all_ic_params = ic_adj + ic_fix
    params = pd.read_csv(OUT / f"{CASE}_params.csv")
    tpl = OUT / f"{CASE}_params.csv.tpl"
    lines = tpl.read_text(encoding="utf-8").splitlines()
    for r in all_ic_params:
        if r["name"].upper() not in params["name"].astype(str).str.upper().values:
            params = pd.concat([params, pd.DataFrame([{"name": r["name"].upper(), "value": r["init"]}])], ignore_index=True)
        if not any(l.lower().startswith(r["name"].lower() + ",") for l in lines):
            lines.append(f"{r['name']},~ {r['name']} ~")
    params.to_csv(OUT / f"{CASE}_params.csv", index=False)
    tpl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("[6/7] finalizing PST")
    run_design = OUT / "joint_design.json"
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    for season in design["seasons"]:
        manifest = Path(season["bundle_path"]) / "input_manifest.json"
        if manifest.is_file():
            season["bundle_manifest_sha256"] = _sha256(manifest)
    run_design.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{run_design.as_posix()}" '
        f'--param-csv {CASE}_params.csv --harvest-var CHPDT '
        f'--keep-nitrogen-outputs --prefix {CASE}'
    ]
    pst.control_data.noptmax = 5
    pst.pestpp_options["ies_num_reals"] = "200"
    pst.pestpp_options["rand_seed"] = "20260808"
    pst.write(str(OUT / f"{CASE}.pst"))

    # Verify
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    ic_adj_count = len([n for n in pst2.parameter_data.index if str(n).lower().startswith("ic_") and pst2.parameter_data.at[n, "partrans"] != "fixed"])
    ic_fix_count = len([n for n in pst2.parameter_data.index if str(n).lower().startswith("ic_") and pst2.parameter_data.at[n, "partrans"] == "fixed"])
    print(f"\n[7/7] verify: npar={pst2.npar} npar_adj={pst2.npar_adj} nobs={pst2.nobs}")
    print(f"  IC adjustable: {ic_adj_count}, IC fixed: {ic_fix_count}")

    receipt = {
        "run_id": CASE,
        "purpose": "Joint genetic + initial soil N calibration",
        "genetic_source": f"a3_nr_zp best #{A3_BEST}",
        "custom_dssat": str(EXE.resolve()),
        "n_parameters": int(pst2.npar),
        "n_adjustable": int(pst2.npar_adj),
        "n_observations": int(pst2.nobs),
        "n_reals": 200, "noptmax": 5,
        "ic_adj": ic_adj_count, "ic_fixed": ic_fix_count,
        "bound_rule": "L01-L03: mean±2SD; L04-L05: fixed",
    }
    (OUT / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
