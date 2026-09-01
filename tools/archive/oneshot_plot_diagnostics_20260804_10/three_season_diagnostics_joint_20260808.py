"""Three-season diagnostics for joint calibration best member #108.

Uses a3_nr_zp exe + #108 params (330, including inverted IC SNH4/SNO3 for
25SP+26SP) on the three-season layermean_ic_valid bundles. The IC parameters
in the param CSV are automatically injected into the FileX by run_dssat.py
at runtime via update_initial_soil_n_file().

25FA has no IC parameters (inversion was 25SP+26SP only), so it uses the
bundle's default layermean IC values.

Usage:
    python tools/calibration/three_season_diagnostics_joint_20260808.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as _pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/calibration"))

import run_best_member_three_season_custom_diagnostics_20260804 as tsd

# Override SEASONS -> three-season layermean_ic_valid bundles
tsd.SEASONS = [
    {"season_id": "25SP", "experiment_code": "XXQL2501",
     "bundle_path": "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
     "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
    {"season_id": "25FA", "experiment_code": "XXQL2502",
     "bundle_path": "data/user/experiments/xxql2502_layermean_ic_valid_n012_v1_20260801",
     "treatments": list(range(1, 13))},
    {"season_id": "26SP", "experiment_code": "XXQL2601",
     "bundle_path": "data/user/experiments/xxql2601_layermean_ic_valid_n012_v1_20260801",
     "treatments": list(range(1, 13))},
]

# Override custom exe/SPE -> a3_nr_zp version
A3_DIR = ROOT / "windows/windows_a3_nr_zp_20260806"
tsd.CUSTOM_EXE = A3_DIR / "DSCSM048.EXE"
tsd.CUSTOM_SPE = A3_DIR / "Genotype/TMGRO048.SPE"

JOINT_RUN = ROOT / "workspace/runs/e02_v2_joint_genetic_soiln_25sp26sp_200x5_20260808"
JOINT_CASE = "e02_v2_joint_genetic_soiln_25sp26sp_200x5_20260808"
BEST_MEMBER = "108"
DET_ROOT = ROOT / f"workspace/runs/{JOINT_CASE}_best{BEST_MEMBER}_three_season_20260808"
OUT_ROOT = ROOT / "figture/joint_genetic_soiln_three_season_20260808"


def _export_joint_member(out_csv: Path) -> int:
    """Export best member #108 params from the joint calibration (iter 5)."""
    frame = _pd.read_csv(JOINT_RUN / f"{JOINT_CASE}.5.par.csv")
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST_MEMBER)
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        v = float(row[col])
        if not math.isfinite(v):
            continue
        records.append({"name": str(col).upper(), "value": v})
    _pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def main() -> int:
    DET_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    print(f"joint calibration best member = #{BEST_MEMBER}")
    print(f"custom exe: {tsd.CUSTOM_EXE}")
    print(f"custom SPE: {tsd.CUSTOM_SPE}")
    print("three-season bundles (layermean_ic_valid):")
    for s in tsd.SEASONS:
        print(f"  {s['season_id']}  {s['experiment_code']}  TN={s['treatments']}")

    params = DET_ROOT / f"best_member_{BEST_MEMBER}_params.csv"
    n_params = _export_joint_member(params)
    print(f"exported {n_params} parameters (including IC SNH4/SNO3 for 25SP+26SP)")

    # Count IC params
    ic_count = sum(1 for r in _pd.read_csv(params).itertuples() if str(r.name).startswith("IC_"))
    print(f"  IC parameters: {ic_count} (will be injected into FileX at runtime)")

    design = tsd._write_design(DET_ROOT, JOINT_CASE, BEST_MEMBER)
    tsd._set_env()
    backup = tsd._backup_filex(DET_ROOT)
    try:
        status = DET_ROOT / "multiseason_run_status.json"
        if not status.is_file():
            tsd._run([
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design), "--param-csv", str(params),
                "--prefix", f"best{BEST_MEMBER}_three_season_joint",
                "--harvest-var", "CHPDT", "--keep-nitrogen-outputs",
            ], DET_ROOT)
        tsd._run_comparisons(DET_ROOT)
        tsd._organ_n_pairs(DET_ROOT)
        metrics = tsd._metric_rows(DET_ROOT)

        plotter = ROOT / "tools/calibration/plot_dynamics.py"
        tsd._run([
            sys.executable, str(plotter),
            "--det-root", str(DET_ROOT),
            "--out-root", str(OUT_ROOT),
            "--seasons", "25SP,25FA,26SP",
        ], ROOT)
        metric_plots = tsd._plot_metrics(metrics, OUT_ROOT)

        extra = DET_ROOT / "organ_n_compare.csv"
        extra_pairs = _pd.read_csv(extra) if extra.is_file() else _pd.DataFrame()
        if not extra_pairs.empty:
            process_extra = []
            for season in tsd.SEASONS:
                sid = season["season_id"]
                path = DET_ROOT / "_seasons" / sid / f"{sid}_deterministic_process_compare.csv"
                if path.is_file() and path.stat().st_size > 2:
                    f = _pd.read_csv(path)
                    for variable in ["CHTD"]:
                        obs_col, sim_col = f"OBS_{variable}", f"SIM_{variable}"
                        if obs_col in f and sim_col in f:
                            sub = f[["TN", "DATE", obs_col, sim_col]].rename(columns={obs_col: "observed", sim_col: "simulated"})
                            sub["season"] = sid
                            sub["variable"] = variable
                            sub = sub[(sub["observed"] != -99) & (sub["simulated"] != -99)]
                            process_extra.append(sub)
            if process_extra:
                extra_pairs = _pd.concat([extra_pairs] + process_extra, ignore_index=True)
            metric_plots.extend(tsd._plot_extra_pairs(extra_pairs, OUT_ROOT))

        manifest = {
            "artifact_type": "three_season_diagnostics_joint_genetic_soiln",
            "source_calibration": str(JOINT_RUN),
            "best_member": BEST_MEMBER,
            "parameter_csv": str(params),
            "parameter_count_exported": n_params,
            "ic_parameters": ic_count,
            "custom_dssat_executable": str(tsd.CUSTOM_EXE.resolve()),
            "custom_spe": str(tsd.CUSTOM_SPE.resolve()),
            "seasons": tsd.SEASONS,
            "deterministic_run": str(DET_ROOT),
            "output_root": str(OUT_ROOT),
            "metric_plots": [p.name for p in metric_plots],
            "figures": sorted(str(p.relative_to(OUT_ROOT)) for p in OUT_ROOT.rglob("*.png")),
            "metrics_csv": str((DET_ROOT / "metrics_by_season_variable.csv").resolve()),
            "organ_n_pairs_csv": str((DET_ROOT / "organ_n_compare.csv").resolve()),
            "note": "IC SNH4/SNO3 from joint inversion injected into 25SP+26SP FileX; 25FA uses default layermean IC.",
        }
        (OUT_ROOT / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nbest_member={BEST_MEMBER}; exported_parameters={n_params}; ic_params={ic_count}")
        print(metrics.to_string(index=False))
        print(f"\nDiagnostics written to: {OUT_ROOT}")
        return 0
    finally:
        tsd._restore_filex(backup)


if __name__ == "__main__":
    sys.exit(main())
