"""End-to-end driver: a calibration batch -> best-member params -> deterministic
simulation -> compare CSVs -> dynamics diagnostic plots.

Outputs go to ``figures/diagnostics/<batch_name>/`` (NOT under ``workspace/runs/``),
one subdirectory per calibration batch, named after the batch run. These are
Python **run-diagnostics** only (``timeseries_*``/``scatter_*``/``residual_*``/
``bar_*``); paper figures live in the separate R track.

Each batch entry maps a short ``--tag`` to:
  * the calibration run directory (``workspace/runs/<batch>``),
  * its ``runtime_multiseason_design.json`` (defines seasons, bundles, treatments,
    and any seasonal_parameterization / autumn offsets), and
  * the best member (read from ``best_member_metrics_rawscale/summary.txt``).

The best-member parameter row is taken from
``best_member_metrics_rawscale/best_member_parameters.csv`` (one wide data row,
columns = PEST-encoded names) and transposed to ``name,value`` (upper-cased).
``run_multiseason`` then applies any per-season offset projection itself.

Usage:
    python tools/calibration/run_dynamics_pipeline.py --tag softn_response
    python tools/calibration/run_dynamics_pipeline.py --tag springpair_wnresponse
    python tools/calibration/run_dynamics_pipeline.py --all
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIGURES_ROOT = ROOT / "figures" / "diagnostics"

# Canonical three-season definition: experiment code, bundle path, treatments.
# These are identical across every batch design (verified), so plotting can
# always run all three seasons regardless of which seasons a batch calibrated on.
CANONICAL_SEASONS = {
    "25SP": {"experiment_code": "XXQL2501",
             "bundle_path": "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
             "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
    "25FA": {"experiment_code": "XXQL2502",
             "bundle_path": "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
             "treatments": list(range(1, 13))},
    "26SP": {"experiment_code": "XXQL2601",
             "bundle_path": "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
             "treatments": list(range(1, 13))},
}
ALL_SEASONS = ["25SP", "25FA", "26SP"]

# season_id -> FileX path (relative) for legacy batch generation.
SEASONS = {s: (f"{v['bundle_path']}/{v['experiment_code']}.TMX", v["treatments"])
           for s, v in CANONICAL_SEASONS.items()}

# tag -> calibration run dir name. The deterministic det dir is derived per run.
BATCHES = {
    "softn_response": "e02_joint62_softn_response_95pct_dmc5_formal_200x5_20260802",
    "springpair_wnresponse": "e02_springpair_wnresponse_100x4_20260802",
    "25fa_temp12": "e02_25fa_temp12_100x4_20260802",
    "posterior_soil_wnresponse": "e02_joint62_posterior_soil_wnresponse_200x5_20260802",
    "posterior_soil_no_pdap_chtd_nresponse": "e02_joint62_posterior_soil_no_pdap_chtd_nresponse_100x4_20260802",
    "posterior_soil": "e02_joint62_posterior_soil_100x4_20260802",
}


def _run(cmd, cwd=ROOT):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=str(cwd), check=True)


def _best_member_index(calib_dir: Path) -> int:
    summary = calib_dir / "best_member_metrics_rawscale" / "summary.txt"
    if not summary.is_file():
        raise SystemExit(f"no best_member summary in {calib_dir}")
    for line in summary.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("best_member"):
            return int(line.split("=")[1].strip())
    raise SystemExit(f"could not parse best_member from {summary}")


def _extract_best_member_param_csv(calib_dir: Path, out_csv: Path) -> int:
    """Transpose the best-member row of ``best_member_parameters.csv`` to a
    ``name,value`` CSV (PEST-encoded names, upper-cased). Returns the member idx.
    """
    src = calib_dir / "best_member_metrics_rawscale" / "best_member_parameters.csv"
    if not src.is_file():
        raise SystemExit(f"no best_member_parameters.csv in {calib_dir}")
    par = pd.read_csv(src)
    member = _best_member_index(calib_dir)
    # The file holds exactly one best-member data row; verify its real_name.
    row = par.iloc[0]
    real_name = int(float(row["real_name"]))
    if real_name != member:
        print(f"[warn] best_member_parameters real_name={real_name} != summary member={member}; using file row")
    cols = [c for c in par.columns if c not in ("real_name", "atop")]
    out = pd.DataFrame({"name": [c.upper() for c in cols], "value": [row[c] for c in cols]})
    out.to_csv(out_csv, index=False)
    print(f"[extract] member {member} -> {out_csv} ({len(out)} params)")
    return member


def _write_legacy_batches(det_root: Path, seasons):
    bs = chr(92)
    for s in seasons:
        tmx_rel, tns = SEASONS[s]
        tmx_abs = str((ROOT / tmx_rel).resolve()).replace(bs, "/")
        rows = [f"{tmx_abs} {tn} 1 0 0 0" for tn in tns]
        (det_root / f"{s}_legacy_batch.v48").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _gen_compare_csvs(det_root: Path, seasons):
    analyze = ROOT / "src" / "reporting" / "analyze_results.py"
    for s in seasons:
        season_dir = det_root / "_seasons" / s
        if not season_dir.is_dir():
            continue
        batch = det_root / f"{s}_legacy_batch.v48"
        for flag in ("--deterministic-harvest-compare", "--deterministic-process-compare"):
            _run([sys.executable, str(analyze), flag,
                  "--prefix", s, "--run-dir", season_dir, "--batch", batch],
                 cwd=ROOT)


def _build_three_season_design(src_design: Path, dest: Path, seasons):
    """Synthesize a design JSON covering the requested seasons.

    Uses the canonical bundle/treatment definition (identical across batches) for
    any season missing from the source design, while preserving the source
    ``seasonal_parameterization`` (autumn offsets are applied by run_multiseason
    only where the offset names exist; seasons absent from a design still run
    with the shared parameters). This lets every batch be plotted across all
    three seasons regardless of which seasons it calibrated on.
    """
    import json
    d = json.loads(src_design.read_text(encoding="utf-8"))
    present = {s["season_id"]: s for s in d.get("seasons", [])}
    new_seasons = []
    for sid in seasons:
        if sid in present:
            new_seasons.append(present[sid])
        else:
            cs = CANONICAL_SEASONS[sid]
            new_seasons.append({
                "season_id": sid, "experiment_code": cs["experiment_code"],
                "bundle_path": cs["bundle_path"], "role": "calibration",
                "treatments": cs["treatments"],
            })
    d["seasons"] = new_seasons
    # A single-season diagnostic design enforces exactly one calibration season;
    # when we widen it to all three for plotting we must lift that constraint.
    if d.pop("diagnostic_single_season", None):
        d["design_id"] = d.get("design_id", "") + "_3season_for_plotting"
    dest.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def process_batch(tag: str, seasons=None) -> Path:
    """Run the full pipeline for one batch tag; return the figures output dir.

    ``seasons`` (default all three) controls both the deterministic simulation
    and the figures. The design is synthesized to cover the requested seasons so
    a single-season or two-season batch can still be plotted across all three.
    """
    if tag not in BATCHES:
        raise SystemExit(f"unknown tag '{tag}'. Known: {', '.join(BATCHES)}")
    if seasons is None:
        seasons = list(ALL_SEASONS)
    batch_name = BATCHES[tag]
    calib_dir = ROOT / "workspace" / "runs" / batch_name
    if not calib_dir.is_dir():
        raise SystemExit(f"calibration run dir not found: {calib_dir}")
    design = calib_dir / "runtime_multiseason_design.json"
    if not design.is_file():
        raise SystemExit(f"design JSON not found: {design}")

    # det dir kept under workspace/runs (transient sim artifacts); figures go to figures/.
    det_root = ROOT / "workspace" / "runs" / f"{batch_name}_det"
    det_root.mkdir(parents=True, exist_ok=True)
    _build_three_season_design(design, det_root / "design.json", seasons)

    param_csv = det_root / "best_member_params.csv"
    _extract_best_member_param_csv(calib_dir, param_csv)

    # 1) deterministic simulation (cwd = det_root so _seasons/ lands there;
    #    script paths are absolute so they resolve regardless of cwd).
    _run([sys.executable, str(ROOT / "src" / "calibration" / "run_multiseason.py"),
          "--design", det_root / "design.json",
          "--param-csv", param_csv, "--prefix", tag, "--harvest-var", "CHPDT"],
         cwd=det_root)

    # 2) compare CSVs
    _write_legacy_batches(det_root, seasons)
    _gen_compare_csvs(det_root, seasons)

    # 3) stage observation registry for SE error bars
    reg = calib_dir / f"{batch_name}_observation_registry.csv"
    if reg.is_file():
        (det_root / "observation_registry.csv").write_bytes(reg.read_bytes())

    # 4) render diagnostics -> figures/diagnostics/<batch_name>/<season>/
    out_dir = FIGURES_ROOT / batch_name
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, str(ROOT / "tools" / "calibration" / "plot_dynamics.py"),
          "--det-root", det_root, "--out-root", out_dir, "--seasons", ",".join(seasons)])
    print(f"\n[done] {tag} -> {out_dir}")
    return out_dir


def main() -> int:
    args = sys.argv[1:]
    # Optional --seasons 25SP,25FA,26SP  (default: all three)
    seasons = list(ALL_SEASONS)
    if "--seasons" in args:
        raw = args[args.index("--seasons") + 1]
        seasons = [s.strip() for s in raw.split(",") if s.strip()]
        bad = [s for s in seasons if s not in ALL_SEASONS]
        if bad:
            raise SystemExit(f"unknown season(s) {bad}; valid: {ALL_SEASONS}")
    if "--all" in args:
        for tag in BATCHES:
            print(f"\n========== {tag} ==========")
            process_batch(tag, seasons)
        return 0
    if "--tag" in args:
        process_batch(args[args.index("--tag") + 1], seasons)
        return 0
    print(__doc__)
    print(f"Known tags: {', '.join(BATCHES)}")
    print("Seasons (default all): {', '.join(ALL_SEASONS)}; override with --seasons 25SP,26SP")
    print("Use --tag <name> or --all")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
