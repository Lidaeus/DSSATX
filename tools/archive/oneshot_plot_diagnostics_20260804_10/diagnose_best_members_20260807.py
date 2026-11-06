"""Deterministic best-member diagnostics for batches A and B.

Exports each batch's best member (min-Phi realization), runs it through DSSAT
with the custom N-response executable, computes fit metrics (RMSE/NRMSE/NSE/
d-index/R²) for all observed variables, and renders the full diagnostic figure
set (scatter / residual / timeseries / metrics heatmaps) to figture/.

Usage (from D:\\Tomato_Cal):
    python tools/calibration/diagnose_best_members_20260807.py

Outputs:
    figture/batchA_nresp_sw_onethird/   — batch A diagnostics
    figture/batchB_rawdiff_terminal/    — batch B diagnostics
    figture/comparison/                 — side-by-side comparison charts
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)

# ── Batch definitions ────────────────────────────────────────────────────────
BATCH_A = {
    "label": "batchA_nresp_sw_onethird",
    "title": "批次A 降权1/3 (旧方案)",
    "run_dir": ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260806_nresp_sw_onethird_20260806",
    "case": "e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260806_nresp_sw_onethird_20260806",
}
BATCH_B = {
    "label": "batchB_rawdiff_terminal",
    "title": "批次B 新方案 (rawdiff_terminal)",
    "run_dir": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806",
    "case": "e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806",
}
BATCHES = [BATCH_A, BATCH_B]

CUSTOM_EXE = ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"
CUSTOM_SPE = ROOT / "windows/windows_nresp_20260803/Genotype/TMGRO048.SPE"
DSSAT_TOMATO = Path(r"C:\DSSAT48\TOMATO")
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
TREATMENTS = [13, 12, 11, 5, 4, 3]
SEASON_ID = "25SP"
EXPERIMENT = "XXQL2501"
FIGTURE = ROOT / "figture"


# ── Helpers ──────────────────────────────────────────────────────────────────
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _best_member(run_dir: Path, case: str) -> str:
    """Find the min-Phi realization from the final iteration."""
    pg = pd.read_csv(run_dir / f"{case}.phi.group.csv")
    max_iter = pg["iteration"].max()
    final = pg[pg["iteration"] == max_iter].copy()
    meta = {"iteration", "total_runs", "obs_realization", "par_realization"}
    gcols = [c for c in pg.columns if c not in meta]
    for c in gcols:
        final[c] = pd.to_numeric(final[c], errors="coerce")
    final["_total"] = final[gcols].sum(axis=1)
    best_idx = final["_total"].idxmin()
    return str(int(float(final.loc[best_idx, "par_realization"])))


def _export_member(run_dir: Path, case: str, member: str, out_csv: Path) -> int:
    source = run_dir / f"{case}.4.par.csv"
    frame = pd.read_csv(source)
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    if real_col is None:
        raise ValueError(f"{source} has no realization column")
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(member))
    if int(mask.sum()) != 1:
        raise ValueError(f"best member {member} occurs {int(mask.sum())} times in {source}")
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        v = float(row[col])
        if not math.isfinite(v):
            raise ValueError(f"best member {member}: non-finite {col}={v}")
        records.append({"name": str(col).upper(), "value": v})
    pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def _write_design(out_dir: Path, case: str, member: str) -> Path:
    payload = {
        "schema_version": 1,
        "design_id": f"{case}_best{member}_deterministic_20260807",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "deterministic best-member replay",
        "observation_policy": "configs/runs/e02_v2_canopy_yield_nresponse_policy_20260802.csv",
        "group_policy": "configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv",
        "purpose": "deterministic diagnostics only; no re-calibration",
        "diagnostic_single_season": True,
        "custom_dssat_executable": str(CUSTOM_EXE.resolve()),
        "custom_spe": str(CUSTOM_SPE.resolve()),
        "seasonal_parameterization": None,
        "seasons": [{
            "season_id": SEASON_ID,
            "experiment_code": EXPERIMENT,
            "bundle_path": str(BUNDLE),
            "bundle_manifest_sha256": _sha256(BUNDLE / "input_manifest.json"),
            "role": "calibration",
            "treatments": TREATMENTS,
        }],
    }
    path = out_dir / "design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _set_env() -> None:
    os.environ["DSSAT_CUSTOM_EXE"] = str(CUSTOM_EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE.resolve())
    os.environ["DSSAT_SOIL_BASE"] = str((BUNDLE / "SOIL.SOL").resolve())
    os.environ["DSSAT_BATCH_FILEX_ROOT"] = str(DSSAT_TOMATO)
    os.environ["DSSAT_KEEP_RUNS"] = "1"
    os.environ["DSSAT_DISABLE_SOIL_INJECTION"] = "1"
    os.environ["DSSAT_FILEX_MAP"] = json.dumps({
        f"{EXPERIMENT}.TMX": str((BUNDLE / f"{EXPERIMENT}.TMX").resolve())
    })


def _backup_filex(out_dir: Path) -> Path:
    backup = out_dir / "dssat_tomato_backup"
    backup.mkdir(parents=True, exist_ok=True)
    src = DSSAT_TOMATO / f"{EXPERIMENT}.TMX"
    if src.is_file():
        shutil.copy2(src, backup / f"{EXPERIMENT}.TMX")
    return backup


def _restore_filex(backup: Path) -> None:
    DSSAT_TOMATO.mkdir(parents=True, exist_ok=True)
    src = backup / f"{EXPERIMENT}.TMX"
    tgt = DSSAT_TOMATO / f"{EXPERIMENT}.TMX"
    if src.is_file():
        shutil.copy2(src, tgt)
    elif tgt.is_file():
        tgt.unlink()


def _run(cmd: list, cwd: Path) -> None:
    print("+ " + subprocess.list2cmdline([str(x) for x in cmd]), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _compute_metrics(det_root: Path) -> pd.DataFrame:
    """Compute RMSE/NRMSE/NSE/d-index/R² for all observed variables."""
    season_dir = det_root / "_seasons" / SEASON_ID
    filex = next(season_dir.glob("*.TMX"))
    batch = season_dir / "analysis_batch.v48"
    batch.write_text(
        "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in TREATMENTS) + "\n",
        encoding="utf-8",
    )
    deterministic_process_compare(
        SEASON_ID, str(batch),
        var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"],
        run_dir=str(season_dir),
    )
    deterministic_harvest_compare(SEASON_ID, str(batch), run_dir=str(season_dir))

    rows = []
    for kind, fname in (("process", f"{SEASON_ID}_deterministic_process_compare.csv"),
                        ("harvest", f"{SEASON_ID}_deterministic_harvest_compare.csv")):
        path = season_dir / fname
        if not path.is_file() or path.stat().st_size <= 2:
            continue
        frame = pd.read_csv(path)
        for col in frame.columns:
            if not str(col).startswith("OBS_"):
                continue
            var = str(col)[4:]
            sim_col = f"SIM_{var}"
            if sim_col not in frame:
                continue
            obs = pd.to_numeric(frame[col], errors="coerce")
            sim = pd.to_numeric(frame[sim_col], errors="coerce")
            ok = obs.notna() & sim.notna() & (obs != -99) & (sim != -99)
            if not bool(ok.any()):
                continue
            y = obs.loc[ok].to_numpy(float)
            p = sim.loc[ok].to_numpy(float)
            e = p - y
            den = float(np.sum((y - y.mean()) ** 2))
            dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
            rows.append({
                "kind": kind, "variable": var, "n": int(ok.sum()),
                "rmse": float(np.sqrt(np.mean(e ** 2))),
                "rrmse_pct": float(100 * np.sqrt(np.mean(e ** 2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
                "mae": float(np.mean(np.abs(e))), "bias": float(e.mean()),
                "nse": float(1 - np.sum(e ** 2) / den) if den > 0 else np.nan,
                "d_index": float(1 - np.sum(e ** 2) / dden) if dden > 0 else np.nan,
                "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
            })
    result = pd.DataFrame(rows)
    result.to_csv(det_root / "metrics.csv", index=False)
    return result


def _plot_scatter_residual(metrics_pairs: dict, out_root: Path, batch_titles: dict) -> list[Path]:
    """Side-by-side scatter + residual plots comparing the two batches."""
    outputs = []
    vars_all = set()
    for label, det_root in metrics_pairs.items():
        season_dir = det_root / "_seasons" / SEASON_ID
        for fname in (f"{SEASON_ID}_deterministic_process_compare.csv",
                      f"{SEASON_ID}_deterministic_harvest_compare.csv"):
            path = season_dir / fname
            if not path.is_file():
                continue
            frame = pd.read_csv(path)
            for col in frame.columns:
                if str(col).startswith("OBS_"):
                    vars_all.add(str(col)[4:])

    colors = {"batchA_nresp_sw_onethird": "#2878B5", "batchB_rawdiff_terminal": "#D95F02"}
    for var in sorted(vars_all):
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), dpi=180)
        for ax, (label, det_root) in zip(axes, metrics_pairs.items()):
            season_dir = det_root / "_seasons" / SEASON_ID
            pairs = None
            for fname in (f"{SEASON_ID}_deterministic_process_compare.csv",
                          f"{SEASON_ID}_deterministic_harvest_compare.csv"):
                path = season_dir / fname
                if not path.is_file():
                    continue
                frame = pd.read_csv(path)
                obs_c, sim_c = f"OBS_{var}", f"SIM_{var}"
                if obs_c in frame and sim_c in frame:
                    sub = frame[[obs_c, sim_c]].copy()
                    sub.columns = ["observed", "simulated"]
                    sub = sub[(sub["observed"] != -99) & (sub["simulated"] != -99)].dropna()
                    pairs = sub
                    break
            if pairs is None or pairs.empty:
                ax.set_visible(False)
                continue
            y = pairs["observed"].to_numpy(float)
            p = pairs["simulated"].to_numpy(float)
            e = p - y
            lo = float(min(y.min(), p.min()))
            hi = float(max(y.max(), p.max()))
            pad = max((hi - lo) * 0.06, 1e-6)
            ax.scatter(y, p, color=colors.get(label, "#555"), s=36, alpha=0.8, edgecolor="white", linewidth=0.3)
            ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
            ax.set_title(batch_titles.get(label, label), fontsize=9)
            ax.set_xlim(lo - pad, hi + pad)
            ax.set_ylim(lo - pad, hi + pad)
            ax.set_xlabel("Observed")
            ax.set_ylabel("Simulated")
            rmse = float(np.sqrt(np.mean(e ** 2)))
            ax.text(0.04, 0.96, f"n={len(pairs)}\nRMSE={rmse:.3g}\nBias={e.mean():+.3g}",
                    transform=ax.transAxes, va="top", fontsize=8, family="monospace",
                    bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"})
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{var}: observed vs simulated", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        path = out_root / f"scatter_{var}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)

        # Residual plot
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), dpi=180)
        for ax, (label, det_root) in zip(axes, metrics_pairs.items()):
            season_dir = det_root / "_seasons" / SEASON_ID
            pairs = None
            for fname in (f"{SEASON_ID}_deterministic_process_compare.csv",
                          f"{SEASON_ID}_deterministic_harvest_compare.csv"):
                path = season_dir / fname
                if not path.is_file():
                    continue
                frame = pd.read_csv(path)
                obs_c, sim_c = f"OBS_{var}", f"SIM_{var}"
                if obs_c in frame and sim_c in frame:
                    sub = frame[[obs_c, sim_c]].copy()
                    sub.columns = ["observed", "simulated"]
                    sub = sub[(sub["observed"] != -99) & (sub["simulated"] != -99)].dropna()
                    pairs = sub
                    break
            if pairs is None or pairs.empty:
                ax.set_visible(False)
                continue
            y = pairs["observed"].to_numpy(float)
            r = pairs["simulated"].to_numpy(float) - y
            rmax = max(float(np.nanmax(np.abs(r))), 1e-6)
            ax.scatter(y, r, color=colors.get(label, "#555"), s=36, alpha=0.8, edgecolor="white", linewidth=0.3)
            ax.axhline(0, ls="--", color="#555", lw=0.9)
            ax.set_title(batch_titles.get(label, label), fontsize=9)
            ax.set_xlabel("Observed")
            ax.set_ylabel("Simulated − observed")
            ax.set_ylim(-1.15 * rmax, 1.15 * rmax)
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{var}: residuals (simulated − observed)", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        path = out_root / f"residual_{var}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)
    return outputs


def _plot_metrics_comparison(all_metrics: dict, out_root: Path, batch_titles: dict) -> list[Path]:
    """Bar-chart comparison of RRMSE / NSE / R² / d-index across batches."""
    outputs = []
    var_order = [v for v in ["LAID", "LWAD", "SWAD", "DRY_CUM", "DRY_INC", "CHTD", "LAIX", "ADAP"] 
                 if any(v in m["variable"].values for m in all_metrics.values())]
    for label_df in all_metrics.values():
        for v in label_df["variable"]:
            if v not in var_order:
                var_order.append(v)

    colors = {"batchA_nresp_sw_onethird": "#2878B5", "batchB_rawdiff_terminal": "#D95F02"}
    for metric, ylabel in (("rrmse_pct", "RRMSE (%)"), ("nse", "NSE"), ("r2", "R²"), ("d_index", "d-index")):
        fig, ax = plt.subplots(figsize=(10, 5), dpi=180)
        x = np.arange(len(var_order))
        width = 0.35
        for j, (label, mdf) in enumerate(all_metrics.items()):
            vals = mdf.set_index("variable")[metric].reindex(var_order)
            ax.bar(x + (j - 0.5) * width, vals.to_numpy(float), width,
                   label=batch_titles.get(label, label), color=colors.get(label))
        ax.set_xticks(x, var_order, rotation=45, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(f"Best-member fit metric comparison: {ylabel}")
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        path = out_root / f"comparison_{metric}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)
    return outputs


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    FIGTURE.mkdir(parents=True, exist_ok=True)
    all_metrics = {}
    metrics_pairs = {}
    batch_titles = {}

    for batch in BATCHES:
        label = batch["label"]
        run_dir = batch["run_dir"]
        case = batch["case"]
        batch_titles[label] = batch["title"]

        print(f"\n{'='*70}")
        print(f"Processing {batch['title']} ({label})")
        print(f"{'='*70}")

        member = _best_member(run_dir, case)
        print(f"best member = real {member}")

        det_root = run_dir / f"best_member_{member}_deterministic_20260807"
        det_root.mkdir(parents=True, exist_ok=True)
        params = det_root / f"best_member_{member}_params.csv"
        n_params = _export_member(run_dir, case, member, params)
        print(f"exported {n_params} parameters")

        design = _write_design(det_root, case, member)
        _set_env()
        backup = _backup_filex(det_root)
        try:
            status = det_root / "multiseason_run_status.json"
            if not status.is_file():
                _run([
                    sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                    "--design", str(design), "--param-csv", str(params),
                    "--prefix", f"best{member}_det", "--harvest-var", "CHPDT",
                    "--keep-nitrogen-outputs",
                ], det_root)
            metrics = _compute_metrics(det_root)
            all_metrics[label] = metrics
            metrics_pairs[label] = det_root
            print(f"\nmetrics for {label}:")
            print(metrics.to_string(index=False))

            # Per-batch output folder
            out_dir = FIGTURE / label
            out_dir.mkdir(parents=True, exist_ok=True)
            # Delegate timeseries/dynamics plots to plot_dynamics.py
            plotter = ROOT / "tools/calibration/plot_dynamics.py"
            if plotter.is_file():
                try:
                    _run([
                        sys.executable, str(plotter),
                        "--det-root", str(det_root),
                        "--out-root", str(out_dir),
                        "--seasons", SEASON_ID,
                    ], ROOT)
                except subprocess.CalledProcessError as e:
                    print(f"WARNING: plot_dynamics.py failed for {label}: {e}")
        finally:
            _restore_filex(backup)

    # ── Comparison charts ────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("Rendering comparison charts")
    print(f"{'='*70}")
    comp_dir = FIGTURE / "comparison"
    comp_dir.mkdir(parents=True, exist_ok=True)
    sr_plots = _plot_scatter_residual(metrics_pairs, comp_dir, batch_titles)
    mc_plots = _plot_metrics_comparison(all_metrics, comp_dir, batch_titles)

    # Save combined metrics table
    combined = []
    for label, mdf in all_metrics.items():
        mdf2 = mdf.copy()
        mdf2["batch"] = batch_titles[label]
        combined.append(mdf2)
    combined_df = pd.concat(combined, ignore_index=True)
    combined_df.to_csv(comp_dir / "metrics_comparison.csv", index=False)
    print(f"\nCombined metrics:\n{combined_df.to_string(index=False)}")

    manifest = {
        "artifact_type": "best_member_deterministic_diagnostics",
        "batches": {b["label"]: {"title": b["title"], "run_dir": str(b["run_dir"])} for b in BATCHES},
        "season": SEASON_ID,
        "treatments": TREATMENTS,
        "custom_dssat_executable": str(CUSTOM_EXE.resolve()),
        "comparison_figures": sorted(p.name for p in sr_plots + mc_plots),
        "metrics_csv": str(comp_dir / "metrics_comparison.csv"),
    }
    (comp_dir / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nDiagnostics written to: {FIGTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
