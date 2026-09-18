"""Update SOIL_SLPF fixed value 0.9 -> 0.92 everywhere (20260812).

User approved changing the fixed soil fertility factor SLPF to 0.92.  This
script updates:
  1. soil_physical_Fix.csv.xlsx (the authoritative fix file)
  2. both actual_trial bundles' SOIL.SOL IBTM910017 SCOM row (6-char column)
  3. both fixedsoil run PSTs (soil_slpf fixed value) + params.csv
so the re-run of the evaluation exports 0.92 for the deterministic replay.

Usage:
    python tools/calibration/update_slpf_092_20260812.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
FIX_XLSX = ROOT / "figture/soil_param_export_three_20260810/soil_physical_Fix.csv.xlsx"
NEW_SLPF = 0.92

BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
]
RUNS = [
    ROOT / "workspace/runs/e02_v2_fixedsoil_joint_a3_25sp26sp_200x5_20260811",
    ROOT / "workspace/runs/e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260811",
]
SCOM_FIELDS = ["SCOM", "SALB", "SLU1", "SLDR", "SLRO", "SLNF", "SLPF",
               "SMHB", "SMPX", "SMKE"]


def _fmt_slpf(v: float, orig: str) -> str:
    """Format into the 6-char SCOM column, keeping '.xx' style."""
    if abs(v) < 1 and orig.startswith("."):
        body = f"{abs(v):.3f}".split(".", 1)[1].rstrip("0")
        tok = "." + body
        if len(tok) <= 6:
            return tok.rjust(6)
    for dec in range(6, -1, -1):
        tok = f"{v:.{dec}f}"
        if len(tok) <= 6:
            return tok.rjust(6)
    return f"{v:.5g}"[:6].rjust(6)


def update_bundle_soil(bundle: Path) -> bool:
    sol = bundle / "SOIL.SOL"
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_prof = False
    for idx, line in enumerate(lines):
        if line.startswith("*IBTM910017"):
            in_prof = True
            continue
        if not in_prof:
            continue
        if line.startswith("*") and not line.startswith("*IBTM910017"):
            break
        if line.lstrip().startswith("@ SCOM"):
            slpf_idx = SCOM_FIELDS.index("SLPF")
            data = lines[idx + 1]
            start = slpf_idx * 6
            orig = data[start : start + 6].strip()
            new_tok = _fmt_slpf(NEW_SLPF, orig)
            cols = list(data)
            cols[start : start + 6] = list(new_tok)
            lines[idx + 1] = "".join(cols).rstrip() + "\n"
            sol.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"  {sol}: SLPF {orig} -> {new_tok.strip()}")
            return True
    return False


def update_run(run: Path) -> None:
    case = run.name
    pst = pyemu.Pst(str(run / f"{case}.pst"))
    if "soil_slpf" in pst.parameter_data.index:
        pst.parameter_data.at["soil_slpf", "parval1"] = NEW_SLPF
        pst.parameter_data.at["soil_slpf", "parlbnd"] = NEW_SLPF
        pst.parameter_data.at["soil_slpf", "parubnd"] = NEW_SLPF
        pst.write(str(run / f"{case}.pst"))
        print(f"  {case}: PST soil_slpf -> {NEW_SLPF}")
    params_path = run / f"{case}_params.csv"
    if params_path.is_file():
        params = pd.read_csv(params_path)
        mask = params["name"].astype(str).str.upper() == "SOIL_SLPF"
        if mask.any():
            params.loc[mask, "value"] = NEW_SLPF
            params.to_csv(params_path, index=False)
            print(f"  {case}: params.csv SOIL_SLPF -> {NEW_SLPF}")


def main() -> int:
    print(f"[1/3] fix file SOIL_SLPF -> {NEW_SLPF}")
    df = pd.read_excel(FIX_XLSX)
    mask = df["param"].astype(str) == "SOIL_SLPF"
    if mask.any():
        df.loc[mask, "Fix"] = NEW_SLPF
        df.to_excel(FIX_XLSX, index=False)
        print(f"  {FIX_XLSX.name}: SOIL_SLPF = {NEW_SLPF}")

    print("[2/3] bundle SOIL.SOL SCOM SLPF")
    for b in BUNDLES:
        update_bundle_soil(b)

    print("[3/3] run PST + params.csv")
    for r in RUNS:
        update_run(r)

    print("\ndone — re-run evaluate_fixedsoil_{a3,official}_20260812.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
