"""Recompute fit metrics and redraw charts after the TMT dry-weight fix.

The DMFR anomaly fix changed the observed dry weights for TN13 (5685->1958)
and TN5 (2882 for TN5 cum).  Simulated values are unchanged (same params, same
DSSAT), so we only need to:
  1. copy the corrected TMT into each deterministic season dir,
  2. regenerate the deterministic_harvest_compare.csv (OBS columns refreshed,
     SIM columns untouched),
  3. recompute fit metrics,
  4. redraw the full diagnostic figure set into figture/.

Usage:
    python tools/calibration/recompute_metrics_after_dmfr_fix_20260807.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)

CORRECTED_TMT = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/XXQL2501.TMT"
SEASON_ID = "25SP"
TREATMENTS = [13, 12, 11, 5, 4, 3]
FIGTURE = ROOT / "figture"
OUT_SUBDIR = "post_dmfr_fix_20260807"

BATCHES = {
    "batchA_nresp_sw_onethird": {
        "title": "批次A 降权1/3 (旧方案)",
        "det_root": ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260806_nresp_sw_onethird_20260806/best_member_110_deterministic_20260807",
    },
    "batchB_rawdiff_terminal": {
        "title": "批次B 新方案 (rawdiff_terminal)",
        "det_root": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806/best_member_139_deterministic_20260807",
    },
}
COLORS = {"batchA_nresp_sw_onethird": "#2878B5", "batchB_rawdiff_terminal": "#D95F02"}


def _compute_metrics(season_dir: Path, det_root: Path) -> pd.DataFrame:
    """Regenerate compare CSVs and compute fit metrics (uses corrected TMT)."""
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
    result.to_csv(det_root / "metrics_post_dmfr_fix.csv", index=False)
    return result


def _plot_scatter_residual(metrics_pairs: dict, out_root: Path, titles: dict) -> list[Path]:
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
            ax.scatter(y, p, color=COLORS.get(label, "#555"), s=36, alpha=0.8,
                       edgecolor="white", linewidth=0.3)
            ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
            ax.set_title(titles.get(label, label), fontsize=9)
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
        fig.suptitle(f"{var}: observed vs simulated (post DMFR fix)", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        path = out_root / f"scatter_{var}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)

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
            ax.scatter(y, r, color=COLORS.get(label, "#555"), s=36, alpha=0.8,
                       edgecolor="white", linewidth=0.3)
            ax.axhline(0, ls="--", color="#555", lw=0.9)
            ax.set_title(titles.get(label, label), fontsize=9)
            ax.set_xlabel("Observed")
            ax.set_ylabel("Simulated − observed")
            ax.set_ylim(-1.15 * rmax, 1.15 * rmax)
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{var}: residuals (simulated − observed) (post DMFR fix)", fontsize=11)
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
        width = 0.35
        for j, (label, mdf) in enumerate(all_metrics.items()):
            vals = mdf.set_index("variable")[metric].reindex(var_order)
            ax.bar(x + (j - 0.5) * width, vals.to_numpy(float), width,
                   label=titles.get(label, label), color=COLORS.get(label))
        ax.set_xticks(x, var_order, rotation=45, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(f"Best-member fit metric (post DMFR fix): {ylabel}")
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
    out_root = FIGTURE / OUT_SUBDIR
    out_root.mkdir(parents=True, exist_ok=True)

    all_metrics = {}
    metrics_pairs = {}
    titles = {k: v["title"] for k, v in BATCHES.items()}

    for label, info in BATCHES.items():
        det_root = info["det_root"]
        season_dir = det_root / "_seasons" / SEASON_ID
        if not season_dir.is_dir():
            print(f"SKIP {label}: no season dir {season_dir}")
            continue

        # 1. Update TMT to corrected version
        dst = season_dir / "XXQL2501.TMT"
        shutil.copy2(CORRECTED_TMT, dst)
        print(f"[{label}] updated TMT -> {dst.name}")

        # 2. Regenerate compare CSVs + metrics (uses corrected TMT observations)
        metrics = _compute_metrics(season_dir, det_root)
        all_metrics[label] = metrics
        metrics_pairs[label] = det_root
        print(f"[{label}] metrics (post fix):")
        print(metrics.to_string(index=False))
        print()

    if len(all_metrics) < 2:
        print("ERROR: need both batches to render comparison", file=sys.stderr)
        return 1

    # 3. Render charts
    sr_plots = _plot_scatter_residual(metrics_pairs, out_root, titles)
    mc_plots = _plot_metrics_comparison(all_metrics, out_root, titles)

    combined = []
    for label, mdf in all_metrics.items():
        mdf2 = mdf.copy()
        mdf2["batch"] = titles[label]
        combined.append(mdf2)
    combined_df = pd.concat(combined, ignore_index=True)
    combined_df.to_csv(out_root / "metrics_comparison_post_dmfr_fix.csv", index=False)

    manifest = {
        "artifact_type": "fit_metrics_after_dmfr_fix",
        "correction": "TN13/TN5 anomalous moisture replicates removed (TN13 DMFR 9.31%->3.21%)",
        "batches": titles,
        "comparison_figures": sorted(p.name for p in sr_plots + mc_plots),
        "metrics_csv": str(out_root / "metrics_comparison_post_dmfr_fix.csv"),
    }
    (out_root / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWritten to: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
