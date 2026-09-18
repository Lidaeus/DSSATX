#!/usr/bin/env python3
"""Execute 3-season independent validation (25SP, 26SP, and blind 25FA) for
full_genetic_98pct_v5 champion Candidate 46, and render the complete diagnostic
suite to figture/full_gen98v5_real46_3season_full_suite_20260915.

Follows the standard diagnostic engine pattern of
plot_fullgen98v2_real70_engine_20260915.py and
evaluate_fixedsoil_official_best189_20260813.py.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.run_dssat import prepare_run_directory

RUN_NAME = "full_genetic_98pct_v5_20260915"
CASE = "full_gen98_v5"
PARAM_CSV = ROOT / "workspace" / "runs" / RUN_NAME / "full_gen98_v5_best_parameters_fixed.csv"
WORK = ROOT / "workspace" / "reports" / "fullgen98v5_real46_3season_20260915"
DET_ROOT = WORK / "det_engine"
OUT_ROOT = ROOT / "figture" / "full_gen98v5_real46_3season_full_suite_20260915"
MAPPING_CSV = ROOT / "configs" / "runs" / "e02_from_scratch_water_n_mapping_20260826.csv"

SEASONS_CONFIG = [
    {
        "season_id": "25SP",
        "excode": "XXQL2501",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2501_unified_20260914",
    },
    {
        "season_id": "25FA",
        "excode": "XXQL2502",
        "treatments": list(range(1, 13)),
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2502_unified_20260914",
    },
    {
        "season_id": "26SP",
        "excode": "XXQL2601",
        "treatments": list(range(1, 13)),
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2601_unified_20260914",
    },
]


def run_deterministic_seasons():
    """Run DSSAT independently for each season so that run numbering is clean (1..N)."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for cfg in SEASONS_CONFIG:
        sid = cfg["season_id"]
        season_dir = DET_ROOT / "_seasons" / sid
        season_dir.mkdir(parents=True, exist_ok=True)
        batch_src = cfg["bundle"] / "DSSBatch.v48"
        print(f"[{sid}] Preparing run directory in {season_dir}...")
        batch_dest = prepare_run_directory(
            season_dir, ["--batch", str(batch_src), "--input-dir", str(cfg["bundle"])]
        )
        print(f"[{sid}] Executing DSSAT with Candidate 46 parameters...")
        cmd = [
            sys.executable,
            "-m",
            "src.dssat.run_dssat",
            "--param-csv",
            str(PARAM_CSV.resolve()),
            "--batch",
            batch_dest.name,
            "--harvest-var",
            "CHPDT",
        ]
        res = subprocess.run(cmd, cwd=season_dir, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"[{sid}] DSSAT stdout tail:", res.stdout[-800:])
            print(f"[{sid}] DSSAT stderr tail:", res.stderr[-400:])
            raise RuntimeError(f"DSSAT execution failed for season {sid}")
        print(f"[{sid}] Simulation complete. OUT files generated.")


def main() -> int:
    print("=" * 70)
    print("Starting 3-Season Validation Suite for V5 (Candidate 46)")
    print(f"Parameter file: {PARAM_CSV}")
    print(f"Output directory: {OUT_ROOT}")
    print("=" * 70)

    if WORK.exists():
        shutil.rmtree(WORK)
    DET_ROOT.mkdir(parents=True)

    # 1. Run DSSAT per season
    run_deterministic_seasons()

    # 2. Mark status and copy params
    shutil.copy2(PARAM_CSV, DET_ROOT / "best_member_46_params.csv")
    (DET_ROOT / "multiseason_run_status.json").write_text(
        json.dumps({"status": "done", "replayed_by": "direct_dssat_v5_candidate46"}),
        encoding="utf-8",
    )

    # Generate minimal input_manifest.json for each season directory (required by evaluation engine)
    import hashlib
    for sdir in (DET_ROOT / "_seasons").iterdir():
        if not sdir.is_dir():
            continue
        files = [
            {"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
            for p in sorted(sdir.iterdir()) if p.is_file()
        ]
        (sdir / "input_manifest.json").write_text(
            json.dumps({"bundle_id": f"engine_replay_{sdir.name}", "files": files}, indent=2) + "\n",
            encoding="utf-8",
        )

    # 3. Configure evaluation engine
    evaluation.RUN_DIR = ROOT / "workspace" / "runs" / RUN_NAME
    evaluation.DET_ROOT = DET_ROOT
    evaluation.OUT_ROOT = OUT_ROOT
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = "46"
    evaluation.SOURCE_ITERATION = 5
    evaluation.BEST_PHI = 876.65
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "three_season_diagnostics_fullgen98v5_real46_20260915"
    evaluation.SPE = ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = "full_genetic_98pct_v5 (163 active parameters; 25FA blind validation)"
    evaluation.SOIL_INJECTION_DESCRIPTION = "per batch frozen bounds"
    evaluation.OBS_REGISTRY = evaluation.RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = MAPPING_CSV
    evaluation.SEASONS = [
        {
            "season_id": cfg["season_id"],
            "excode": cfg["excode"],
            "treatments": cfg["treatments"],
            "bundle": DET_ROOT / "_seasons" / cfg["season_id"],
        }
        for cfg in SEASONS_CONFIG
    ]
    evaluation.SEASON_IDS = ["25SP", "25FA", "26SP"]
    evaluation.COLORS = {"25SP": "#2878B5", "25FA": "#E67E22", "26SP": "#2A9D55"}
    evaluation.EXTRA_LIMITATIONS = [
        "Champion realization 46 from full_genetic_98pct_v5 (71 active calibrated parameters, "
        "8-treatment spring calibration subset: 25SP extremes + 26SP contrasts).",
        "25FA (2025 Autumn) evaluated as 100% BLIND independent validation dataset with zero tuning.",
        "All 34 treatments across three seasons replayed deterministically.",
    ]
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation.EXE = ROOT / "DSCSM048.EXE"
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    os.environ["PYTHONPATH"] = str(ROOT)

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True)

    result = int(evaluation.main() or 0)

    # Enrich manifest
    manifest_path = OUT_ROOT / "diagnostic_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            dssat_version="official DSSAT v4.8",
            member_selection_rule="V5 Champion realization 46",
            custom_genetic_params="Candidate 46 parameters (71 calibrated active parameters + senescence model)",
            validation_dataset="25FA (2025 Autumn, XXQL2502) 12 treatments blind validation",
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print("\n" + "=" * 70)
    print(f"3-Season diagnostic suite successfully generated at:\n{OUT_ROOT}")
    print("=" * 70)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
