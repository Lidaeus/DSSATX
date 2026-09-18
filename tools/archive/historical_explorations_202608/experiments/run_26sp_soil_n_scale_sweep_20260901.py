"""Deterministic 26SP initial-mineral-N scale sweep for the Dias-2026 anchor.

The genetic/soil parameter vector is copied from the Dias-2026 double-N
champion.  Only SNH4/SNO3 in the 0--60 cm layers of XXQL2601.TMX are changed;
the three Excel strata (0--20, 20--40, 40--60 cm) are mapped to DSSAT depths
2/4/15, 30/40, and 60 cm respectively.  Deeper layers and every other input
file remain byte-for-byte copies of the double-N bundle.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE_BUNDLE = ROOT / "data/user/experiments/xxql2601_scheme4_double_n_20260831"
SOURCE_BUNDLE_25 = ROOT / "data/user/experiments/xxql2501_scheme4_double_n_20260831"
CHAMPION = ROOT / "workspace/runs/e02_formal_v46_dias2026_double_n_20260831/best_member_1_deterministic_20260831/best_member_1_params.csv"
XLSX = next((ROOT / "data/user/ref").glob("*26SP*校准值.xlsx"))
OUT = ROOT / "workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901"
BUNDLE_ROOT = OUT / "bundles_v2"
BASE_CASE = ROOT / "workspace/runs/e02_formal_v46_dias2026_double_n_20260831"
MAPPING = ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv"

SCALES = [round(0.10 + 0.04 * i, 2) for i in range(21)]
DEPTH_TO_STRATUM = {2: "0-20", 4: "0-20", 15: "0-20", 30: "20-40", 40: "20-40", 60: "40-60"}


def read_excel_means() -> dict[tuple[int, str], tuple[float, float]]:
    frame = pd.read_excel(XLSX)
    frame = frame.rename(columns={c: str(c).strip() for c in frame.columns})
    trt_col = next(c for c in frame.columns if c.startswith("小区"))
    layer_col = next(c for c in frame.columns if c == "土层")
    no3_cols = [c for c in frame.columns if "硝态氮纯氮" in c]
    nh4_cols = [c for c in frame.columns if "铵态氮" in c]
    out: dict[tuple[int, str], tuple[float, float]] = {}
    for (trt, layer), g in frame.groupby([trt_col, layer_col], sort=False):
        t = int(trt)
        layer = str(layer).replace(" ", "")
        no3 = float(g[no3_cols].to_numpy(dtype=float).mean())
        nh4 = float(g[nh4_cols].to_numpy(dtype=float).mean())
        out[(t, layer)] = (nh4, no3)
    expected = {(t, s) for t in range(1, 13) for s in ("0-20", "20-40", "40-60")}
    missing = sorted(expected - set(out))
    if missing:
        raise ValueError(f"missing Excel strata: {missing}")
    return out


def rewrite_tmx(src: Path, dst: Path, scale: float, means: dict[tuple[int, str], tuple[float, float]]) -> None:
    lines = src.read_text(encoding="utf-8-sig").splitlines()
    in_ic = False
    in_ic_data = False
    current_tn: int | None = None
    out: list[str] = []
    changed: list[dict[str, object]] = []
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_ic = True
            in_ic_data = False
            current_tn = None
            out.append(line)
            continue
        if in_ic and stripped.startswith("*"):
            in_ic = False
            in_ic_data = False
            current_tn = None
        if in_ic and upper.startswith("@C"):
            in_ic_data = "ICBL" in upper and "SNH4" in upper and "SNO3" in upper
            out.append(line)
            continue
        if in_ic:
            m = re.match(r"^\s*(\d+)\s+TM\s+", line)
            if m:
                current_tn = int(m.group(1))
                in_ic_data = False
                out.append(line)
                continue
        if in_ic and in_ic_data:
            fields = stripped.split()
            if current_tn is not None and len(fields) >= 5:
                try:
                    depth = int(fields[1])
                    float(fields[2]); float(fields[3]); float(fields[4])
                except ValueError:
                    out.append(line)
                    continue
                if depth in DEPTH_TO_STRATUM:
                    nh4_0, no3_0 = means[(current_tn, DEPTH_TO_STRATUM[depth])]
                    nh4, no3 = scale * nh4_0, scale * no3_0
                    # Keep DSSAT's leading treatment/depth fields explicit and
                    # preserve the SH2O value; mineral-N fields are two decimals.
                    # TMX initial-condition columns are fixed-width.  Keep the
                    # original starts (SH2O col 10, SNH4 col 17, SNO3 col 23);
                    # widening these fields shifts the parser and produces the
                    # misleading IPSLIN/initial-N failure.
                    new_line = f"{current_tn:2d}{depth:6d}{float(fields[2]):6.3f}{nh4:6.2f}{no3:6.1f}"
                    out.append(new_line)
                    changed.append({"treatment": current_tn, "depth_cm": depth, "stratum": DEPTH_TO_STRATUM[depth], "nh4": nh4, "no3": no3})
                    continue
        out.append(line)
    if len(changed) != 12 * 6:
        raise ValueError(f"expected 72 changed 0-60 cm rows, got {len(changed)}")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    (dst.parent / "soil_n_scale_rows.json").write_text(json.dumps(changed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_bundle(scale: float, means: dict[tuple[int, str], tuple[float, float]]) -> Path:
    label = f"s{scale:.2f}".replace(".", "p")
    target = BUNDLE_ROOT / label
    if target.exists():
        tmx = target / "XXQL2601.TMX"
        if not (target / "soil_n_scale_manifest.json").is_file():
            raise RuntimeError(f"refusing to reuse unverified bundle: {target}")
        return target
    shutil.copytree(SOURCE_BUNDLE, target)
    rewrite_tmx(SOURCE_BUNDLE / "XXQL2601.TMX", target / "XXQL2601.TMX", scale, means)
    manifest = {"format_version": 2, "source_bundle": str(SOURCE_BUNDLE.resolve()), "scale": scale, "xlsx": str(XLSX.resolve()), "scope": "SNH4/SNO3 only, DSSAT depths <=60 cm", "deeper_layers_unchanged": True}
    (target / "soil_n_scale_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def run_one(mod, scale: float, bundle: Path, param_csv: Path) -> dict[str, object]:
    label = f"s{scale:.2f}".replace(".", "p")
    case = f"e02_v46_dias2026_26sp_soiln_{label}_20260901"
    det = OUT / "deterministic_v2" / label
    det.mkdir(parents=True, exist_ok=True)
    mod.CASE = case
    mod.RUN_DIR = BASE_CASE
    mod.BEST_MEMBER = "1"
    mod.SOURCE_ITERATION = 1
    mod.BEST_PHI = 491.6
    mod.OBS_REGISTRY = BASE_CASE / "e02_formal_v46_dias2026_double_n_20260831_observation_registry.csv"
    mod.EXE = ROOT / "DSCSM048.EXE"
    mod.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    mod.GENOTYPE_DIR = ROOT / "data/templates/genotype"
    mod.DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
    mod.DET_ROOT = det
    mod.OUT_ROOT = OUT / "diagnostics_v2" / label
    # run_multiseason requires at least two seasons; 25SP is an unchanged
    # control season and is retained only to satisfy that contract.
    mod.SEASONS = [
        {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "bundle": SOURCE_BUNDLE_25},
        {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1, 13)), "bundle": bundle},
    ]
    mod.SEASON_IDS = ["25SP", "26SP"]

    def export(_out: Path) -> int:
        shutil.copy2(param_csv, _out)
        return len(pd.read_csv(param_csv))
    mod._export_member = export
    params = det / "best_member_1_params.csv"
    mod._export_member(params)
    design = mod._write_design(det)
    status = det / "multiseason_run_status.json"
    if not status.is_file():
        import os
        os.environ["DSSAT_SPE_BASE"] = str(mod.SPE.resolve())
        replacements = mod._swap()
        try:
            mod._run([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(design), "--param-csv", str(params), "--prefix", f"best1_det_{label}", "--harvest-var", "CHPDT", "--keep-nitrogen-outputs"], det)
        finally:
            mod._restore(replacements)
    mod._run_comparisons(det)
    organ = mod._organ_n_pairs(det)
    metrics = mod._metric_rows(det)
    mpath = det / "metrics_by_season_variable.csv"
    metrics.to_csv(mpath, index=False)
    # Response-structure audit reuses the canonical renderer's definitions.
    plot = __import__("tools.calibration.plot_dynamics", fromlist=["_load_season", "_response_structure_audit"])
    plot.MAPPING_CSV = str(MAPPING.resolve())
    plot._INCLUDE_ALL_TREATMENTS = True
    loaded = plot._load_season(str(det / "_seasons" / "26SP"), "26SP")
    all_proc = {"26SP": {**loaded, "compare": loaded["compare_proc"]}}
    all_harv = {"26SP": {**loaded, "compare": loaded["compare_harv"]}}
    diag = mod.OUT_ROOT
    diag.mkdir(parents=True, exist_ok=True)
    plot._response_structure_audit(all_proc, all_harv, str(diag / "response_structure_audit.png"), str(diag / "response_structure_audit.csv"))
    rows = {"scale": scale, "label": label, "run_dir": str(det), "metrics_csv": str(mpath)}
    for _, r in metrics[metrics["season"].eq("26SP")].iterrows():
        key = str(r["variable"]).lower()
        rows[f"{key}_rrmse_pct"] = float(r["rrmse_pct"])
        rows[f"{key}_nse"] = float(r["nse"])
        rows[f"{key}_bias"] = float(r["bias"])
    audit = pd.read_csv(diag / "response_structure_audit.csv")
    for _, r in audit.iterrows():
        rows[f"response_{str(r['response']).lower()}_spread_ratio"] = float(r["spread_ratio_sim_over_obs"])
        rows[f"response_{str(r['response']).lower()}_bias"] = float(r["mean_bias_sim_minus_obs"])
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    means = read_excel_means()
    shutil.copy2(CHAMPION, OUT / "anchor_best_member_1_params.csv")
    (OUT / "scale_grid.csv").write_text("scale\n" + "\n".join(f"{x:.2f}" for x in SCALES) + "\n", encoding="utf-8")
    bundles = {scale: make_bundle(scale, means) for scale in SCALES}
    sys.path.insert(0, str(ROOT))
    import importlib
    mod = importlib.import_module("tools.calibration.evaluate_fixedsoil_official_best189_20260813")
    results = []
    failures = []
    for i, scale in enumerate(SCALES, start=1):
        print(f"[sweep] {i}/{len(SCALES)} scale={scale:.2f}", flush=True)
        try:
            results.append(run_one(mod, scale, bundles[scale], CHAMPION))
        except Exception as exc:
            # Keep the grid auditable and continue; a native DSSAT input/run
            # failure at one scale must not hide the remaining profile.
            failures.append({"scale": scale, "error": repr(exc)})
            print(f"[sweep] FAILED scale={scale:.2f}: {exc}", flush=True)
        pd.DataFrame(results).sort_values("scale").to_csv(OUT / "scale_metrics.csv", index=False)
        (OUT / "scale_failures.json").write_text(json.dumps(failures, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result = pd.DataFrame(results).sort_values("scale")
    # Transparent composite: mean rank of key state/yield errors, with LAI and
    # fresh cumulative yield receiving equal weight; response ratios are shown
    # separately and never hidden in the ranking.
    rank_cols = [c for c in ["laid_rrmse_pct", "lwad_rrmse_pct", "swad_rrmse_pct", "fresh_cum_rrmse_pct", "dry_cum_rrmse_pct"] if c in result]
    result["rank_mean_rrmse"] = result[rank_cols].rank(method="min").mean(axis=1)
    result["rank_mean_nse"] = result[[c for c in result.columns if c.endswith("_nse")]].rank(ascending=False, method="min").mean(axis=1)
    result["composite_rank"] = (result["rank_mean_rrmse"] + result["rank_mean_nse"]).rank(method="min")
    result.to_csv(OUT / "scale_metrics_ranked.csv", index=False)
    # Plot the scale response for the primary metrics.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), dpi=180)
    for col, title, ax in [("laid_nse", "26SP LAI NSE", axes[0]), ("lwad_nse", "26SP LWAD NSE", axes[1]), ("fresh_cum_rrmse_pct", "26SP fresh cumulative RRMSE (%)", axes[2])]:
        if col in result:
            ax.plot(result["scale"], result[col], marker="o", lw=1.3)
            ax.set_xlabel("Initial SNH4/SNO3 scale")
            ax.set_ylabel(title)
            ax.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(OUT / "scale_metric_profiles.png", bbox_inches="tight"); plt.close(fig)
    print(result[["scale", "composite_rank"] + [c for c in rank_cols if c in result]].to_string(index=False))


if __name__ == "__main__":
    main()
