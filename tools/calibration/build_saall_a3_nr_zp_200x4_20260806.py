"""Build the A3 NR-ZP calibration using the complete Morris active domain."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_saall_a3_nr_zp_200x4_20260806"
OUT = ROOT / "workspace/runs" / CASE
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_rawdiff_terminal_nresp01_soil02_saactive_a3_nr_zp_20260806.json"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
BOUNDS_ID = "eggplant_two_spring_organ_n_v1_20260803"
BOUNDS_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{BOUNDS_ID}.csv"
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
EXE = ROOT / "windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe"
SPE = ROOT / "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE"
SOURCE_CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_6treat_150x4_20260805_a3_nr_zp_0805"
SOURCE = ROOT / "workspace/runs" / SOURCE_CASE


def main() -> None:
    if OUT.exists():
        raise FileExistsError(OUT)
    bounds = pd.read_csv(BOUNDS_CSV, encoding="utf-8-sig")
    active = bounds.loc[bounds.status.astype(str).str.lower().eq("active")].copy()
    lookup = {str(r["name"]).strip().lower(): r for _, r in bounds.iterrows()}
    expected_active = set(active.name.astype(str).str.strip().str.lower())
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(SPE.resolve())
    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(BUNDLE), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", CASE, "--noptmax", "4", "--ies-num-reals", "200",
        "--random-seed", "20260806", "--bad-phi-sigma", "1e300",
        "--batch", str(BUNDLE / "DSSBatch.v48"), "--harvest-var", "CHPDT",
        "--include-n-uptake", "--include-soil", "--out-dir", str(OUT),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY), "--initial-ensemble-method", "sobol",
    ]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)

    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    source_pst = pyemu.Pst(str(SOURCE / f"{SOURCE_CASE}.pst"))
    pst_names = {str(n).lower(): n for n in pst.parameter_data.index}
    missing = expected_active - set(pst_names)
    if missing:
        raise RuntimeError(f"complete Morris active parameters absent from generated PST: {sorted(missing)}")
    for key, name in pst_names.items():
        row = lookup.get(key)
        if row is None:
            pst.parameter_data.at[name, "partrans"] = "fixed"
            pst.parameter_data.at[name, "parlbnd"] = pst.parameter_data.at[name, "parval1"]
            pst.parameter_data.at[name, "parubnd"] = pst.parameter_data.at[name, "parval1"]
            continue
        pst.parameter_data.at[name, "parval1"] = float(row["init"])
        pst.parameter_data.at[name, "parlbnd"] = float(row["lower"])
        pst.parameter_data.at[name, "parubnd"] = float(row["upper"])
        pst.parameter_data.at[name, "partrans"] = (
            "none" if str(row["status"]).strip().lower() == "active" else "fixed"
        )

    custom_names = {"nupk50", "nupcmn"}
    custom = source_pst.parameter_data.loc[
        source_pst.parameter_data.index.astype(str).str.lower().isin(custom_names)
    ].copy()
    if set(custom.index.astype(str).str.lower()) != custom_names:
        raise RuntimeError(f"A3 NR-ZP custom parameters missing: {custom_names}")
    if len(pst.parameter_data.index.astype(str).str.lower().intersection(custom.index.astype(str).str.lower())):
        raise RuntimeError("custom parameter collision")
    pst.parameter_data = pd.concat([pst.parameter_data, custom], axis=0)

    tpl = OUT / f"{CASE}_params.csv.tpl"
    lines = tpl.read_text(encoding="utf-8").splitlines()
    for name in ("NUPK50", "NUPCMN"):
        if not any(line.lower().startswith(name.lower() + ",") for line in lines):
            lines.append(f"{name},~ {name} ~")
    tpl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    params = pd.read_csv(OUT / f"{CASE}_params.csv")
    for key, row in lookup.items():
        mask = params.name.astype(str).str.lower().eq(key)
        if mask.any():
            params.loc[mask, "value"] = float(row["init"])
    source_params = pd.read_csv(SOURCE / f"{SOURCE_CASE}_params.csv")
    for name in ("NUPK50", "NUPCMN"):
        row = source_params.loc[source_params.name.astype(str).str.upper().eq(name)]
        if len(row) != 1:
            raise RuntimeError(f"source value missing for {name}")
        params = pd.concat([params, row[["name", "value"]]], ignore_index=True)
    params.to_csv(OUT / f"{CASE}_params.csv", index=False)

    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    design.update({"design_id": CASE, "custom_dssat_executable": str(EXE.resolve()), "custom_spe": str(SPE.resolve())})
    design["formal"] = {"n_reals": 200, "noptmax": 4, "initial_ensemble_method": "sobol"}
    design_path = OUT / "six_treatment_design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{design_path.as_posix()}" --param-csv {CASE}_params.csv '
        f"--harvest-var CHPDT --keep-nitrogen-outputs --prefix {CASE}"
    ]
    pst.control_data.noptmax = 4
    pst.pestpp_options["ies_num_reals"] = "200"
    pst.pestpp_options["rand_seed"] = "20260806"
    pst.write(str(OUT / f"{CASE}.pst"))

    receipt = {
        "run_id": CASE,
        "objective_contract": "raw_scale_difference_plus_terminal_20260805",
        "bounds_id": BOUNDS_ID,
        "morris_active_count": int(len(expected_active)),
        "custom_parameters": {
            name.upper(): {
                "init": float(custom.loc[custom.index.astype(str).str.upper() == name.upper(), "parval1"].iloc[0]),
                "lower": float(custom.loc[custom.index.astype(str).str.upper() == name.upper(), "parlbnd"].iloc[0]),
                "upper": float(custom.loc[custom.index.astype(str).str.upper() == name.upper(), "parubnd"].iloc[0]),
            }
            for name in custom_names
        },
        "n_parameters": int(pst.npar),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations": int(pst.nobs),
        "n_observations_active": int((pst.observation_data.weight > 0).sum()),
        "n_reals": 200,
        "noptmax": 4,
        "custom_executable": str(EXE.resolve()),
        "custom_spe": str(SPE.resolve()),
        "status": "built",
    }
    (OUT / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
