"""Evaluate a3_nr_zp (20260808) best member on the DMFR-corrected bundle.

Uses the A3-NR-ZP custom DSSAT exe + SPE with best member #103 parameters
on the corrected layermean_ic_valid 25SP bundle, computes fit metrics, and
renders scatter/residual/metrics charts into figture/.

Usage:
    python tools/calibration/evaluate_a3_nr_zp_20260808.py
"""

from __future__ import annotations

import json
import math
import os
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

SEASON_ID = "25SP"
EXPERIMENT = "XXQL2501"
TREATMENTS = [13, 12, 11, 5, 4, 3]
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
FIGTURE = ROOT / "figture"
OUT_DIR_NAME = "a3_nr_zp_20260808"

RUN_DIR = ROOT / "workspace/runs/e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260808"
CASE = "e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260808"
BEST_MEMBER = "103"

EXE_DIR = ROOT / "windows/windows_a3_nr_zp_20260806"
CUSTOM_EXE = EXE_DIR / "DSCSM048.EXE"
CUSTOM_SPE = EXE_DIR / "Genotype/TMGRO048.SPE"
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _export_member(out_csv: Path) -> int:
    frame = pd.read_csv(RUN_DIR / f"{CASE}.4.par.csv")
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST_MEMBER)
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        v = float(row[col])
        if not math.isfinite(v):
            raise ValueError(f"non-finite {col}={v}")
        records.append({"name": str(col).upper(), "value": v})
    pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def _write_design(out_dir: Path) -> Path:
    payload = {
        "schema_version": 1,
        "design_id": f"{CASE}_best{BEST_MEMBER}_det_20260808",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "deterministic best-member replay on corrected bundle",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260805.csv",
        "purpose": "deterministic diagnostics; no re-calibration",
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


def _swap() -> list[tuple[Path, Path]]:
    backup_exe = ROOT / "workspace/DSCSM048.EXE.eval_a3nrzp"
    spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
    spe_backup = GENOTYPE_DIR / "TMGRO048.SPE.base.eval_a3nrzp"
    replacements = []
    shutil.copy2(DEFAULT_EXE, backup_exe)
    shutil.copy2(CUSTOM_EXE, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    shutil.copy2(spe_base, spe_backup)
    shutil.copy2(CUSTOM_SPE, spe_base)
    replacements.append((spe_base, spe_backup))
    plain = GENOTYPE_DIR / "TMGRO048.SPE"
    if plain.is_file():
        pb = GENOTYPE_DIR / "TMGRO048.SPE.eval_a3nrzp"
        shutil.copy2(plain, pb)
        shutil.copy2(CUSTOM_SPE, plain)
        replacements.append((plain, pb))
    return replacements


def _restore(replacements: list[tuple[Path, Path]]) -> None:
    for live, backup in reversed(replacements):
        if live.exists():
            live.unlink()
        if backup.exists():
            backup.replace(live)


def _compute_metrics(det_root: Path) -> pd.DataFrame:
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


def _plot_charts(metrics: pd.DataFrame, det_root: Path, out_root: Path) -> list[Path]:
    outputs = []
    season_dir = det_root / "_seasons" / SEASON_ID
    title = f"a3_nr_zp best#{BEST_MEMBER} (new TMT)"

    # Scatter + residual for each variable
    vars_all = set()
    pairs_by_var = {}
    for fname in (f"{SEASON_ID}_deterministic_process_compare.csv",
                  f"{SEASON_ID}_deterministic_harvest_compare.csv"):
        path = season_dir / fname
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        for col in frame.columns:
            if str(col).startswith("OBS_"):
                var = str(col)[4:]
                vars_all.add(var)
                sim_col = f"SIM_{var}"
                if sim_col in frame:
                    sub = frame[[col, sim_col]].copy()
                    sub.columns = ["observed", "simulated"]
                    sub = sub[(sub["observed"] != -99) & (sub["simulated"] != -99)].dropna()
                    pairs_by_var[var] = sub

    for var in sorted(vars_all):
        pairs = pairs_by_var.get(var)
        if pairs is None or pairs.empty:
            continue
        y = pairs["observed"].to_numpy(float)
        p = pairs["simulated"].to_numpy(float)
        e = p - y
        lo = float(min(y.min(), p.min()))
        hi = float(max(y.max(), p.max()))
        pad = max((hi - lo) * 0.06, 1e-6)

        # Scatter
        fig, ax = plt.subplots(figsize=(6, 5), dpi=180)
        ax.scatter(y, p, color="#D95F02", s=36, alpha=0.8, edgecolor="white", linewidth=0.3)
        ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_xlabel("Observed")
        ax.set_ylabel("Simulated")
        rmse = float(np.sqrt(np.mean(e ** 2)))
        ax.text(0.04, 0.96, f"n={len(pairs)}\nRMSE={rmse:.3g}\nBias={e.mean():+.3g}",
                transform=ax.transAxes, va="top", fontsize=8, family="monospace",
                bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"})
        ax.set_title(f"{var}: {title}", fontsize=10)
        ax.grid(True, alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        sp = out_root / f"scatter_{var}.png"
        fig.savefig(sp, bbox_inches="tight")
        plt.close(fig)
        outputs.append(sp)

        # Residual
        rmax = max(float(np.nanmax(np.abs(e))), 1e-6)
        fig, ax = plt.subplots(figsize=(6, 5), dpi=180)
        ax.scatter(y, e, color="#D95F02", s=36, alpha=0.8, edgecolor="white", linewidth=0.3)
        ax.axhline(0, ls="--", color="#555", lw=0.9)
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(-1.15 * rmax, 1.15 * rmax)
        ax.set_xlabel("Observed")
        ax.set_ylabel("Simulated − observed")
        ax.set_title(f"{var}: residuals ({title})", fontsize=10)
        ax.grid(True, alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        rp = out_root / f"residual_{var}.png"
        fig.savefig(rp, bbox_inches="tight")
        plt.close(fig)
        outputs.append(rp)

    # Metrics bar charts
    var_order = [v for v in ["LAID", "LWAD", "SWAD", "DRY_CUM", "DRY_INC", "CHTD", "LAIX", "ADAP"]
                 if v in metrics["variable"].values]
    for v in metrics["variable"]:
        if v not in var_order:
            var_order.append(v)

    for metric, ylabel in (("rrmse_pct", "RRMSE (%)"), ("nse", "NSE"), ("r2", "R²"), ("d_index", "d-index")):
        fig, ax = plt.subplots(figsize=(10, 5), dpi=180)
        x = np.arange(len(var_order))
        vals = metrics.set_index("variable")[metric].reindex(var_order)
        ax.bar(x, vals.to_numpy(float), color="#D95F02")
        ax.set_xticks(x, var_order, rotation=45, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{title}: {ylabel}")
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        mp = out_root / f"metrics_{metric}.png"
        fig.savefig(mp, bbox_inches="tight")
        plt.close(fig)
        outputs.append(mp)

    return outputs


def main() -> int:
    out_root = FIGTURE / OUT_DIR_NAME
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"a3_nr_zp (20260808) best member = #{BEST_MEMBER}")

    det_root = RUN_DIR / f"best_member_{BEST_MEMBER}_deterministic_20260808"
    det_root.mkdir(parents=True, exist_ok=True)
    params = det_root / f"best_member_{BEST_MEMBER}_params.csv"
    n_params = _export_member(params)
    print(f"exported {n_params} params")

    design = _write_design(det_root)
    status = det_root / "multiseason_run_status.json"
    if not status.is_file():
        os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE.resolve())
        os.environ["DSSAT_FILEX_MAP"] = json.dumps({
            f"{EXPERIMENT}.TMX": str((BUNDLE / f"{EXPERIMENT}.TMX").resolve())
        })
        os.environ["DSSAT_BATCH_FILEX_ROOT"] = str(Path(r"C:\DSSAT48\TOMATO"))
        os.environ["DSSAT_KEEP_RUNS"] = "1"
        os.environ["DSSAT_DISABLE_SOIL_INJECTION"] = "1"
        replacements = _swap()
        try:
            subprocess.run([
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design), "--param-csv", str(params),
                "--prefix", f"best{BEST_MEMBER}_det", "--harvest-var", "CHPDT",
                "--keep-nitrogen-outputs",
            ], cwd=str(det_root), check=True)
        finally:
            _restore(replacements)

    metrics = _compute_metrics(det_root)
    print(f"\nmetrics:\n{metrics.to_string(index=False)}")

    plots = _plot_charts(metrics, det_root, out_root)
    metrics.to_csv(out_root / "metrics_a3_nr_zp_20260808.csv", index=False)

    manifest = {
        "artifact_type": "a3_nr_zp_evaluation",
        "version": "a3_nr_zp",
        "run_id": CASE,
        "best_member": BEST_MEMBER,
        "bundle": str(BUNDLE),
        "bundle_manifest_sha256": _sha256(BUNDLE / "input_manifest.json"),
        "custom_dssat": str(CUSTOM_EXE.resolve()),
        "custom_spe": str(CUSTOM_SPE.resolve()),
        "note": "DMFR-corrected bundle (new TMT); a3_nr_zp exe with NUPK50+NUPCMN+NREXP+NRMIN",
        "figures": sorted(p.name for p in plots),
        "metrics_csv": str(out_root / "metrics_a3_nr_zp_20260808.csv"),
    }
    (out_root / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWritten to: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
