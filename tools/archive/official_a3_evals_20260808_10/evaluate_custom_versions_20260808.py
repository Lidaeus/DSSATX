"""Evaluate the three custom DSSAT versions (a3/a3_nr_zp/nni) best members.

For each version:
  1. export its best member (min-Phi realization) parameters,
  2. run a deterministic DSSAT replay with the version's OWN custom exe + SPE,
     against the DMFR-CORRECTED bundle (new TMT — TN13 dry weight fixed),
  3. compute fit metrics (RMSE/NRMSE/NSE/d-index/R²) for all variables,
  4. render scatter/residual/comparison charts into figture/.

Usage:
    python tools/calibration/evaluate_custom_versions_20260808.py
"""

from __future__ import annotations

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

SEASON_ID = "25SP"
EXPERIMENT = "XXQL2501"
TREATMENTS = [13, 12, 11, 5, 4, 3]
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
FIGTURE = ROOT / "figture"
OUT_DIR_NAME = "custom_versions_20260808"

VERSIONS = {
    "a3": {
        "exe_dir": "windows_a3_20260806",
        "title": "A3 阈值氮吸收 (NUPK50+NUPCMN)",
        "run_dir": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_a3_108par_150x4_20260807",
        "case": "e02_v2_rawdiff_terminal_a3_108par_150x4_20260807",
    },
    "a3_nr_zp": {
        "exe_dir": "windows_a3_nr_zp_20260806",
        "title": "A3+零保持NR响应 (NUPK50+NUPCMN+NREXP+NRMIN)",
        "run_dir": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260807",
        "case": "e02_v2_rawdiff_terminal_a3_nr_zp_108par_150x4_20260807",
    },
    "nni": {
        "exe_dir": "windows_nni_20260806",
        "title": "NNI 临界氮稀释 (NUPK50+NUPQ)",
        "run_dir": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nni_108par_150x4_20260807",
        "case": "e02_v2_rawdiff_terminal_nni_108par_150x4_20260807",
    },
}
COLORS = {"a3": "#2878B5", "a3_nr_zp": "#D95F02", "nni": "#2A9D55"}

DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _best_member(run_dir: Path, case: str) -> str:
    pg = pd.read_csv(run_dir / f"{case}.phi.group.csv")
    mi = pg["iteration"].max()
    f = pg[pg["iteration"] == mi].copy()
    meta = {"iteration", "total_runs", "obs_realization", "par_realization"}
    gcols = [c for c in pg.columns if c not in meta]
    for c in gcols:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f["_total"] = f[gcols].sum(axis=1)
    b = f.loc[f["_total"].idxmin()]
    return str(int(float(b["par_realization"])))


def _export_member(run_dir: Path, case: str, member: str, out_csv: Path) -> int:
    frame = pd.read_csv(run_dir / f"{case}.4.par.csv")
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(member))
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


def _write_design(out_dir: Path, case: str, member: str, exe: Path, spe: Path) -> Path:
    payload = {
        "schema_version": 1,
        "design_id": f"{case}_best{member}_det_20260808",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "deterministic best-member replay on corrected bundle",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260805.csv",
        "purpose": "deterministic diagnostics; no re-calibration",
        "diagnostic_single_season": True,
        "custom_dssat_executable": str(exe.resolve()),
        "custom_spe": str(spe.resolve()),
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


def _swap(version: str) -> list[tuple[Path, Path]]:
    exe_dir = ROOT / "windows" / VERSIONS[version]["exe_dir"]
    custom_exe = exe_dir / "DSCSM048.EXE"
    custom_spe = exe_dir / "Genotype/TMGRO048.SPE"
    backup_exe = ROOT / f"workspace/DSCSM048.EXE.eval_{version}"
    spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
    spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.eval_{version}"

    replacements = []
    shutil.copy2(DEFAULT_EXE, backup_exe)
    shutil.copy2(custom_exe, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    shutil.copy2(spe_base, spe_backup)
    shutil.copy2(custom_spe, spe_base)
    replacements.append((spe_base, spe_backup))
    plain = GENOTYPE_DIR / "TMGRO048.SPE"
    if plain.is_file():
        pb = GENOTYPE_DIR / f"TMGRO048.SPE.eval_{version}"
        shutil.copy2(plain, pb)
        shutil.copy2(custom_spe, plain)
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


def _plot_scatter_residual(metrics_pairs: dict, out_root: Path, titles: dict) -> list[Path]:
    outputs = []
    vars_all = set()
    for label, det_root in metrics_pairs.items():
        season_dir = det_root / "_seasons" / SEASON_ID
        for fname in (f"{SEASON_ID}_deterministic_process_compare.csv",
                      f"{SEASON_ID}_deterministic_harvest_compare.csv"):
            path = season_dir / fname
            if path.is_file():
                frame = pd.read_csv(path)
                for col in frame.columns:
                    if str(col).startswith("OBS_"):
                        vars_all.add(str(col)[4:])

    for var in sorted(vars_all):
        # Scatter
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), dpi=180)
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
            ax.scatter(y, p, color=COLORS.get(label, "#555"), s=30, alpha=0.8,
                       edgecolor="white", linewidth=0.3)
            ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
            ax.set_title(titles.get(label, label), fontsize=8)
            ax.set_xlim(lo - pad, hi + pad)
            ax.set_ylim(lo - pad, hi + pad)
            ax.set_xlabel("Observed")
            ax.set_ylabel("Simulated")
            rmse = float(np.sqrt(np.mean(e ** 2)))
            ax.text(0.04, 0.96, f"n={len(pairs)}\nRMSE={rmse:.3g}\nBias={e.mean():+.3g}",
                    transform=ax.transAxes, va="top", fontsize=7, family="monospace",
                    bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"})
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{var}: observed vs simulated (new TMT)", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        path = out_root / f"scatter_{var}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)

        # Residual
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), dpi=180)
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
            ax.scatter(y, r, color=COLORS.get(label, "#555"), s=30, alpha=0.8,
                       edgecolor="white", linewidth=0.3)
            ax.axhline(0, ls="--", color="#555", lw=0.9)
            ax.set_title(titles.get(label, label), fontsize=8)
            ax.set_xlabel("Observed")
            ax.set_ylabel("Simulated − observed")
            ax.set_ylim(-1.15 * rmax, 1.15 * rmax)
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{var}: residuals (simulated − observed) (new TMT)", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        path = out_root / f"residual_{var}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)
    return outputs


def _plot_metrics_comparison(all_metrics: dict, out_root: Path, titles: dict) -> list[Path]:
    outputs = []
    var_order = []
    for mdf in all_metrics.values():
        for v in mdf["variable"]:
            if v not in var_order:
                var_order.append(v)
    for metric, ylabel in (("rrmse_pct", "RRMSE (%)"), ("nse", "NSE"), ("r2", "R²"), ("d_index", "d-index")):
        fig, ax = plt.subplots(figsize=(10, 5), dpi=180)
        x = np.arange(len(var_order))
        width = 0.25
        for j, (label, mdf) in enumerate(all_metrics.items()):
            vals = mdf.set_index("variable")[metric].reindex(var_order)
            ax.bar(x + (j - 1) * width, vals.to_numpy(float), width,
                   label=titles.get(label, label), color=COLORS.get(label))
        ax.set_xticks(x, var_order, rotation=45, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(f"Best-member fit metric (new TMT): {ylabel}")
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        path = out_root / f"comparison_{metric}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)
    return outputs


def main() -> int:
    out_root = FIGTURE / OUT_DIR_NAME
    out_root.mkdir(parents=True, exist_ok=True)
    all_metrics = {}
    metrics_pairs = {}
    titles = {k: v["title"] for k, v in VERSIONS.items()}

    for version, info in VERSIONS.items():
        run_dir = info["run_dir"]
        case = info["case"]
        exe = ROOT / "windows" / info["exe_dir"] / "DSCSM048.EXE"
        spe = ROOT / "windows" / info["exe_dir"] / "Genotype/TMGRO048.SPE"

        print(f"\n{'='*70}\n{version} ({info['title']})\n{'='*70}")
        member = _best_member(run_dir, case)
        print(f"best member = real {member}")

        det_root = run_dir / f"best_member_{member}_deterministic_20260808"
        det_root.mkdir(parents=True, exist_ok=True)
        params = det_root / f"best_member_{member}_params.csv"
        n_params = _export_member(run_dir, case, member, params)
        print(f"exported {n_params} params")

        design = _write_design(det_root, case, member, exe, spe)
        status = det_root / "multiseason_run_status.json"
        if not status.is_file():
            os.environ["DSSAT_SPE_BASE"] = str(spe.resolve())
            os.environ["DSSAT_FILEX_MAP"] = json.dumps({
                f"{EXPERIMENT}.TMX": str((BUNDLE / f"{EXPERIMENT}.TMX").resolve())
            })
            os.environ["DSSAT_BATCH_FILEX_ROOT"] = str(Path(r"C:\DSSAT48\TOMATO"))
            os.environ["DSSAT_KEEP_RUNS"] = "1"
            os.environ["DSSAT_DISABLE_SOIL_INJECTION"] = "1"
            replacements = _swap(version)
            try:
                subprocess.run([
                    sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                    "--design", str(design), "--param-csv", str(params),
                    "--prefix", f"best{member}_det", "--harvest-var", "CHPDT",
                    "--keep-nitrogen-outputs",
                ], cwd=str(det_root), check=True)
            finally:
                _restore(replacements)
        metrics = _compute_metrics(det_root)
        all_metrics[version] = metrics
        metrics_pairs[version] = det_root
        print(f"metrics:\n{metrics.to_string(index=False)}")

    sr_plots = _plot_scatter_residual(metrics_pairs, out_root, titles)
    mc_plots = _plot_metrics_comparison(all_metrics, out_root, titles)

    combined = []
    for label, mdf in all_metrics.items():
        mdf2 = mdf.copy()
        mdf2["version"] = titles[label]
        combined.append(mdf2)
    combined_df = pd.concat(combined, ignore_index=True)
    combined_df.to_csv(out_root / "metrics_custom_versions_20260808.csv", index=False)

    manifest = {
        "artifact_type": "custom_dssat_versions_evaluation",
        "bundle": str(BUNDLE),
        "bundle_manifest_sha256": _sha256(BUNDLE / "input_manifest.json"),
        "note": "DMFR-corrected bundle (new TMT); TN13 dry weight 5685->1958",
        "versions": titles,
        "figures": sorted(p.name for p in sr_plots + mc_plots),
        "metrics_csv": str(out_root / "metrics_custom_versions_20260808.csv"),
    }
    (out_root / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWritten to: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
