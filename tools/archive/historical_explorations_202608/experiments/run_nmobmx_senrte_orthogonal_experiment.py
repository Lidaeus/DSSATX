#!/usr/bin/env python3
"""Orthogonal sensitivity experiment for NMOBMX and SENRTE on nitrogen response.

This script executes a 3x3 factorial forward simulation matrix:
  - NMOBMX in [0.09, 0.15, 0.22]
  - SENRTE in [1.0, 2.0, 3.0]
across 25SP and 26SP factorial water x nitrogen treatments (W3/W1 x N3/N2/N1/N0).

It uses the latest formal champion parameter set (best member 41 from
e02_formal_final_champion_200x6_20260829) as the deterministic baseline.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = ROOT / "workspace/runs/e02_formal_final_champion_200x6_20260829/best_member_41_two_season_deterministic_20260829"
BASE_PARAMS = BASE_DIR / "best_member_41_params.csv"
BASE_DESIGN = BASE_DIR / "design.json"
OUT_DIR = ROOT / "workspace/diagnostics/nmobmx_senrte_orthogonal_20260830"

NMOBMX_LEVELS = [0.09, 0.15, 0.22]
SENRTE_LEVELS = [1.0, 2.0, 3.0]

SEASONS_INFO = {
    "25SP": {
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "n_map": {2: "N3", 3: "N2", 4: "N1", 5: "N0", 10: "N3", 11: "N2", 12: "N1", 13: "N0"},
        "w_map": {2: "W3", 3: "W3", 4: "W3", 5: "W3", 10: "W1", 11: "W1", 12: "W1", 13: "W1"},
    },
    "26SP": {
        "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "n_map": {1: "N3", 4: "N2", 7: "N1", 9: "N0", 3: "N3", 6: "N2", 10: "N1", 12: "N0"},
        "w_map": {1: "W3", 4: "W3", 7: "W3", 9: "W3", 3: "W1", 6: "W1", 10: "W1", 12: "W1"},
    },
}


def parse_harvest_out(path: Path) -> pd.DataFrame:
    rows = []
    pat = re.compile(
        r"RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+HNO\s+(?P<hno>\d+)\s+DATE\s+(?P<date>\d+).*?@CHPDTS@\s+(?P<val>[-+0-9.eE]+)"
    )
    if not path.exists():
        raise FileNotFoundError(f"Harvest output not found: {path}")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.search(line)
        if m:
            rows.append({
                "global_run": int(m.group("run")),
                "treatment": int(m.group("tn")),
                "hno": int(m.group("hno")),
                "date": int(m.group("date")),
                "CHPDT": float(m.group("val")),
            })
    if not rows:
        raise RuntimeError(f"No harvest records parsed from {path}")
    return pd.DataFrame(rows)


def extract_case_results(case_dir: Path, case_name: str, nmobmx: float, senrte: float) -> pd.DataFrame:
    h = parse_harvest_out(case_dir / "PestHarvest.OUT")
    mapping = pd.read_csv(case_dir / f"{case_name}_run_mapping.csv")
    h = h.merge(mapping[["global_run", "season_id"]], on="global_run", how="left")
    # Take terminal harvest per treatment
    h_term = h.sort_values(["season_id", "treatment", "hno"]).groupby(
        ["season_id", "treatment"], as_index=False
    ).tail(1)

    rows = []
    for sid, sinfo in SEASONS_INFO.items():
        for tn, n_level in sinfo["n_map"].items():
            w_level = sinfo["w_map"][tn]
            rec = h_term[(h_term["season_id"] == sid) & (h_term["treatment"] == tn)]
            if rec.empty:
                raise RuntimeError(f"Missing terminal harvest for {sid} treatment {tn}")
            chpdt_val = float(rec.iloc[0]["CHPDT"])
            rows.append({
                "case": case_name,
                "NMOBMX": nmobmx,
                "SENRTE": senrte,
                "season": sid,
                "water": w_level,
                "nitrogen": n_level,
                "treatment": tn,
                "CHPDT": chpdt_val,
            })
    return pd.DataFrame(rows)


def main() -> int:
    print(f"[run_nmobmx_senrte] Starting 3x3 orthogonal experiment in {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not BASE_PARAMS.exists():
        raise FileNotFoundError(f"Baseline parameter file missing: {BASE_PARAMS}")
    base_params_df = pd.read_csv(BASE_PARAMS)
    design_dict = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))

    # Setup isolated verified bundles
    bundles_dir = OUT_DIR / "_bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)

    for season in design_dict["seasons"]:
        sid = season["season_id"]
        src_season = BASE_DIR / "_seasons" / sid
        dst_bundle = bundles_dir / sid
        if dst_bundle.exists():
            shutil.rmtree(dst_bundle)
        dst_bundle.mkdir(parents=True, exist_ok=True)
        for f in src_season.iterdir():
            if f.is_file() and not f.name.endswith(".OUT") and not f.name.endswith(".log") and not f.name.startswith("pest_"):
                shutil.copy2(f, dst_bundle / f.name)
        season["bundle_path"] = str(dst_bundle)
        manifest_file = dst_bundle / "input_manifest.json"
        if manifest_file.exists():
            season["bundle_manifest_sha256"] = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

    # Prepare design JSON for diagnostic runs
    design_dict["design_id"] = "nmobmx_senrte_orthogonal_20260830"
    design_dict["purpose"] = "NMOBMX x SENRTE forward sensitivity orthogonal grid"
    design_path = OUT_DIR / "experiment_design.json"
    design_path.write_text(json.dumps(design_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    all_case_rows = []
    cases_grid = []

    for nm in NMOBMX_LEVELS:
        for sr in SENRTE_LEVELS:
            case_name = f"NM{int(nm*100):03d}_SR{int(sr*10):02d}"
            cases_grid.append((case_name, nm, sr))

    print(f"[run_nmobmx_senrte] Generated {len(cases_grid)} cases to simulate.")

    for case_name, nm, sr in cases_grid:
        case_dir = OUT_DIR / case_name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)

        params_df = base_params_df.copy()
        # Set NMOBMX
        if "NMOBMX" in params_df["name"].values:
            params_df.loc[params_df["name"] == "NMOBMX", "value"] = nm
        else:
            params_df.loc[len(params_df)] = ["NMOBMX", nm]
        # Set SENRTE
        if "SENRTE" in params_df["name"].values:
            params_df.loc[params_df["name"] == "SENRTE", "value"] = sr
        else:
            params_df.loc[len(params_df)] = ["SENRTE", sr]

        param_csv = case_dir / "parameters.csv"
        params_df.to_csv(param_csv, index=False)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

        cmd = [
            sys.executable,
            "-m", "src.calibration.run_multiseason",
            "--design", str(design_path),
            "--param-csv", str(param_csv),
            "--prefix", case_name,
            "--harvest-var", "CHPDT",
        ]
        print(f"\n--- Running case {case_name}: NMOBMX={nm}, SENRTE={sr} ---")
        res = subprocess.run(cmd, cwd=case_dir, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"[ERROR] Case {case_name} failed:")
            print(res.stderr)
            raise RuntimeError(f"Simulation failed for {case_name}")

        case_res = extract_case_results(case_dir, case_name, nm, sr)
        all_case_rows.append(case_res)

    all_results = pd.concat(all_case_rows, ignore_index=True)
    all_results.to_csv(OUT_DIR / "chpdt_by_treatment.csv", index=False)

    # Calculate response contrasts across nitrogen levels within each (case, season, water)
    wide = all_results.pivot_table(
        index=["case", "NMOBMX", "SENRTE", "season", "water"],
        columns="nitrogen",
        values="CHPDT",
        aggfunc="first",
    ).reset_index()

    for n_high, n_low in [("N1", "N0"), ("N2", "N0"), ("N3", "N0"), ("N2", "N1"), ("N3", "N2")]:
        if n_high in wide and n_low in wide:
            wide[f"{n_high}_minus_{n_low}"] = wide[n_high] - wide[n_low]

    wide.to_csv(OUT_DIR / "chpdt_response_contrasts.csv", index=False)

    print("\n" + "="*80)
    print("EXPERIMENT COMPLETED SUCCESSFULLY. Summary of contrasts (CHPDT kg/ha):")
    print("="*80)
    summary_cols = ["case", "NMOBMX", "SENRTE", "season", "water", "N0", "N1", "N2", "N3", "N1_minus_N0", "N2_minus_N1", "N3_minus_N2", "N3_minus_N0"]
    print(wide[[c for c in summary_cols if c in wide.columns]].to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
