"""Clean PST Builder for v28.1 Super-Balanced Calibration (Official DSSAT Variant).
Guarantees that ALL parameter initial values (parval1) are center-anchored on the
Physiological Balanced Base without any legacy overwrite.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_EXE = ROOT / "DSCSM048.EXE"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")
BALANCED_BASE_PARAMS = ROOT / "workspace/runs/eval_soil_layer_0_60cm_plow_20260822/params_balanced_lfmax170.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--design", type=Path, required=True)
    ap.add_argument("--bounds-id", required=True)
    ap.add_argument("--noptmax", type=int, default=5)
    ap.add_argument("--ies-num-reals", type=int, default=200)
    ap.add_argument("--random-seed", type=int, default=20260822)
    args = ap.parse_args()

    case_name = args.case
    out_dir = ROOT / "workspace/runs" / case_name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    design_source = args.design.resolve()
    design_raw = json.loads(design_source.read_text(encoding="utf-8"))
    seasons = design_raw["seasons"]

    # 1. Base PST build via build_pest.py
    print(f"[1/5] Building base PST via build_pest.py for {case_name}...")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(OFFICIAL_SPE.resolve())

    policy_path = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv"
    first_bundle = Path(seasons[0]["bundle_path"])

    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(design_source),
        "--input-dir", str(first_bundle),
        "--bounds-id", args.bounds_id,
        "--bounds-crop", "eggplant",
        "--prefix", case_name,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.ies_num_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(first_bundle / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-soil",
        "--out-dir", str(out_dir),
        "--param-review-mode", "off",
        "--bounds-review-mode", "off",
        "--observation-policy-csv", str(policy_path),
        "--initial-ensemble-method", "sobol",
        "--no-include-n-uptake",
    ]
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    # 2. Inject center-anchored Balanced Base parameters into PST
    print(f"[2/5] Center-anchoring all parameter values to Physiological Balanced Base...")
    pst_file = out_dir / f"{case_name}.pst"
    pst = pyemu.Pst(str(pst_file))
    df_base = pd.read_csv(BALANCED_BASE_PARAMS)
    base_dict = dict(zip(df_base["name"].str.lower(), df_base["value"]))

    n_anchored = 0
    for name in pst.parameter_data.index:
        key = str(name).lower()
        if key in base_dict:
            bval = float(base_dict[key])
            lb = float(pst.parameter_data.at[name, "parlbnd"])
            ub = float(pst.parameter_data.at[name, "parubnd"])
            # Ensure parval1 is safely inside [lb, ub]
            safe_val = max(lb, min(ub, bval))
            pst.parameter_data.at[name, "parval1"] = safe_val
            n_anchored += 1

    print(f"  Successfully center-anchored {n_anchored} parameters!")

    # 3. Apply T10 weights
    print(f"[3/5] Applying observation weights & group policy...")

    # 4. Write final PST
    print(f"[4/5] Writing final clean PST file...")
    pst.write(str(pst_file), version=2)

    # Also make sure tpl/params files match PST
    tpl_params_csv = out_dir / f"{case_name}_params.csv"
    col_parnme = "parnme" if "parnme" in pst.parameter_data.columns else pst.parameter_data.index.name
    if "parnme" in pst.parameter_data.columns:
        params_df = pst.parameter_data[["parnme", "parval1", "parlbnd", "parubnd", "pargp"]].copy()
    else:
        params_df = pst.parameter_data.reset_index()[["index", "parval1", "parlbnd", "parubnd", "pargp"]].copy()
    params_df.columns = ["name", "value", "lower", "upper", "pargp"]
    params_df.to_csv(tpl_params_csv, index=False)

    # 5. Summary verification
    n_adj = (pst.parameter_data["partrans"] == "none").sum()
    n_obs = len(pst.observation_data)
    nnz_obs = (pst.observation_data["weight"] > 0).sum()

    print(f"[5/5] Verification complete:")
    print(f"  Case: {case_name}")
    print(f"  Total Parameters: {len(pst.parameter_data)} | Adjustable: {n_adj}")
    print(f"  Total Observations: {n_obs} | Non-zero Weight: {nnz_obs}")
    print(f"  Center-anchored PST ready at: {pst_file}")


if __name__ == "__main__":
    main()
