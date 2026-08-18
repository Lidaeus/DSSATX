"""SSKS sensitivity test for the eggplant four-corner design.

Hypothesis check: the current soil profile fixes SSKS = 0.23 cm/h for the
0-100 cm layers, which may slow drainage so much that the low-water (W1)
treatments never actually dry out — damping the simulated W1 vs W3 yield
gap.  This tool re-runs the deterministic best-member simulation (four-corner
treatments, 25SP + 26SP) under alternative SSKS values (-99 auto-estimate,
1.0, 2.0 cm/h) while keeping every other input byte-identical, then reports
the final cumulative dry harvest and water-stress (WSPD) statistics per
treatment so the W1/W3 response can be compared across scenarios.

Usage:
    python tools/calibration/run_ssks_sensitivity.py \
        --ssks-values "0.23,-99,1.0,2.0" [--param-csv ...] [--out-root ...]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEASONS = [
    {
        "season_id": "25SP",
        "experiment_code": "XXQL2501",
        "bundle_path": (
            "data/user/experiments/"
            "xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"
        ),
        "manifest_sha256": (
            "f0c59a5e48127b62d77da13f1e5db154ac3b13f03b496b3586ee7514192e39fe"
        ),
        "treatments": [2, 5, 10, 13],
    },
    {
        "season_id": "26SP",
        "experiment_code": "XXQL2601",
        "bundle_path": (
            "data/user/experiments/"
            "xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"
        ),
        "manifest_sha256": (
            "365e0afc8e33be2ef6413a5420ec905211f7deb276f852f97723f4ce3dd1d24a"
        ),
        "treatments": [1, 3, 9, 12],
    },
]

OBS_POLICY = "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_nochtd_v1.csv"
GROUP_POLICY = "configs/runs/t10_n_response_group_policy_harvestdry250_v2.csv"
DEFAULT_PARAM_CSV = (
    "workspace/runs/e02_wnstress_fourcorner_formal_200x5_20260801_080700/"
    "best_member_long_params.csv"
)
SOIL_ID = "IBTM910017"
BASELINE_SSKS = 0.23  # value currently fixed in the 0-100 cm layers


def run(command: list[str], cwd: Path) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def patch_soil_ssks(soil_path: Path, ssks_value: float) -> int:
    """Replace SSKS in the IBTM910017 block where it currently equals 0.23.

    DSSAT SOIL.SOL fields are 6-char fixed-width.  Returns the number of
    layers patched.
    """
    lines = soil_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    block_start = next(
        i for i, l in enumerate(lines) if l.startswith("*") and SOIL_ID in l
    )
    header_idx = None
    data_start = None
    for i in range(block_start + 1, len(lines)):
        line = lines[i]
        if line.startswith("*"):
            break
        if line.lstrip().startswith("@") and "SSKS" in line:
            header_idx = i
            data_start = i + 1
            break
    if header_idx is None:
        raise ValueError(f"{SOIL_ID} header with SSKS not found in {soil_path}")
    # DSSAT SOIL.SOL headers are 6-char fixed-width fields; ``index("SSKS")``
    # points at the 'S' inside the "  SSKS" field, so align back to the field
    # start (DSSAT reads data rows on 6-char boundaries).
    col = (lines[header_idx].index("SSKS") // 6) * 6
    original_values: list[float] = []
    patched = 0
    for i in range(data_start, len(lines)):
        line = lines[i]
        if line.startswith("*") or not line.strip():
            break
        field = line[col:col + 6].strip()
        try:
            current = float(field)
        except ValueError:
            continue
        original_values.append(current)
        if abs(current - BASELINE_SSKS) > 1e-9:
            continue
        lines[i] = line[:col] + f"{ssks_value:>6.2f}" + line[col + 6:]
        if ssks_value == -99:
            lines[i] = line[:col] + "   -99" + line[col + 6:]
        patched += 1
    if patched == 0:
        raise ValueError(f"no layers with SSKS={BASELINE_SSKS} found in {soil_path}")
    soil_path.write_text("".join(lines), encoding="utf-8")
    # Verify the patch landed at the true 6-char field boundary (stop at the
    # next profile block — the file contains many soils after IBTM910017).
    verify = soil_path.read_text(encoding="utf-8", errors="replace").splitlines()
    values = []
    for v in verify[data_start:]:
        if v.startswith("*") or not v.strip():
            break
        if "@" in v:
            continue
        values.append(float(v[col:col + 6].strip()))
    expected = [
        ssks_value if abs(orig - BASELINE_SSKS) < 1e-9 else orig
        for orig in original_values
    ]
    if values != expected:
        raise ValueError(
            f"SSKS patch verification failed for {soil_path}: "
            f"expected {expected}, got {values}"
        )
    return patched


def build_scenario(
    out_dir: Path, ssks_value: float, scenario_label: str
) -> Path:
    """Copy the two season bundles, patch SOIL.SOL SSKS, write the design."""
    design_seasons = []
    for spec in SEASONS:
        src = (ROOT / spec["bundle_path"]).resolve()
        dst = out_dir / f"bundle_{spec['season_id']}"
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        n = patch_soil_ssks(dst / "SOIL.SOL", ssks_value)
        print(f"  [{spec['season_id']}] patched {n} layers -> SSKS={ssks_value}")
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
        "design_id": f"ssks_sensitivity_{scenario_label}_{datetime.now():%Y%m%d}",
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


def parse_harvest(out_dir: Path) -> pd.DataFrame:
    """Parse merged PestHarvest.OUT -> final cumulative dry harvest per TN."""
    path = out_dir / "PestHarvest.OUT"
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^RUN\s+\d+\s+TN\s+(\d+)\s+HNO\s+(\d+).*?@CHPDTS@\s+([\d.eE+-]+)", line)
        if not m:
            continue
        tn, hno, chpdts = int(m.group(1)), int(m.group(2)), float(m.group(3))
        rows.append({"treatment": tn, "hno": hno, "chpdts": chpdts})
    if not rows:
        raise ValueError(f"no harvest rows parsed from {path}")
    df = pd.DataFrame(rows)
    final = df.loc[df.groupby("treatment")["hno"].idxmax()].set_index("treatment")["chpdts"]
    return final


def parse_wspd(out_dir: Path) -> pd.DataFrame:
    """Parse PlantGro.OUT water stress (WSPD) per treatment from season dirs."""
    recs = []
    for spec in SEASONS:
        path = out_dir / "_seasons" / spec["season_id"] / "PlantGro.OUT"
        if not path.is_file():
            continue
        block_tn = None
        header = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("*RUN"):
                m = re.search(r"XXQL\d+\s+(\d+)\s*$", line)
                block_tn = int(m.group(1)) if m else None
                header = None
                continue
            if block_tn is None:
                continue
            if line.startswith("@YEAR") or line.startswith("@  YEAR"):
                header = line.split()
                continue
            if header and line.strip() and not line.startswith(("!", "$", "*")):
                tokens = line.split()
                if len(tokens) != len(header):
                    continue
                row = dict(zip(header, tokens))
                if "WSPD" in row:
                    try:
                        wspd = float(row["WSPD"])
                    except ValueError:
                        continue
                    recs.append({"season": spec["season_id"], "treatment": block_tn, "wspd": wspd})
    return pd.DataFrame(recs)


def run_scenario(out_dir: Path, design_path: Path, param_csv: Path) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path.resolve()),
        "--param-csv", str(param_csv),
        "--harvest-var", "CHPDT",
        "--prefix", f"ssks_{design_path.stem}",
    ]
    run(cmd, cwd=out_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ssks-values", default="0.23,-99,1.0,2.0",
        help="comma-separated SSKS values to test (default 0.23,-99,1.0,2.0)",
    )
    parser.add_argument("--param-csv", default=str(ROOT / DEFAULT_PARAM_CSV))
    parser.add_argument("--out-root", default=None)
    parser.add_argument("--skip-run", action="store_true", help="only build scenarios")
    args = parser.parse_args()

    param_csv = Path(args.param_csv).resolve()
    if not param_csv.is_file():
        parser.error(f"--param-csv not found: {param_csv}")
    values = [v.strip() for v in args.ssks_values.split(",")]
    labels = ["auto" if v == "-99" else v for v in values]

    out_root = Path(args.out_root) if args.out_root else (
        ROOT / "workspace/runs" / f"ssks_sensitivity_{datetime.now():%Y%m%d_%H%M%S}"
    )
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"out root: {out_root}")

    harvest_tables = []
    wspd_tables = []
    for value, label in zip(values, labels):
        out_dir = out_root / f"scenario_ssks_{label}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"=== scenario SSKS={value} ({label}) ===")
        design_path = build_scenario(out_dir, float(value), label)
        if not args.skip_run:
            run_scenario(out_dir, design_path, param_csv)
            harvest = parse_harvest(out_dir)
            harvest.name = "final_chpdts"
            harvest_tables.append(harvest.rename(f"ssks_{label}"))
            wspd = parse_wspd(out_dir)
            wspd["ssks"] = label
            wspd_tables.append(wspd)
        else:
            print("  (--skip-run: build only)")

    if not harvest_tables:
        return 0

    summary = pd.concat(harvest_tables, axis=1)
    summary.insert(0, "season_treatment", summary.index.map(
        lambda tn: "25SP" if tn in (2, 5, 10, 13) else "26SP"
    ))
    summary.to_csv(out_root / "final_chpdts_by_scenario.csv", encoding="utf-8-sig")
    print("\n=== final cumulative dry harvest (CHPDTS, t/ha) by scenario ===")
    print(summary.to_string())

    if wspd_tables:
        wspd_all = pd.concat(wspd_tables, ignore_index=True)
        wspd_stats = (
            wspd_all.groupby(["ssks", "season", "treatment"])["wspd"]
            .agg(mean="mean", min="min", stress_days=lambda s: (s < 0.99).sum())
            .reset_index()
        )
        wspd_stats.to_csv(out_root / "wspd_by_scenario.csv", encoding="utf-8-sig")
        print("\n=== WSPD (water stress factor, 1=no stress) by scenario ===")
        print(wspd_stats.to_string(index=False))

    # W1 vs W3 gap within each N level, per season and scenario
    mapping = {
        (25, "W3N3"): 2, (25, "W3N0"): 5, (25, "W1N3"): 10, (25, "W1N0"): 13,
        (26, "W3N3"): 1, (26, "W3N0"): 9, (26, "W1N3"): 3, (26, "W1N0"): 12,
    }
    rows = []
    for label in labels:
        for season_key in (25, 26):
            w3n3 = summary.loc[mapping[(season_key, "W3N3")], f"ssks_{label}"]
            w1n3 = summary.loc[mapping[(season_key, "W1N3")], f"ssks_{label}"]
            w3n0 = summary.loc[mapping[(season_key, "W3N0")], f"ssks_{label}"]
            w1n0 = summary.loc[mapping[(season_key, "W1N0")], f"ssks_{label}"]
            rows.append({
                "scenario": f"ssks_{label}",
                "season": f"{season_key}SP",
                "dW_N3 (W3N3-W1N3)": w3n3 - w1n3,
                "dW_N0 (W3N0-W1N0)": w3n0 - w1n0,
                "W1/W3 ratio N3": w1n3 / w3n3,
                "W1/W3 ratio N0": w1n0 / w3n0,
            })
    gap = pd.DataFrame(rows)
    gap.to_csv(out_root / "water_gap_by_scenario.csv", encoding="utf-8-sig")
    print("\n=== W1 vs W3 yield gap by scenario ===")
    print(gap.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
