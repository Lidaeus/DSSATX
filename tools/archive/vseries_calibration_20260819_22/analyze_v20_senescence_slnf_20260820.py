"""Replay v20 Senescence SLNF official run and render all diagnostic figures in figture/."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping
import tools.analysis.analyze_formal_measuredmoisture_best42_20260819 as audit

CASE = "e02_v20_senescence_slnf_official_200x6_20260820"
RUN_DIR = ROOT / "workspace/runs" / CASE


def get_best_member_and_phi() -> tuple[str, float]:
    phi_csv = RUN_DIR / f"{CASE}.phi.actual.csv"
    if not phi_csv.exists():
        raise FileNotFoundError(f"Phi file {phi_csv} not found")
    df = pd.read_csv(phi_csv)
    last = df.iloc[-1]
    members = [c for c in df.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
    best_mem = None
    min_phi = float("inf")
    for m in members:
        val = float(last[m])
        if val < min_phi:
            min_phi = val
            best_mem = m
    return str(best_mem), float(min_phi)


def main() -> int:
    best_member, best_phi = get_best_member_and_phi()
    print(f"v20 Best Member: {best_member} with Lowest Phi: {best_phi:.4f}")

    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = 6
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "engineering_validated"
    evaluation.ARTIFACT_TYPE = f"v20_senescence_slnf_best{best_member}_two_season_diagnostics_20260820"
    evaluation.HARVEST_OBJECTIVE = "Phi budget: 50% harvest dry (200 proc + 300 term) : 45% process states (150 LAI + 150 LWAD + 150 SWAD) : 5% soil water"
    evaluation.SOIL_INJECTION_DESCRIPTION = "10-layer refined soil with active SOIL_SLNF & SRGF; SLPF capped at 0.955; 5cm topdressing depth"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / f"figture/e02_v20_senescence_slnf_best{best_member}_two_season_full_20260820"
    evaluation.DET_ROOT = RUN_DIR / f"deterministic_candidates/best_phi_member{best_member}_two_season_20260820"
    evaluation.SEASONS = [
        {
            "season_id": "25SP", "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820",
        },
        {
            "season_id": "26SP", "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820",
        },
    ]
    evaluation.SEASON_IDS = [item["season_id"] for item in evaluation.SEASONS]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation.DET_ROOT.mkdir(parents=True, exist_ok=True)

    mapping_csv = evaluation.DET_ROOT / "two_season_water_n_mapping_from_filex.csv"
    mappings = [
        derive_filex_water_n_mapping(
            season["bundle"] / f"{season['excode']}.TMX",
            season_id=season["season_id"], treatments=season["treatments"],
        )
        for season in evaluation.SEASONS
    ]
    pd.concat(mappings, ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.EXTRA_LIMITATIONS = [
        "Calibration used 25SP TN 2/5/10/13 and 26SP TN 2/11/3/12 only; other treatments are out-of-objective diagnostics.",
        "Both spring seasons use harvest-date matched measured fruit dry-matter fractions from corrected bundles.",
        "Water and nitrogen identities are read from current FileX management data, not inferred from treatment numbers.",
        "Python run diagnostics only; these files are not publication Fig/FigS artifacts.",
    ]
    rc = int(evaluation.main() or 0)
    if rc:
        return rc

    for name in ("metrics_by_season_variable.csv", "organ_n_compare.csv"):
        source = evaluation.DET_ROOT / name
        if source.is_file():
            shutil.copy2(source, evaluation.OUT_ROOT / name)
    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calibration_treatments"] = {
        "25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]
    }
    manifest["evaluation_treatments"] = {
        season["season_id"]: season["treatments"] for season in evaluation.SEASONS
    }
    manifest["bundle_note"] = "v20 formal: NMOBMX<=0.20 + SENRTE<=2.50 + NVSMOB in [0.20,0.25] + SOIL_SLNF in [1.20,1.60] + Phi budget (200 proc + 300 term)"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Run formal summary & boundary audit
    audit.CASE = CASE
    audit.RUN = RUN_DIR
    audit.DET = evaluation.DET_ROOT
    audit.OUT = evaluation.OUT_ROOT
    audit.BEST = best_member
    audit.main()

    print(f"Diagnostic plotting completed successfully in {evaluation.OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
