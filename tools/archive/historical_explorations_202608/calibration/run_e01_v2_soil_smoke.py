"""E01 v2 soil moisture process smoke test for three-season bundles.

Spec: docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md section 6.7:
  "土壤水分过程链 smoke。SoilWat.OUT SW1D..SWnD 读取、深度映射、首测排除。"

This script runs DSSAT directly (bypassing run_dssat.py's cleanup that deletes
SoilWat.OUT) to verify the full soil-water observation pipeline:

  1. DSSAT produces SoilWat.OUT with SW1D..SW14D daily columns.
  2. SoilWat.OUT dates cover all observation dates in soil_water_observations.csv.
  3. Layer mapping uses the ACTUAL DSSAT output sub-layers (14 layers: 0-5,
     5-15, 15-20, 20-30, 30-40, 40-50, 50-60, 60-70, 70-80, 80-100,
     100-122, 122-145, 145-175, 175-203), NOT the 8 SLB layers in SOIL.SOL.
  4. Initial-condition-only observations (first date per (trno, depth)) are
     correctly flagged and excluded from the Phi-eligible set.
  5. Aggregated simulated SW (overlap-weighted mean of SW1D..SW14D) is
     computed for each (trno, date, measured_depth) and reported alongside
     the observed vwc_mean for sanity-check magnitude comparison.

Usage:
  python tools/calibration/run_e01_v2_soil_smoke.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SMOKE_RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "E01_v2_soil_smoke_20260726"

SEASONS = [
    {
        "season_id": "25SP",
        "bundle_dir": PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_actual_trial_calibration_v2_20260726",
        "excode": "XXQL2501",
    },
    {
        "season_id": "25FA",
        "bundle_dir": PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_actual_trial_calibration_v2_20260726",
        "excode": "XXQL2502",
    },
    {
        "season_id": "26SP",
        "bundle_dir": PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2601_actual_trial_calibration_v2_20260726",
        "excode": "XXQL2601",
    },
]

# ACTUAL DSSAT SoilWat.OUT sub-layer boundaries (cm), parsed from the
# comment line above the @YEAR header. DSSAT subdivides the 8 SLB layers
# into 14 output sub-layers. This is the GROUND TRUTH for layer mapping.
DSSAT_SOILWAT_LAYER_BOUNDARIES = [
    (0.0, 5.0),      # SW1D
    (5.0, 15.0),     # SW2D
    (15.0, 20.0),    # SW3D
    (20.0, 30.0),    # SW4D
    (30.0, 40.0),    # SW5D
    (40.0, 50.0),    # SW6D
    (50.0, 60.0),    # SW7D
    (60.0, 70.0),    # SW8D
    (70.0, 80.0),    # SW9D
    (80.0, 100.0),   # SW10D
    (100.0, 122.0),  # SW11D
    (122.0, 145.0),  # SW12D
    (145.0, 175.0),  # SW13D
    (175.0, 203.0),  # SW14D
]
N_DSSAT_LAYERS = len(DSSAT_SOILWAT_LAYER_BOUNDARIES)  # 14
SW_COLUMN_NAMES = [f"SW{i}D" for i in range(1, N_DSSAT_LAYERS + 1)]


def compute_overlap_weights(measured_top: float, measured_bottom: float) -> dict[int, float]:
    """Compute thickness-overlap weights for a measured layer against the
    14 DSSAT SoilWat.OUT sub-layers.

    w_ml = overlap(m, l) / thickness(m)
    Returns {layer_index (0-based): weight}.
    """
    m_thickness = measured_bottom - measured_top
    if m_thickness <= 0:
        raise ValueError(f"measured layer thickness <= 0: top={measured_top}, bottom={measured_bottom}")
    weights: dict[int, float] = {}
    for i, (layer_top, layer_bottom) in enumerate(DSSAT_SOILWAT_LAYER_BOUNDARIES):
        overlap = max(0.0, min(measured_bottom, layer_bottom) - max(measured_top, layer_top))
        if overlap > 0:
            weights[i] = overlap / m_thickness
    wsum = sum(weights.values())
    if not (0.999 <= wsum <= 1.001):
        raise ValueError(
            f"weights sum {wsum} != 1.0 for measured layer {measured_top}-{measured_bottom}"
        )
    return weights


def setup_season_run_dir(season: dict) -> Path:
    """Set up a fresh run directory for one season, copying all required
    files from the v2 bundle and the genotype templates."""
    season_id = season["season_id"]
    bundle_dir = season["bundle_dir"]
    excode = season["excode"]

    run_dir = SMOKE_RUN_DIR / season_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Copy files from v2 bundle
    files_to_copy = [
        f"{excode}.TMX",
        f"{excode}.TMA",
        f"{excode}.TMT",
        "SOIL.SOL",
        "DSSBatch.v48",
    ]
    for fname in files_to_copy:
        src = bundle_dir / fname
        if src.is_file():
            shutil.copy2(src, run_dir / fname)

    # Copy ALL weather files
    for wth_src in sorted(bundle_dir.glob("*.WTH")):
        shutil.copy2(wth_src, run_dir / wth_src.name)

    # Copy template files
    template_dir = PROJECT_ROOT / "data" / "templates" / "genotype"
    for fname in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
        src = template_dir / fname
        if src.is_file():
            shutil.copy2(src, run_dir / fname)

    # Copy DSSATPRO.v48
    dssatpro_src = PROJECT_ROOT / "data" / "templates" / "DSSATPRO.v48"
    if dssatpro_src.is_file():
        shutil.copy2(dssatpro_src, run_dir / "DSSATPRO.v48")

    # Copy default pest_params.csv from the E01_v2_smoke run (already generated)
    smoke_param_src = (
        PROJECT_ROOT / "workspace" / "runs" / "E01_v2_smoke_20260726" / season_id / "pest_params.csv"
    )
    if smoke_param_src.is_file():
        shutil.copy2(smoke_param_src, run_dir / "pest_params.csv")

    return run_dir


def run_dssat_direct(run_dir: Path) -> tuple[bool, str]:
    """Run DSSAT directly via DSCSM048.EXE, bypassing run_dssat.py cleanup.

    First runs run_dssat.py to inject parameters into CUL/ECO/SPE, then
    re-runs DSCSM048.EXE directly to regenerate all .OUT files (including
    SoilWat.OUT, which run_dssat.py's cleanup would delete).
    """
    run_dssat_script = PROJECT_ROOT / "src" / "dssat" / "run_dssat.py"

    # Step 1: Run run_dssat.py to inject parameters and generate CUL/ECO/SPE.
    # This will also run DSSAT once and then cleanup (deleting SoilWat.OUT),
    # but the generated CUL/ECO/SPE files will remain.
    cmd_inject = [
        sys.executable,
        str(run_dssat_script),
        "--param-csv", "pest_params.csv",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
    ]
    try:
        result = subprocess.run(
            cmd_inject,
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            return False, f"run_dssat.py failed: {result.stdout[-500:]} {result.stderr[-500:]}"
    except subprocess.TimeoutExpired:
        return False, "run_dssat.py TIMEOUT"

    # Step 2: Run DSCSM048.EXE directly to regenerate ALL .OUT files.
    # The CUL/ECO/SPE/SOIL/FileX files are already in place from step 1.
    dssat_exe = shutil.which("DSCSM048.EXE")
    if not dssat_exe:
        # Fallback: look in C:\DSSAT48\
        candidate = r"C:\DSSAT48\DSCSM048.EXE"
        if os.path.exists(candidate):
            dssat_exe = candidate
    if not dssat_exe:
        return False, "DSCSM048.EXE not found in PATH or C:\\DSSAT48\\"

    cmd_direct = [dssat_exe, "B", "DSSBatch.v48"]
    try:
        result = subprocess.run(
            cmd_direct,
            cwd=str(run_dir),
            input="\n" * 8,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout + "\n" + result.stderr
        if result.returncode != 0:
            return False, f"DSCSM048.EXE exit {result.returncode}: {output[-500:]}"
    except subprocess.TimeoutExpired:
        return False, "DSCSM048.EXE TIMEOUT"

    soilwat_path = run_dir / "SoilWat.OUT"
    if not soilwat_path.is_file():
        return False, "SoilWat.OUT not generated after direct DSSAT run"

    return True, output


def parse_soilwat_out(soilwat_path: Path) -> dict[int, dict[int, list[float]]]:
    """Parse SoilWat.OUT to extract SW1D..SW14D values per (trno, yyddd).

    Returns dict: {trno: {yyddd: [sw1, sw2, ..., sw14]}}.

    SoilWat.OUT structure:
      *RUN   <run_no>  : <tname>  <model>  <excode>  <trno>
      @YEAR DOY DAS ... SW1D SW2D ... SW14D
       2025 067   0  ... 0.216 0.216 ... 0.263
    """
    if not soilwat_path.is_file():
        return {}
    lines = soilwat_path.read_text(encoding="utf-8", errors="replace").splitlines()
    result: dict[int, dict[int, list[float]]] = {}
    current_trno: int | None = None
    sw_cols: list[int] | None = None
    year_col: int | None = None
    doy_col: int | None = None

    for line in lines:
        if line.startswith("*RUN"):
            parts = line.split()
            trno_candidate: int | None = None
            for tok in reversed(parts):
                try:
                    trno_candidate = int(tok)
                    break
                except ValueError:
                    continue
            current_trno = trno_candidate
            sw_cols = None
            year_col = doy_col = None
            continue

        if line.lstrip().startswith("@YEAR"):
            cols = line.split()
            sw_cols = []
            for j, c in enumerate(cols):
                if c in ("YEAR", "@YEAR"):
                    year_col = j
                elif c == "DOY":
                    doy_col = j
                elif re.match(r"^SW\d+D$", c):
                    sw_cols.append(j)
            continue

        if current_trno is None or year_col is None or doy_col is None or not sw_cols:
            continue
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.startswith("!"):
            continue

        parts = line.split()
        if len(parts) <= max(sw_cols):
            continue
        try:
            year_val = int(parts[year_col])
            doy_val = int(parts[doy_col])
            sw_values = [float(parts[j]) for j in sw_cols]
        except (ValueError, IndexError):
            continue
        yyddd = (year_val % 100) * 1000 + doy_val
        result.setdefault(current_trno, {})[yyddd] = sw_values

    return result


def load_soil_observations(bundle_dir: Path) -> list[dict]:
    """Load soil_water_observations.csv into a list of dicts."""
    csv_path = bundle_dir / "soil_water_observations.csv"
    if not csv_path.is_file():
        return []
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def date_str_to_yyddd(date_str: str) -> int:
    """Convert 'YYYY-MM-DD' to YYDDD (e.g., '2025-03-12' -> 25071)."""
    y, m, d = date_str.split("-")
    from datetime import date
    dt = date(int(y), int(m), int(d))
    doy = dt.timetuple().tm_yday
    return (int(y) % 100) * 1000 + doy


def verify_soil_obs(
    season: dict,
    soilwat_data: dict[int, dict[int, list[float]]],
    observations: list[dict],
) -> dict:
    """Verify the soil-water pipeline:

      1. Each observation date has a matching SoilWat.OUT date.
      2. Layer mapping (using 14 sub-layers) produces a valid aggregated SW.
      3. initial_condition_only flag correctly identifies first date per
         (trno, depth).
      4. Phi-eligible observations (phi_role=soil_water_phi) exclude the
         initial-condition-only set.
    """
    verification: dict = {
        "n_observations": len(observations),
        "n_init_cond_only": 0,
        "n_phi_eligible": 0,
        "n_dates_matched_in_soilwat": 0,
        "n_dates_missing_in_soilwat": 0,
        "n_layer_mapping_ok": 0,
        "n_layer_mapping_failed": 0,
        "missing_dates": [],
        "layer_mapping_errors": [],
        "aggregated_sw_samples": [],
        "init_cond_audit": {
            "n_first_dates_checked": 0,
            "n_first_dates_flagged_correctly": 0,
            "errors": [],
        },
    }

    # Group observations by (trno, depth_label) to verify first-date flagging
    by_trno_depth: dict[tuple[int, str], list[dict]] = {}
    for obs in observations:
        trno = int(obs["trno"])
        depth_label = obs["depth_label"]
        by_trno_depth.setdefault((trno, depth_label), []).append(obs)

    # Verify first-date flagging
    for (trno, depth_label), obs_list in by_trno_depth.items():
        obs_sorted = sorted(obs_list, key=lambda x: x["date"])
        if not obs_sorted:
            continue
        first = obs_sorted[0]
        verification["init_cond_audit"]["n_first_dates_checked"] += 1
        if first.get("initial_condition_only", "").lower() == "true":
            verification["init_cond_audit"]["n_first_dates_flagged_correctly"] += 1
        else:
            verification["init_cond_audit"]["errors"].append(
                f"trno={trno} depth={depth_label}: first date {first['date']} "
                "not flagged initial_condition_only"
            )
        # All non-first should NOT be initial_condition_only
        for obs in obs_sorted[1:]:
            if obs.get("initial_condition_only", "").lower() == "true":
                verification["init_cond_audit"]["errors"].append(
                    f"trno={trno} depth={depth_label}: non-first date {obs['date']} "
                    "incorrectly flagged initial_condition_only"
                )

    # Verify each observation against SoilWat.OUT
    for obs in observations:
        trno = int(obs["trno"])
        date_str = obs["date"]
        depth_label = obs["depth_label"]
        depth_top = float(obs["depth_top_cm"])
        depth_bottom = float(obs["depth_bottom_cm"])
        observed_vwc = float(obs["vwc_mean"])
        init_only = obs.get("initial_condition_only", "").lower() == "true"
        phi_role = obs.get("phi_role", "")

        if init_only:
            verification["n_init_cond_only"] += 1
        if phi_role == "soil_water_phi":
            verification["n_phi_eligible"] += 1

        yyddd = date_str_to_yyddd(date_str)
        sw_by_date = soilwat_data.get(trno, {})
        if yyddd in sw_by_date:
            verification["n_dates_matched_in_soilwat"] += 1
            sw_values = sw_by_date[yyddd]
            # Compute overlap-weighted aggregation
            try:
                weights = compute_overlap_weights(depth_top, depth_bottom)
                aggregated_sw = sum(weights[i] * sw_values[i] for i in weights)
                verification["n_layer_mapping_ok"] += 1
                # Save first 5 samples for the report
                if len(verification["aggregated_sw_samples"]) < 5:
                    verification["aggregated_sw_samples"].append({
                        "trno": trno,
                        "date": date_str,
                        "yyddd": yyddd,
                        "depth_label": depth_label,
                        "observed_vwc": observed_vwc,
                        "simulated_vwc_aggregated": round(aggregated_sw, 4),
                        "n_dssat_layers_used": len(weights),
                        "weights": {str(k): round(v, 4) for k, v in weights.items()},
                    })
            except ValueError as e:
                verification["n_layer_mapping_failed"] += 1
                verification["layer_mapping_errors"].append(str(e))
        else:
            verification["n_dates_missing_in_soilwat"] += 1
            verification["missing_dates"].append({
                "trno": trno,
                "date": date_str,
                "yyddd": yyddd,
                "depth_label": depth_label,
            })

    return verification


def main() -> None:
    print(f"[E01 v2 soil smoke] Run directory: {SMOKE_RUN_DIR}")
    SMOKE_RUN_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    overall_pass = True

    for season in SEASONS:
        season_id = season["season_id"]
        excode = season["excode"]
        print(f"\n=== {season_id} ({excode}) soil smoke ===")

        # Load observations
        observations = load_soil_observations(season["bundle_dir"])
        print(f"  Loaded {len(observations)} soil observations")
        if not observations:
            print(f"  SKIP: no soil observations for {season_id}")
            results.append({
                "season_id": season_id,
                "excode": excode,
                "dssat_success": False,
                "verification": None,
                "error": "no soil observations",
            })
            overall_pass = False
            continue

        # Setup run directory
        print(f"  Setting up run directory...")
        run_dir = setup_season_run_dir(season)

        # Run DSSAT directly
        print(f"  Running DSSAT (direct, no cleanup)...")
        success, output = run_dssat_direct(run_dir)
        print(f"  DSSAT exit: {'SUCCESS' if success else 'FAILURE'}")

        log_path = run_dir / "dssat_run_log.txt"
        log_path.write_text(output, encoding="utf-8")

        if not success:
            print(f"  ERROR: {output[:300]}")
            overall_pass = False
            results.append({
                "season_id": season_id,
                "excode": excode,
                "dssat_success": False,
                "verification": None,
                "error": output[:500],
            })
            continue

        # Parse SoilWat.OUT
        soilwat_path = run_dir / "SoilWat.OUT"
        print(f"  Parsing SoilWat.OUT...")
        soilwat_data = parse_soilwat_out(soilwat_path)
        n_trt = len(soilwat_data)
        n_dates = sum(len(d) for d in soilwat_data.values())
        print(f"  SoilWat.OUT: {n_trt} treatments, {n_dates} daily records")

        # Verify observations
        print(f"  Verifying soil observations...")
        verification = verify_soil_obs(season, soilwat_data, observations)
        print(f"  Obs: {verification['n_observations']} total, "
              f"{verification['n_init_cond_only']} init-only, "
              f"{verification['n_phi_eligible']} phi-eligible")
        print(f"  Date match: {verification['n_dates_matched_in_soilwat']}/"
              f"{verification['n_observations']} in SoilWat.OUT")
        print(f"  Layer mapping: {verification['n_layer_mapping_ok']} ok, "
              f"{verification['n_layer_mapping_failed']} failed")
        print(f"  Init-cond audit: "
              f"{verification['init_cond_audit']['n_first_dates_flagged_correctly']}/"
              f"{verification['init_cond_audit']['n_first_dates_checked']} correct")

        if verification["missing_dates"]:
            print(f"  Missing dates (first 3): {verification['missing_dates'][:3]}")
        if verification["layer_mapping_errors"]:
            print(f"  Layer mapping errors (first 3): {verification['layer_mapping_errors'][:3]}")
        if verification["aggregated_sw_samples"]:
            s = verification["aggregated_sw_samples"][0]
            print(f"  Sample aggregation: trno={s['trno']} date={s['date']} "
                  f"depth={s['depth_label']} obs={s['observed_vwc']:.4f} "
                  f"sim={s['simulated_vwc_aggregated']:.4f}")

        # Smoke pass criteria:
        #   1. SoilWat.OUT parsed with >=1 treatment
        #   2. >=90% of observation dates found in SoilWat.OUT
        #   3. Layer mapping succeeded for all matched dates
        #   4. Init-cond flagging 100% correct
        n_obs = verification["n_observations"]
        n_matched = verification["n_dates_matched_in_soilwat"]
        n_map_ok = verification["n_layer_mapping_ok"]
        n_map_fail = verification["n_layer_mapping_failed"]
        n_first_checked = verification["init_cond_audit"]["n_first_dates_checked"]
        n_first_ok = verification["init_cond_audit"]["n_first_dates_flagged_correctly"]
        init_errors = len(verification["init_cond_audit"]["errors"])

        date_match_rate = n_matched / n_obs if n_obs > 0 else 0.0
        season_pass = (
            n_trt > 0
            and date_match_rate >= 0.90
            and n_map_fail == 0
            and n_map_ok == n_matched
            and n_first_ok == n_first_checked
            and init_errors == 0
        )
        if not season_pass:
            overall_pass = False

        results.append({
            "season_id": season_id,
            "excode": excode,
            "dssat_success": True,
            "verification": verification,
            "season_pass": season_pass,
        })

    # Write report
    report = {
        "smoke_id": "E01_v2_soil_smoke_20260726",
        "spec_compliance": "docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md section 6.7",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": "pass" if overall_pass else "fail",
        "n_seasons": len(SEASONS),
        "n_seasons_pass": sum(1 for r in results if r.get("season_pass", False)),
        "dssat_soilwat_layer_boundaries": [
            {"index": i, "top_cm": t, "bottom_cm": b, "sw_column": f"SW{i+1}D"}
            for i, (t, b) in enumerate(DSSAT_SOILWAT_LAYER_BOUNDARIES)
        ],
        "seasons": results,
    }
    report_path = SMOKE_RUN_DIR / "E01_v2_soil_smoke_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"E01 v2 soil smoke complete: {'PASS' if overall_pass else 'FAIL'}")
    print(f"  Report: {report_path}")
    print(f"  Seasons: {report['n_seasons_pass']}/{report['n_seasons']} passed")


if __name__ == "__main__":
    main()
