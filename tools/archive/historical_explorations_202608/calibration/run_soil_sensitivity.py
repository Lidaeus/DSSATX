"""True water-response knob sensitivity: SLDR (drainage rate) and SDUL (field
capacity) for the eggplant four-corner design.

The SSKS sensitivity test (run_ssks_sensitivity.py) proved that DSSAT v4.8's
soil-water balance does not use saturated hydraulic conductivity (SSKS) —
0.23/1.0/2.0/-99 cm/h all produced byte-identical water/yield outputs.  The
parameters that actually control drainage and water storage in the v4.8
tipping-bucket balance are:

- ``SLDR``  — drainage rate coefficient on the SCOM line (default 0.27);
- ``SDUL``  — drained upper limit / field capacity per layer (0-100 cm);
- ``SLLL``  — lower limit of plant-extractable water.

This tool re-runs the deterministic best-member simulation (four-corner
treatments, 25SP + 26SP) under alternative SLDR / SDUL values, patching the
bundle SOIL.SOL copies exactly like the SSKS tool does (the pipeline feeds
the bundle's SOIL.SOL into the DSSAT run directory, which is the file DSSAT
actually reads — verified via the run's FILEIO dump).

Usage:
    python tools/calibration/run_soil_sensitivity.py \
        --scenarios "sldr_0.05,sldr_0.9,dul_minus005" [--param-csv ...]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.calibration.run_ssks_sensitivity import (
    SEASONS,
    OBS_POLICY,
    GROUP_POLICY,
    DEFAULT_PARAM_CSV,
    SOIL_ID,
    run,
    run_scenario,
    parse_harvest,
    parse_wspd,
)

# Column layout of the IBTM910017 block in the bundle SOIL.SOL (6-char fields):
#   @  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  ...
#   field0   f1    f2    f3    f4    f5    f6    f7
SLLL_COL, SDUL_COL, SSAT_COL = 12, 18, 24
# SCOM line:  SCOM SALB SLU1 SLDR SLRO SLNF SLPF  -> SLDR is field 3
SLDR_COL = 18


def _block_range(lines: list[str]) -> tuple[int, int]:
    start = next(i for i, l in enumerate(lines) if l.startswith("*") and SOIL_ID in l)
    data = []
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("*"):
            break
        if not lines[i].startswith("@") and lines[i].strip():
            data.append(i)
    return data[0], data[-1] + 1


def _fmt6(value: float) -> str:
    if value == -99:
        return "   -99"
    return f"{value:>6.2f}"


def patch_sldr(soil_path: Path, value: float) -> int:
    """Replace SLDR on the IBTM910017 SCOM data line (the row directly below
    the ``@ SCOM ... SLDR ...`` header; 6-char fixed-width fields)."""
    lines = soil_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith("*") and SOIL_ID in l)
    for i in range(start + 1, start + 6):
        if lines[i].lstrip().startswith("@") and "SLDR" in lines[i]:
            col = (lines[i].index("SLDR") // 6) * 6
            row = i + 1  # SCOM data row directly below the header
            old = lines[row][col:col + 6].strip()
            if old in ("", "-99", "0", "0."):
                raise ValueError(f"unexpected current SLDR value {old!r} in {soil_path}")
            lines[row] = lines[row][:col] + _fmt6(value) + lines[row][col + 6:]
            soil_path.write_text("".join(lines), encoding="utf-8")
            # Verify
            check = soil_path.read_text(encoding="utf-8").splitlines()
            got = check[row][col:col + 6].strip()
            if abs(float(got) - value) > 1e-9:
                raise ValueError(f"SLDR patch verification failed: {got}")
            return 1
    raise ValueError(f"SLDR header not found in {soil_path}")


def patch_sdul(soil_path: Path, delta: float) -> int:
    """Add ``delta`` to SDUL (field capacity) on all IBTM910017 layers where
    the current SDUL is positive (0-100 cm; deep layers stay untouched)."""
    lines = soil_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    lo, hi = _block_range(lines)
    patched = 0
    for i in range(lo, hi):
        field = lines[i][SDUL_COL:SDUL_COL + 6].strip()
        try:
            sdul = float(field)
        except ValueError:
            continue
        if sdul <= 0 or sdul > 0.9:
            continue
        new = round(sdul + delta, 4)
        if new < 0.05 or new > 0.95:
            raise ValueError(f"SDUL {sdul} + {delta} out of safe range")
        lines[i] = lines[i][:SDUL_COL] + f"{new:>6.4f}" + lines[i][SDUL_COL + 6:]
        patched += 1
    if patched == 0:
        raise ValueError(f"no SDUL layers patched in {soil_path}")
    soil_path.write_text("".join(lines), encoding="utf-8")
    return patched


PATCHERS = {
    "sldr": patch_sldr,
    "dul": patch_sdul,
}


def build_scenario(out_dir: Path, patch_name: str, value: float) -> Path:
    """Copy the two season bundles, apply the named soil patch, write design."""
    patcher = PATCHERS[patch_name]
    design_seasons = []
    for spec in SEASONS:
        src = (ROOT / spec["bundle_path"]).resolve()
        dst = out_dir / f"bundle_{spec['season_id']}"
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        n = patcher(dst / "SOIL.SOL", value)
        print(f"  [{spec['season_id']}] {patch_name} patch applied ({n} edits)")
        design_seasons.append(
            {
                "season_id": spec["season_id"],
                "experiment_code": spec["experiment_code"],
                "bundle_path": str(dst),
                "bundle_manifest_sha256": spec["manifest_sha256"],
                "role": "calibration",
                "treatments": spec["treatments"],
            }
        )
    design = {
        "schema_version": 1,
        "design_id": f"soil_sensitivity_{patch_name}_{value}_{datetime.now():%Y%m%d}",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "all",
        "observation_policy": OBS_POLICY,
        "group_policy": GROUP_POLICY,
        "seasons": design_seasons,
    }
    design_path = out_dir / "design.json"
    design_path.write_text(
        json.dumps(design, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return design_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenarios",
        default="sldr_0.05,sldr_0.9,dul_minus005",
        help="comma-separated scenario specs <patch>_<value> (sldr|dul)",
    )
    parser.add_argument("--param-csv", default=str(ROOT / DEFAULT_PARAM_CSV))
    parser.add_argument("--out-root", default=None)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    param_csv = Path(args.param_csv).resolve()
    if not param_csv.is_file():
        parser.error(f"--param-csv not found: {param_csv}")

    out_root = Path(args.out_root) if args.out_root else (
        ROOT / "workspace/runs" / f"soil_sensitivity_{datetime.now():%Y%m%d_%H%M%S}"
    )
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"out root: {out_root}")

    harvest_tables = []
    wspd_tables = []
    for spec in args.scenarios.split(","):
        patch_name, _, value_s = spec.partition("_")
        value = float(value_s.replace("minus", "-"))
        out_dir = out_root / f"scenario_{spec}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"=== scenario {spec} ===")
        design_path = build_scenario(out_dir, patch_name, value)
        if args.skip_run:
            continue
        run_scenario(out_dir, design_path, param_csv)
        harvest = parse_harvest(out_dir)
        harvest_tables.append(harvest.rename(spec))
        wspd = parse_wspd(out_dir)
        wspd["scenario"] = spec
        wspd_tables.append(wspd)

    if not harvest_tables:
        return 0

    summary = pd.concat(harvest_tables, axis=1)
    summary.insert(0, "season_treatment", summary.index.map(
        lambda tn: "25SP" if tn in (2, 5, 10, 13) else "26SP"
    ))
    summary.to_csv(out_root / "final_chpdts_by_scenario.csv", encoding="utf-8-sig")
    print("\n=== final cumulative dry harvest (CHPDTS, kg/ha) by scenario ===")
    print(summary.to_string())

    mapping = {
        (25, "W3N3"): 2, (25, "W3N0"): 5, (25, "W1N3"): 10, (25, "W1N0"): 13,
        (26, "W3N3"): 1, (26, "W3N0"): 9, (26, "W1N3"): 3, (26, "W1N0"): 12,
    }
    rows = []
    for scen in summary.columns[1:]:
        for season_key in (25, 26):
            w3n3 = summary.loc[mapping[(season_key, "W3N3")], scen]
            w1n3 = summary.loc[mapping[(season_key, "W1N3")], scen]
            w3n0 = summary.loc[mapping[(season_key, "W3N0")], scen]
            w1n0 = summary.loc[mapping[(season_key, "W1N0")], scen]
            rows.append({
                "scenario": scen,
                "season": f"{season_key}SP",
                "dW_N3 (W3N3-W1N3)": round(w3n3 - w1n3, 1),
                "dW_N0 (W3N0-W1N0)": round(w3n0 - w1n0, 1),
                "W1/W3 ratio N3": round(w1n3 / w3n3, 4),
                "W1/W3 ratio N0": round(w1n0 / w3n0, 4),
            })
    gap = pd.DataFrame(rows)
    gap.to_csv(out_root / "water_gap_by_scenario.csv", encoding="utf-8-sig")
    print("\n=== W1 vs W3 yield gap by scenario ===")
    print(gap.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
