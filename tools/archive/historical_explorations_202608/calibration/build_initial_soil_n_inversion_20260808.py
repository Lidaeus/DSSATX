"""Build the initial soil N inversion calibration (25SP+26SP, 20260808).

Inverts treatment-specific initial SNH4/SNO3 (5 layers each) for 25SP (10
treatments) and 26SP (12 treatments), with all 108 genetic parameters from
best member #139 fixed.

Parameter count: 220 adjustable IC params (22 treatments × 5 layers × 2 species)
+ 108 fixed genetic params = 328 total.

Usage:
    python tools/calibration/build_initial_soil_n_inversion_20260808.py
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_v2_initial_soil_n_25sp26sp_100x4_20260808"
OUT = ROOT / "workspace/runs" / CASE
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_initial_soil_n_25sp26sp_20260808.json"
BOUNDS_ID = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
POLICY = ROOT / "configs/runs/e02_v2_joint25sp26sp_nosoil_nresp_policy_20260802.csv"
BATCH_25SP = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/DSSBatch.v48"
BATCH_26SP = ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729/DSSBatch.v48"

EXE = ROOT / "windows/windows_nresp_20260806/DSCSM048.EXE"
SPE = ROOT / "windows/windows_nresp_20260806/Genotype/TMGRO048.SPE"

# Best member #139 genetic params (all to be fixed)
BATCH_B_RUN = ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806"
BATCH_B_CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806"
BEST_MEMBER = "139"

# Season configs
SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2,3,4,5,9,10,11,12,13,14],
     "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"},
    {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1,13)),
     "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"},
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_ic_n_from_filex(filex_path: Path) -> dict:
    """Read treatment-specific SNH4/SNO3 from FileX *INITIAL CONDITIONS section.
    Returns {(excode, tn, layer_idx): {'snh4': val, 'sno3': val}}.
    """
    text = filex_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    # Find *INITIAL CONDITIONS
    ic_start = None
    for i, line in enumerate(lines):
        if "*INITIAL CONDITIONS" in line.upper():
            ic_start = i
            break
    if ic_start is None:
        raise ValueError(f"No *INITIAL CONDITIONS in {filex_path}")

    results = {}
    current_tn = None
    in_layer_block = False

    for i in range(ic_start + 1, len(lines)):
        line = lines[i]
        if line.startswith("!") or not line.strip():
            continue
        # Next section marker ends IC
        if line.startswith("*") and "INITIAL CONDITIONS" not in line.upper():
            break

        upper = line.upper()
        # Treatment header: @C   PCR ICDAT ...
        if "@C" in upper and "PCR" in upper:
            current_tn = None
            in_layer_block = False
            continue

        # Layer header: @C  ICBL  SH2O  SNH4  SNO3
        if "@C" in upper and "ICBL" in upper:
            in_layer_block = True
            continue

        if in_layer_block and line.strip():
            # Parse fixed-width: cols are IC(3) ICBL(6) SH2O(6) SNH4(6) SNO3(6)
            # But fields may be space-separated or touching; use regex
            tokens = line.split()
            if len(tokens) >= 5:
                try:
                    tn = int(float(tokens[0]))
                    depth = int(float(tokens[1]))
                    sh2o = float(tokens[2])
                    snh4 = float(tokens[3])
                    sno3 = float(tokens[4])
                    # Layer index by depth: 20->L01, 40->L02, 60->L03, 80->L04, 100->L05
                    layer_idx = depth // 20
                    if 1 <= layer_idx <= 5:
                        results[(tn, layer_idx)] = {"snh4": snh4, "sno3": sno3}
                except (ValueError, IndexError):
                    pass
    return results


def _export_best_member_params() -> pd.DataFrame:
    """Export best member #139 genetic params."""
    frame = pd.read_csv(BATCH_B_RUN / f"{BATCH_B_CASE}.4.par.csv")
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST_MEMBER)
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        records.append({"name": str(col).upper(), "value": float(row[col])})
    return pd.DataFrame(records)


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"target exists: {OUT}")
    if not EXE.is_file():
        raise FileNotFoundError(EXE)
    if not SPE.is_file():
        raise FileNotFoundError(SPE)

    print("[1/6] building base PST via build_pest.py (dual-season multiseason)")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(SPE.resolve())

    # build_pest needs a single --batch and --input-dir; for multiseason it
    # reads bundle_path from the design json per season. We pass the 25SP bundle
    # as --input-dir (it's the first season) and the full design for both seasons.
    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(DESIGN),
        "--input-dir", str(SEASONS[0]["bundle"]),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", CASE,
        "--noptmax", "4", "--ies-num-reals", "100",
        "--random-seed", "20260808",
        "--bad-phi-sigma", "1e300",
        "--batch", str(BATCH_25SP),
        "--harvest-var", "CHPDT",
        "--include-soil",
        "--out-dir", str(OUT),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol",
        "--no-include-n-uptake",
    ]
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    print("[2/6] freezing all genetic parameters to best member #139 values")
    genetic_params = _export_best_member_params()
    gen_lookup = {str(r["name"]).lower(): float(r["value"]) for _, r in genetic_params.iterrows()}

    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    n_frozen = 0
    for name in pst.parameter_data.index:
        key = str(name).lower()
        if key in gen_lookup and not key.startswith("ic_") and not key.startswith("sa_"):
            val = gen_lookup[key]
            pst.parameter_data.at[name, "partrans"] = "fixed"
            pst.parameter_data.at[name, "parval1"] = val
            pst.parameter_data.at[name, "parlbnd"] = val
            pst.parameter_data.at[name, "parubnd"] = val
            n_frozen += 1
    print(f"  frozen {n_frozen} genetic parameters to #139 values")

    print("[3/6] reading treatment-specific IC SNH4/SNO3 from FileX")
    # Compute pooled mean/SD per layer (L01-L03) across both seasons for bounds.
    # L04-L05 will be FIXED (not adjustable); L01-L03 bounds = mean ± 2*SD (clip 0).
    import numpy as _np
    pooled = {l: {"snh4": [], "sno3": []} for l in range(1, 4)}
    all_ic_data = {}
    for season in SEASONS:
        excode = season["excode"]
        filex = season["bundle"] / f"{excode}.TMX"
        ic_data = _read_ic_n_from_filex(filex)
        all_ic_data[excode] = ic_data
        print(f"  {season['season_id']} ({excode}): {len(ic_data)} IC layer rows from {len(season['treatments'])} treatments")
        for tn in season["treatments"]:
            for layer in range(1, 4):
                key = (tn, layer)
                if key in ic_data:
                    pooled[layer]["snh4"].append(ic_data[key]["snh4"])
                    pooled[layer]["sno3"].append(ic_data[key]["sno3"])

    # Bounds: mean ± 2*SD, clipped at 0
    layer_bounds = {}
    for layer in range(1, 4):
        for species in ["snh4", "sno3"]:
            vals = _np.array(pooled[layer][species])
            mean = vals.mean()
            sd = vals.std(ddof=1)
            lower = max(0.0, mean - 2.0 * sd)
            upper = mean + 2.0 * sd
            layer_bounds[(layer, species)] = (lower, upper, mean, sd)
            print(f"  L{layer:02d} {species.upper()}: mean={mean:.3f} sd={sd:.3f} -> bounds=[{lower:.3f}, {upper:.3f}]")

    ic_rows = []       # adjustable IC params (L01-L03 only)
    ic_fixed_rows = []  # fixed IC params (L04-L05, written to params.csv but not adjustable)
    for season in SEASONS:
        excode = season["excode"]
        ic_data = all_ic_data[excode]
        for tn in season["treatments"]:
            for layer in range(1, 6):
                key = (tn, layer)
                if key not in ic_data:
                    continue
                vals = ic_data[key]
                for species, init_val in [("SNH4", vals["snh4"]), ("SNO3", vals["sno3"])]:
                    param_name = f"IC_{species}_{excode}_TN{tn:02d}_L{layer:02d}"
                    if layer <= 3:
                        lb, ub, _, _ = layer_bounds[(layer, species.lower())]
                        # Ensure init is within bounds
                        init_clipped = max(lb, min(ub, init_val))
                        ic_rows.append({
                            "name": param_name, "init": init_clipped,
                            "lower": lb, "upper": ub,
                        })
                    else:
                        # L04-L05: fixed at FileX value
                        ic_fixed_rows.append({
                            "name": param_name, "init": init_val,
                            "lower": init_val, "upper": init_val,
                        })

    print(f"  adjustable IC parameters (L01-L03): {len(ic_rows)}")
    print(f"  fixed IC parameters (L04-L05): {len(ic_fixed_rows)}")

    print("[4/6] injecting IC parameters into PST + params.csv + tpl")
    existing = set(pst.parameter_data.index.astype(str).str.lower())
    new_par_rows = []
    # Adjustable IC params (L01-L03)
    for r in ic_rows:
        pname = r["name"].lower()
        if pname in existing:
            continue
        new_par_rows.append({
            "parnme": pname, "partrans": "none", "parchglim": "factor",
            "parval1": r["init"], "parlbnd": r["lower"], "parubnd": r["upper"],
            "pargp": "initial_conditions", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": "",
        })
    # Fixed IC params (L04-L05) — added as fixed in PST so run_dssat reads them
    for r in ic_fixed_rows:
        pname = r["name"].lower()
        if pname in existing:
            continue
        new_par_rows.append({
            "parnme": pname, "partrans": "fixed", "parchglim": "factor",
            "parval1": r["init"], "parlbnd": r["init"], "parubnd": r["init"],
            "pargp": "initial_conditions", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": "",
        })
    if new_par_rows:
        new_df = pd.DataFrame(new_par_rows).set_index("parnme")
        new_df = new_df.reindex(columns=pst.parameter_data.columns)
        new_df["parnme"] = new_df.index
        pst.parameter_data = pd.concat([pst.parameter_data, new_df])

    # Update params.csv — include BOTH adjustable and fixed IC params
    params = pd.read_csv(OUT / f"{CASE}_params.csv")
    all_ic = ic_rows + ic_fixed_rows
    for r in all_ic:
        if r["name"].upper() not in params["name"].astype(str).str.upper().values:
            params = pd.concat([params, pd.DataFrame([{"name": r["name"].upper(), "value": r["init"]}])], ignore_index=True)
    params.to_csv(OUT / f"{CASE}_params.csv", index=False)

    # Update params.csv.tpl
    tpl = OUT / f"{CASE}_params.csv.tpl"
    lines = tpl.read_text(encoding="utf-8").splitlines()
    for r in all_ic:
        if not any(l.lower().startswith(r["name"].lower() + ",") for l in lines):
            lines.append(f"{r['name']},~ {r['name']} ~")
    tpl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Write design json inside run dir + update model_command
    run_design = OUT / "soil_n_design.json"
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    # Update bundle_path to absolute and add sha
    for season in design["seasons"]:
        bundle = ROOT / season["bundle_path"]
        manifest = bundle / "input_manifest.json"
        if manifest.is_file():
            season["bundle_manifest_sha256"] = _sha256(manifest)
    run_design.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{run_design.as_posix()}" '
        f'--param-csv {CASE}_params.csv --harvest-var CHPDT '
        f'--keep-nitrogen-outputs --prefix {CASE}'
    ]
    pst.control_data.noptmax = 4
    pst.pestpp_options["ies_num_reals"] = "100"
    pst.pestpp_options["rand_seed"] = "20260808"
    pst.write(str(OUT / f"{CASE}.pst"))

    # Verify
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    n_adj = int(pst2.npar_adj)
    ic_adj = len([n for n in pst2.parameter_data.index if str(n).lower().startswith("ic_") and pst2.parameter_data.at[n, "partrans"] != "fixed"])
    ic_fix = len([n for n in pst2.parameter_data.index if str(n).lower().startswith("ic_") and pst2.parameter_data.at[n, "partrans"] == "fixed"])
    print(f"\n[5/6] verify: npar={pst2.npar} npar_adj={n_adj} nobs={pst2.nobs}")
    print(f"  IC adjustable (L01-L03): {ic_adj}")
    print(f"  IC fixed (L04-L05): {ic_fix}")
    print(f"  genetic fixed: {n_frozen}")

    # Receipt
    receipt = {
        "run_id": CASE,
        "purpose": "Initial soil N inversion (SNH4+SNO3 per treatment per layer)",
        "seasons": ["25SP (XXQL2501, 10 treatments)", "26SP (XXQL2601, 12 treatments)"],
        "genetic_params": f"best member #{BEST_MEMBER} from {BATCH_B_CASE} (108 params, all fixed)",
        "ic_params_adjustable": len(ic_rows),
        "ic_params_fixed": len(ic_fixed_rows),
        "total_params": int(pst2.npar),
        "adjustable_params": n_adj,
        "n_observations": int(pst2.nobs),
        "n_reals": 100,
        "noptmax": 4,
        "custom_dssat": str(EXE.resolve()),
        "custom_spe": str(SPE.resolve()),
        "bound_rule": "L01-L03: pooled mean ± 2*SD (clip 0); L04-L05: fixed at FileX value",
        "bundles": {s["season_id"]: str(s["bundle"]) for s in SEASONS},
    }
    (OUT / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n[6/6] done: {OUT.name}")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
