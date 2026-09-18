"""Build a3-DSSAT joint calibration with negative NUPCMN allowed (20260810).

Based on the a3 joint calibration (e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810)
with a single change: the NUPCMN lower bound is widened from 0.0 to -2.0 so the
A3 thresholded uptake threshold C*=max(C-NUPCMN,0) can go negative (which
raises effective uptake at low soil-N concentrations).  Everything else —
exe/SPE, parameter set, bounds, objective, bundles, scale — is unchanged.

The A3 response is numerically safe for negative NUPCMN: C*=C+|NUPCMN|>0 and
F=C*/(NUPK50+C*) has no singularity.  PHYSICAL_BOUNDS floor was widened to
-2.0 in src/common/param_registry.py.

Usage:
    python tools/calibration/build_a3_negupcmn_20260810.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810_negupcmn"
BASE_CASE = "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810"
BASE_RUN = ROOT / f"workspace/runs/{BASE_CASE}"

NUPCMN_LOWER = -2.0
NUPCMN_UPPER = 2.0


def main():
    OUT = ROOT / "workspace/runs" / CASE
    if OUT.exists():
        raise FileExistsError(OUT)
    if not BASE_RUN.is_dir():
        raise FileNotFoundError(BASE_RUN)

    print("[1/4] copying a3 joint calibration as base")
    shutil.copytree(BASE_RUN, OUT)
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
        if p.is_file() and BASE_CASE in p.name:
            p.rename(OUT / p.name.replace(BASE_CASE, CASE))

    print("[2/4] widening NUPCMN bounds")
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    r = pst.parameter_data.loc["nupcmn"]
    print(f"  nupcmn: init={r.parval1} [{r.parlbnd},{r.parubnd}] -> [{NUPCMN_LOWER},{NUPCMN_UPPER}]")
    pst.parameter_data.at["nupcmn", "parlbnd"] = NUPCMN_LOWER
    pst.parameter_data.at["nupcmn", "parubnd"] = NUPCMN_UPPER

    # Fix bounds issues (same policy as previous builds)
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

    pst.control_data.noptmax = 5
    pst.pestpp_options["ies_num_reals"] = "200"
    pst.pestpp_options["rand_seed"] = "2026081001"
    pst.write(str(OUT / f"{CASE}.pst"))

    # PST internal references still point at base case names; rewrite them
    pst_path = OUT / f"{CASE}.pst"
    text = pst_path.read_text(encoding="utf-8")
    n = text.count(BASE_CASE)
    pst_path.write_text(text.replace(BASE_CASE, CASE), encoding="utf-8")
    print(f"  rewrote {n} internal base case references -> {CASE}")

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

    # Verify
    pst2 = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    r2 = pst2.parameter_data.loc["nupcmn"]
    print(f"\n[4/4] verify: npar={pst2.npar} npar_adj={pst2.npar_adj} nobs={pst2.nobs}")
    print(f"  nupcmn final bounds: [{r2.parlbnd},{r2.parubnd}] init={r2.parval1}")

    receipt = {
        "run_id": CASE,
        "base": "a3 joint calibration (genetic + soilN + soil physical)",
        "change": "NUPCMN lower bound widened 0.0 -> -2.0 (A3 thresholded uptake C*=max(C-NUPCMN,0) may go negative)",
        "physical_bounds_note": "PHYSICAL_BOUNDS floor for NUPCMN widened to -2.0 in src/common/param_registry.py (no singularity in A3 response)",
        "n_parameters": int(pst2.npar),
        "n_adjustable": int(pst2.npar_adj),
        "n_reals": 200,
        "noptmax": 5,
    }
    (OUT / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print("\ndone — run smoke test, then launch with launch_a3_negupcmn_20260810.py")


if __name__ == "__main__":
    main()
