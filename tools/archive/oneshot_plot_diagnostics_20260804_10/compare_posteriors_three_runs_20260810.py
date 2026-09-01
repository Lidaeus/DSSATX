"""Compare posterior parameter distributions across THREE calibration runs.

Loads the final IES parameter ensembles (.5.par.csv, 200 realizations each) of
  - v2        e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808  (a3_nr_zp)
  - official  e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809 (official v4.8)
  - a3        e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810  (a3 thresholded)
and renders per-group posterior comparisons:

  * caterpillar plots (median + 5-95% interval, three colors) for genetic (73)
    and soil physical (48) params
  * pairwise median scatter plots (v2 vs official, v2 vs a3, official vs a3)
  * IC initial-soil-N summary: per (variable, layer) grouped boxplot
  * shift histogram + per-param comparison CSVs (median/IQR/pairwise KS p)

This is a Python run-diagnostics product (never Fig/FigS).

Usage:
    python tools/calibration/compare_posteriors_three_runs_20260810.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]

RUNS = {
    "v2": {
        "case": "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808",
        "label": "v2 (a3_nr_zp)",
    },
    "official": {
        "case": "e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809",
        "label": "official v4.8",
    },
    "a3": {
        "case": "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810",
        "label": "a3 (thresholded)",
    },
}
ORDER = ["v2", "official", "a3"]
COLORS = {"v2": "#2878B5", "official": "#D95F02", "a3": "#2A9D55"}
OUT_ROOT = ROOT / "figture/param_posterior_compare_three_20260810"


def _load_ensemble(case: str) -> pd.DataFrame:
    path = ROOT / f"workspace/runs/{case}/{case}.5.par.csv"
    frame = pd.read_csv(path)
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    if real_col is None:
        raise ValueError(f"{path}: no realization column")
    return frame.drop(columns=[real_col])


def _posterior_stats(series: pd.Series) -> dict:
    return {
        "median": float(series.median()),
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)),
        "p5": float(series.quantile(0.05)),
        "p95": float(series.quantile(0.95)),
        "q25": float(series.quantile(0.25)),
        "q75": float(series.quantile(0.75)),
        "iqr": float(series.quantile(0.75) - series.quantile(0.25)),
    }


def _caterpillar(rows: pd.DataFrame, group: str, title: str, out_png: Path) -> None:
    order = rows.sort_values("range_abs").index.tolist()
    n = len(order)
    fig, ax = plt.subplots(figsize=(10.5, max(5.0, 0.30 * n + 2.0)), dpi=180)
    for k, run in enumerate(ORDER):
        yoff = (k - (len(ORDER) - 1) / 2) * 0.26
        ax.errorbar([rows.loc[o, f"{run}_median"] for o in order],
                    [i + yoff for i in range(n)],
                    xerr=[[rows.loc[o, f"{run}_median"] - rows.loc[o, f"{run}_p5"] for o in order],
                          [rows.loc[o, f"{run}_p95"] - rows.loc[o, f"{run}_median"] for o in order]],
                    fmt="o", color=COLORS[run], markersize=4, capsize=2, lw=1.2,
                    label=RUNS[run]["label"] if k == 0 else None)
    ax.axvline(0, color="#999", lw=0.7, ls=":")
    ax.set_yticks(range(n), order, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Posterior median with 5-95% interval")
    ax.set_title(title, fontsize=10)
    ax.grid(True, axis="x", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _scatter_pairs(rows: pd.DataFrame, group: str, out_root: Path) -> None:
    pairs = [("v2", "official"), ("v2", "a3"), ("official", "a3")]
    n = len(pairs)
    fig, axes = plt.subplots(1, n, figsize=(6.4 * n, 6.0), dpi=180, sharey=True)
    for ax, (a, b) in zip(axes, pairs):
        x = rows[f"{a}_median"].to_numpy(float)
        y = rows[f"{b}_median"].to_numpy(float)
        ax.scatter(x, y, s=22, color="#555", alpha=0.7, edgecolor="white", linewidth=0.3)
        lo = min(x.min(), y.min()); hi = max(x.max(), y.max())
        pad = (hi - lo) * 0.05
        ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#999", lw=0.9)
        ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(lo - pad, hi + pad)
        ax.set_xlabel(f"{RUNS[a]['label']} median")
        ax.set_ylabel(f"{RUNS[b]['label']} median")
        ax.set_title(f"{group}: {RUNS[a]['label']} vs {RUNS[b]['label']}", fontsize=9)
        ax.grid(True, alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_root / f"scatter_medians_{group}_pairs.png", bbox_inches="tight")
    plt.close(fig)


def _ic_grouped_boxplot(rows: pd.DataFrame, out_root: Path) -> None:
    """rows: one per IC param with <run>_median columns; group by (var, layer)."""
    cells = {}
    for name, r in rows.iterrows():
        m = re.search(r"_(SNH4|SNO3)_(?:XXQL\d+)_TN\d+_L(\d+)", str(name).upper())
        if not m:
            continue
        var, layer = m.group(1), int(m.group(2))
        cells.setdefault((var, layer), {run: [] for run in ORDER})
        for run in ORDER:
            cells[(var, layer)][run].append(r[f"{run}_median"])

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), dpi=180, sharey=True)
    for ax, var in zip(axes, ["SNH4", "SNO3"]):
        sub = [(layer, cells[(var, layer)]) for layer in range(1, 6) if (var, layer) in cells]
        x = np.arange(len(sub))
        n_runs = len(ORDER)
        w = 0.24
        for k, run in enumerate(ORDER):
            off = (k - (n_runs - 1) / 2) * w
            vals = [np.median(cell[run]) for _, cell in sub]
            ax.bar(x + off, vals, w, color=COLORS[run], alpha=0.85,
                   label=RUNS[run]["label"] if var == "SNH4" else None)
        ax.set_xticks(x, [f"L{l}" for l, _ in sub])
        ax.set_xlabel("Layer")
        ax.set_ylabel(f"Posterior median {var} (mg/kg)")
        ax.set_title(f"IC {var} — treatment-median by layer", fontsize=10)
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_root / "ic_layer_boxplot_three.png", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ens = {k: _load_ensemble(RUNS[k]["case"]) for k in ORDER}
    shared = [c for c in ens["v2"].columns if all(c in ens[r].columns for r in ORDER)]
    print(f"ensembles: " + ", ".join(f"{RUNS[k]['label']}={ens[k].shape[1]} params" for k in ORDER))
    print(f"shared across all three: {len(shared)}")

    rows = []
    for name in shared:
        sv = {r: _posterior_stats(ens[r][name]) for r in ORDER}
        scale = max(sv["v2"]["iqr"], 1e-9)
        record = {"param": name,
                  **{f"{r}_{k}": v for r in ORDER for k, v in sv[r].items()}}
        meds = [sv[r]["median"] for r in ORDER]
        record["range_abs"] = max(meds) - min(meds)
        record["range_iqr"] = (max(meds) - min(meds)) / scale
        for a, b in (("v2", "official"), ("v2", "a3"), ("official", "a3")):
            record[f"ks_p_{a}_vs_{b}"] = float(
                stats.ks_2samp(ens[a][name].to_numpy(float), ens[b][name].to_numpy(float)).pvalue)
        rows.append(record)
    table = pd.DataFrame(rows).set_index("param")
    table.to_csv(OUT_ROOT / "posterior_comparison_all.csv", encoding="utf-8-sig")

    genetic = [n for n in shared if not n.lower().startswith(("soil_", "ic_"))]
    soil = [n for n in shared if n.lower().startswith("soil_")]
    ic = [n for n in shared if n.lower().startswith("ic_")]
    print(f"genetic: {len(genetic)} | soil physical: {len(soil)} | IC: {len(ic)}")

    g = table.loc[genetic].copy()
    g.to_csv(OUT_ROOT / "posterior_comparison_genetic.csv", encoding="utf-8-sig")
    _caterpillar(g, "genetic", "Genetic params: three-run posterior (median ± 5-95%)",
                 OUT_ROOT / "caterpillar_genetic.png")
    _scatter_pairs(g, "genetic", OUT_ROOT)

    s = table.loc[soil].copy()
    s.to_csv(OUT_ROOT / "posterior_comparison_soil_physical.csv", encoding="utf-8-sig")
    _caterpillar(s, "soil", "Soil physical params: three-run posterior (median ± 5-95%)",
                 OUT_ROOT / "caterpillar_soil_physical.png")
    _scatter_pairs(s, "soil", OUT_ROOT)

    ic_table = table.loc[ic].copy()
    ic_table.to_csv(OUT_ROOT / "posterior_comparison_ic.csv", encoding="utf-8-sig")
    _ic_grouped_boxplot(ic_table, OUT_ROOT)

    # Shift histogram: max pairwise median distance in IQR units
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=180)
    for name, color in (("genetic", "#2A6FA0"), ("soil_physical", "#B0782A")):
        sub = table.loc[{"genetic": genetic, "soil_physical": soil}[name]]
        ax.hist(sub["range_iqr"], bins=24, alpha=0.55, color=color, label=name)
    ax.axvline(0, color="#999", lw=0.9, ls="--")
    ax.set_xlabel("Max pairwise median spread / v2 IQR")
    ax.set_ylabel("Parameter count")
    ax.set_title("Three-run posterior median spread", fontsize=10)
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT_ROOT / "spread_histogram.png", bbox_inches="tight")
    plt.close(fig)

    # Top-spread params (genetic + soil)
    top = table.loc[genetic + soil].copy()
    top = top.sort_values("range_iqr", ascending=False).head(20)
    cols = [f"{r}_median" for r in ORDER] + [f"{r}_iqr" for r in ORDER] + \
           [c for c in top.columns if c.startswith("ks_p_")]
    top[cols].to_csv(OUT_ROOT / "top_spread_params.csv", encoding="utf-8-sig")

    manifest = {
        "artifact_type": "posterior_comparison_three_runs_20260810",
        "runs": {k: RUNS[k]["case"] for k in ORDER},
        "n_realizations": 200,
        "shared_params": len(shared),
        "groups": {"genetic": len(genetic), "soil_physical": len(soil), "ic": len(ic)},
        "figures": sorted(str(p.relative_to(OUT_ROOT)) for p in OUT_ROOT.glob("*.png")),
    }
    (OUT_ROOT / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nWritten to: {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
