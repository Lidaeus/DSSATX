"""Replay full_genetic_98pct_v2 realization 70 (Pareto optimal) on all 22
treatments and render the full diagnostic suite via the standard evaluation
engine.  Follows the same wrapper pattern as plot_v48sp26_only_best_22tmt_20260903.py.

The deterministic outputs already exist (direct DSSAT run); this wrapper
skips the replay when the status file is present and proceeds to
comparisons + plot_dynamics + metric heatmaps.
"""
from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping

RUN_NAME = "full_genetic_98pct_v2_20260915"
CASE = "full_gen98_v2"
WORK = ROOT / "workspace/reports/fullgen98v2_real70_22tmt_20260915"
DET_DIRECT = WORK / "det_direct"       # already has _seasons/ + DSSAT outputs
DET_ROOT = WORK / "det_engine"          # engine-format working dir
OUT_ROOT = ROOT / "figture/full_gen98v2_real70_22tmt_full_suite_20260915"


def main() -> int:
    # --- prepare engine-format DET_ROOT from the existing direct outputs ---
    if DET_ROOT.exists():
        shutil.rmtree(DET_ROOT)
    DET_ROOT.mkdir(parents=True)
    # copy _seasons (compare CSVs + DSSAT outputs + inputs)
    shutil.copytree(DET_DIRECT / "_seasons", DET_ROOT / "_seasons")
    # CRITICAL: split DSSAT outputs per season — the engine assumes RUN starts
    # at 1 for each season, but the direct 22-trt run is sequential (25SP=1-10,
    # 26SP=11-22).  Without this split, 26SP reads 25SP's RUN1-12 as its own.
    import re as _re
    def _split_outfile(src_path, dst_dir, start_run, n_runs):
        lines = src_path.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
        out, new_num = [], 0
        for line in lines:
            m = _re.match(r'\*RUN\s+(\d+)', line)
            if m:
                rn = int(m.group(1))
                if start_run <= rn < start_run + n_runs:
                    new_num = rn - start_run + 1
                    out.append(_re.sub(r'\*RUN\s+\d+', f'*RUN  {new_num:04d}', line))
                else:
                    new_num = 0
                continue
            if new_num > 0:
                out.append(line)
        src_path.write_text(''.join(out), encoding='utf-8')
    for outfile in ('PlantGro.OUT', 'FreshWt.OUT', 'Evaluate.OUT'):
        for sdir, start, n in [(DET_ROOT/'_seasons/25SP', 1, 10),
                                (DET_ROOT/'_seasons/26SP', 11, 12)]:
            f = sdir / outfile
            if f.exists():
                _split_outfile(f, sdir, start, n)
    # minimal manifests for each season dir (engine _write_design requires them)
    import hashlib
    for sdir in (DET_ROOT / "_seasons").iterdir():
        if not sdir.is_dir():
            continue
        files = [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                  "bytes": p.stat().st_size} for p in sorted(sdir.iterdir()) if p.is_file()]
        (sdir / "input_manifest.json").write_text(
            json.dumps({"bundle_id": f"engine_replay_{sdir.name}", "files": files}, indent=2) + "\n",
            encoding="utf-8")
    # copy params + status (marks replay as done)
    shutil.copy2(WORK / "det_real70/params.csv", DET_ROOT / "best_member_70_params.csv")
    (DET_ROOT / "multiseason_run_status.json").write_text(
        json.dumps({"status": "done", "replayed_by": "direct_dssat"}), encoding="utf-8")

    # mapping CSV
    m25 = derive_filex_water_n_mapping(
        DET_ROOT / "_seasons/25SP/XXQL2501.TMX", season_id="25SP",
        treatments=[2, 3, 4, 5, 9, 10, 11, 12, 13, 14])
    m26 = derive_filex_water_n_mapping(
        DET_ROOT / "_seasons/26SP/XXQL2601.TMX", season_id="26SP",
        treatments=list(range(1, 13)))
    mapping_csv = DET_ROOT / "two_season_water_n_mapping_from_filex.csv"
    pd.concat([m25, m26], ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")

    # --- configure evaluation engine ---
    evaluation.RUN_DIR = ROOT / "workspace/runs" / RUN_NAME
    evaluation.DET_ROOT = DET_ROOT
    evaluation.OUT_ROOT = OUT_ROOT
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = "70"
    evaluation.SOURCE_ITERATION = 5
    evaluation.BEST_PHI = 8611.03
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "two_season_diagnostics_fullgen98v2_real70_20260915"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = "full_genetic_98pct_v2 (156-param, 8-trt calib subset)"
    evaluation.SOIL_INJECTION_DESCRIPTION = "per batch frozen bounds"
    evaluation.OBS_REGISTRY = evaluation.RUN_DIR / f"{CASE}_observation_registry.csv"  # may not exist
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.SEASONS = [
        {"season_id": "25SP", "excode": "XXQL2501",
         "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
         "bundle": DET_ROOT / "_seasons/25SP"},
        {"season_id": "26SP", "excode": "XXQL2601",
         "treatments": list(range(1, 13)),
         "bundle": DET_ROOT / "_seasons/26SP"},
    ]
    evaluation.SEASON_IDS = ["25SP", "26SP"]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}
    evaluation.EXTRA_LIMITATIONS = [
        "Pareto-optimal realization 70 from full_genetic_98pct_v2 (156 active parameters, "
        "8-treatment calibration subset: 25SP extremes + 26SP contrasts).",
        "All 22 spring treatments replayed deterministically; posterior/uncertainty "
        "figures intentionally excluded per user request.",
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

    # enrich manifest
    manifest_path = OUT_ROOT / "diagnostic_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            dssat_version="official DSSAT v4.8",
            member_selection_rule="Pareto-optimal realization 70 (user-selected)",
            custom_genetic_params="real70 parameters (156 params, direct ECO injection)",
            bundle_note="Workspace root XXQL2501 + iso XXQL2601 (batch-effective inputs)",
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
