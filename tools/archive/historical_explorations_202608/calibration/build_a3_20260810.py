"""Build a3-DSSAT joint calibration (20260810).

Based on the v2 joint calibration
(e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808) with:
  - DSSAT version swapped from the custom a3_nr_zp build to the A3 build
    (windows/windows_a3_20260805/dscsm048_a3.exe + its Genotype/TMGRO048.SPE).
    A3 implements thresholded soil-N uptake C*=max(C-NUPCMN,0),
    F=C*/(NUPK50+C*); NREXP/NRMIN stay in the SPE but the continuous NSTRES
    branch is not enabled in this build (per package README).
  - Custom genetic params keep the a3 SPE's set (NREXP, NRMIN, NUPK50, NUPCMN
    — same names as the a3_nr_zp config, so the PST parameter set is unchanged).
  - Everything else unchanged: 200 reals x 5 iters, rawdiff_terminal objective,
    25SP+26SP actual_trial bundles (22 treatments), IC params, soil physical
    params (SBDM/SLPF/SSKS/SLCL/SLSI), observation/group policies.

Usage:
    python tools/calibration/build_a3_20260810.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810"
V2_CASE = "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808"
V2_RUN = ROOT / f"workspace/runs/{V2_CASE}"

A3_EXE = ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe"
A3_SPE = ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"


def main():
    OUT = ROOT / "workspace/runs" / CASE
    if OUT.exists():
        raise FileExistsError(OUT)
    if not V2_RUN.is_dir():
        raise FileNotFoundError(V2_RUN)
    if not A3_EXE.is_file():
        raise FileNotFoundError(A3_EXE)
    if not A3_SPE.is_file():
        raise FileNotFoundError(A3_SPE)

    print("[1/4] copying v2 joint calibration as base")
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

    print("[2/4] loading PST (param set unchanged — a3 SPE keeps the same custom params)")
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    for n in ["nrexp", "nrmin", "nupk50", "nupcmn"]:
        if n in pst.parameter_data.index:
            r = pst.parameter_data.loc[n]
            print(f"  kept {n}: init={r.parval1} [{r.parlbnd},{r.parubnd}]")

    # Fix bounds issues (same policy as v2 build)
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
    pst.pestpp_options["rand_seed"] = "20260810"
    pst.write(str(OUT / f"{CASE}.pst"))

    # PST internal references still point at v2 case names; rewrite them
    pst_path = OUT / f"{CASE}.pst"
    text = pst_path.read_text(encoding="utf-8")
    n = text.count(V2_CASE)
    pst_path.write_text(text.replace(V2_CASE, CASE), encoding="utf-8")
    print(f"  rewrote {n} internal v2 case references -> {CASE}")

    manifest = OUT / "run_manifest.yaml"
    if manifest.is_file():
        lines = [l for l in manifest.read_text(encoding="utf-8").splitlines()
                 if not l.startswith("stage_representative_")]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    oe_json = OUT / f"{CASE}.observation_ensemble.json"
    if oe_json.is_file():
        meta = json.loads(oe_json.read_text(encoding="utf-8"))
        meta["run_id"] = CASE
        oe_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Update design scope text (a3 config instead of a3_nr_zp)
    design = OUT / "joint_design.json"
    if design.is_file():
        d = json.loads(design.read_text(encoding="utf-8"))
        scope = d.get("shared_parameter_scope", "")
        if "a3_nr_zp" in scope:
            d["shared_parameter_scope"] = scope.replace(
                "a3_nr_zp config", "a3_20260805 config (thresholded N uptake; NREXP/NRMIN inert)")
            design.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Verify
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    print(f"\n[4/4] verify: npar={pst2.npar} npar_adj={pst2.npar_adj} nobs={pst2.nobs}")
    print(f"  custom params present: {[n for n in ['nrexp','nrmin','nupk50','nupcmn'] if n in pst2.parameter_data.index]}")
    print(f"  a3 exe: {A3_EXE} ({A3_EXE.stat().st_size} bytes)")
    print(f"  a3 SPE: {A3_SPE}")

    receipt = {
        "run_id": CASE,
        "base": "v2 joint calibration (genetic + soilN + soil physical)",
        "dssat_version": "A3 build (windows/windows_a3_20260805/dscsm048_a3.exe)",
        "species_file": str(A3_SPE),
        "custom_params": ["nrexp", "nrmin", "nupk50", "nupcmn"],
        "custom_params_note": "same names as a3_nr_zp; in the A3 build NREXP/NRMIN remain in SPE but the continuous NSTRES branch is not enabled",
        "n_parameters": int(pst2.npar),
        "n_adjustable": int(pst2.npar_adj),
        "n_reals": 200,
        "noptmax": 5,
        "note": "a3 exe/SPE swapped in at launch; parameter set identical to v2",
    }
    (OUT / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print("\ndone — run smoke test, then launch with launch_a3_20260810.py")


if __name__ == "__main__":
    main()
