"""Three-season diagnostics for best member #139 of batch B (0806).

Uses the nresp exe + #139 parameters on the DMFR-corrected three-season
layermean_ic_valid bundles (XXQL2501/2502/2601), then renders the full
diagnostic figure set into figture/.

Usage:
    python tools/calibration/three_season_diagnostics_batchB_0806.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/calibration"))

# Import the canonical three-season diagnostics module so we reuse its
# _best_member / _export_member / _write_design / _set_env / _run_comparisons /
# _metric_rows / _plot_metrics / _plot_extra_pairs / main helpers.
import run_best_member_three_season_custom_diagnostics_20260804 as tsd

# Override the module-level SEASONS to point at the DMFR-corrected
# layermean_ic_valid bundles (the same bundles the rebuild scripts use).
tsd.SEASONS = [
    {
        "season_id": "25SP",
        "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    {
        "season_id": "25FA",
        "experiment_code": "XXQL2502",
        "bundle_path": "data/user/experiments/xxql2502_layermean_ic_valid_n012_v1_20260801",
        "treatments": list(range(1, 13)),
    },
    {
        "season_id": "26SP",
        "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/xxql2601_layermean_ic_valid_n012_v1_20260801",
        "treatments": list(range(1, 13)),
    },
]

BATCH_B_RUN = ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806"
BATCH_B_CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806"
BEST_MEMBER = "139"  # min-Phi realization of batch B
DET_ROOT = ROOT / f"workspace/runs/{BATCH_B_CASE}_best{BEST_MEMBER}_three_season_dmfrfix_20260808"
OUT_ROOT = ROOT / "figture/batchB_three_season_20260808"


def main() -> int:
    DET_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    print(f"batch B best member = #{BEST_MEMBER}")
    print(f"three-season bundles (DMFR-corrected layermean_ic_valid):")
    for s in tsd.SEASONS:
        print(f"  {s['season_id']}  {s['experiment_code']}  TN={s['treatments']}")
        print(f"    bundle: {s['bundle_path']}")

    # Export the best member parameters
    params = DET_ROOT / f"best_member_{BEST_MEMBER}_params.csv"
    n_params = tsd._export_member(BATCH_B_RUN, BATCH_B_CASE, BEST_MEMBER, params)
    print(f"exported {n_params} parameters -> {params}")

    # Write the three-season design json (uses overridden SEASONS + nresp exe/SPE)
    design = tsd._write_design(DET_ROOT, BATCH_B_CASE, BEST_MEMBER)
    print(f"design: {design}")

    tsd._set_env()

    # Backup C:\DSSAT48\TOMATO FileX, run, restore
    backup = tsd._backup_filex(DET_ROOT)
    try:
        status = DET_ROOT / "multiseason_run_status.json"
        if not status.is_file():
            tsd._run([
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design), "--param-csv", str(params),
                "--prefix", f"best{BEST_MEMBER}_three_season_dmfrfix",
                "--harvest-var", "CHPDT", "--keep-nitrogen-outputs",
            ], DET_ROOT)
        tsd._run_comparisons(DET_ROOT)
        tsd._organ_n_pairs(DET_ROOT)
        metrics = tsd._metric_rows(DET_ROOT)
        # Delegate the canonical dynamics renderer
        plotter = ROOT / "tools/calibration/plot_dynamics.py"
        tsd._run([
            sys.executable, str(plotter),
            "--det-root", str(DET_ROOT),
            "--out-root", str(OUT_ROOT),
            "--seasons", "25SP,25FA,26SP",
        ], ROOT)
        metric_plots = tsd._plot_metrics(metrics, OUT_ROOT)
        extra = DET_ROOT / "organ_n_compare.csv"
        import pandas as _pd
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
            "artifact_type": "three_season_diagnostics_batchB_0806",
            "source_calibration": str(BATCH_B_RUN),
            "best_member": BEST_MEMBER,
            "parameter_csv": str(params),
            "parameter_count_exported": n_params,
            "custom_dssat_executable": str(tsd.CUSTOM_EXE.resolve()),
            "custom_spe": str(tsd.CUSTOM_SPE.resolve()),
            "seasons": tsd.SEASONS,
            "deterministic_run": str(DET_ROOT),
            "output_root": str(OUT_ROOT),
            "metric_plots": [p.name for p in metric_plots],
            "figures": sorted(str(p.relative_to(OUT_ROOT)) for p in OUT_ROOT.rglob("*.png")),
            "metrics_csv": str((DET_ROOT / "metrics_by_season_variable.csv").resolve()),
            "organ_n_pairs_csv": str((DET_ROOT / "organ_n_compare.csv").resolve()),
            "bundle_note": "DMFR-corrected layermean_ic_valid_n012_v1_20260801 bundles (TN13 DMFR 9.31%->3.21%)",
            "limitations": [
                "Python run-diagnostics product, not a publication Fig/FigS bundle.",
                "W×N dynamics renderer excludes unmapped 25SP TN9/TN14 from factorial panels; all observations remain in metric CSVs.",
            ],
        }
        (OUT_ROOT / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nbest_member={BEST_MEMBER}; exported_parameters={n_params}")
        print(metrics.to_string(index=False))
        print(f"\nDiagnostics written to: {OUT_ROOT}")
        return 0
    finally:
        tsd._restore_filex(backup)


if __name__ == "__main__":
    sys.exit(main())
