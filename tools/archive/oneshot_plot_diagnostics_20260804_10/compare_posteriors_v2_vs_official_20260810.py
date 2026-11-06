"""Compare posterior parameter distributions: v2 (custom a3_nr_zp) vs official DSSAT.

Loads the final IES parameter ensembles (.5.par.csv, 200 realizations each) of
  - e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808  (custom exe)
  - e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809 (official exe)
and renders per-group posterior comparisons:

  * caterpillar plots (median + 5-95% interval) for genetic (73) and soil
    physical (48) params
  * IC initial-soil-N summary: per (variable, layer) boxplot of treatment
    medians across the two runs
  * shift histogram + median-vs-median scatter with 1:1 line
  * per-param comparison CSV (median/IQR/shift/KS p-value)

This is a Python run-diagnostics product (never Fig/FigS).

Usage:
    python tools/calibration/compare_posteriors_v2_vs_official_20260810.py
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

V2_CASE = "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808"
OFF_CASE = "e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809"
ENSEMBLES = {
    "v2": ROOT / f"workspace/runs/{V2_CASE}/{V2_CASE}.5.par.csv",
    "official": ROOT / f"workspace/runs/{OFF_CASE}/{OFF_CASE}.5.par.csv",
}
OUT_ROOT = ROOT / "figture/param_posterior_compare_20260810"

COLORS = {"v2": "#2878B5", "official": "#D95F02"}
PCT_LOW, PCT_HIGH = 5.0, 95.0


def _load_ensemble(path: Path) -> pd.DataFrame:
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


def _ks_p(a: pd.Series, b: pd.Series) -> float:
    return float(stats.ks_2samp(a.to_numpy(float), b.to_numpy(float)).pvalue)


def _caterpillar(rows: pd.DataFrame, group: str, title: str, out_png: Path) -> None:
    """rows: one per param, with v2_* and official_* stats columns, sorted."""
    order = rows.sort_values("shift_abs").index.tolist()
    fig, ax = plt.subplots(figsize=(9.5, max(5.0, 0.30 * len(order) + 2.0)), dpi=180)
    for i, name in enumerate(order):
        r = rows.loc[name]
        ax.errorbar([r["v2_median"]], [i + 0.19], xerr=[[r["v2_median"] - r["v2_p5"]], [r["v2_p95"] - r["v2_median"]]],
                    fmt="o", color=COLORS["v2"], markersize=4, capsize=2, lw=1.2, label="v2" if i == 0 else None)
        ax.errorbar([r["official_median"]], [i - 0.19], xerr=[[r["official_median"] - r["official_p5"]], [r["official_p95"] - r["official_median"]]],
                    fmt="s", color=COLORS["official"], markersize=4, capsize=2, lw=1.2, label="official" if i == 0 else None)
    ax.axvline(0, color="#999", lw=0.7, ls=":")
    ax.set_yticks(range(len(order)), order, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Posterior median with 5-95% interval")
    ax.set_title(title, fontsize=10)
    ax.grid(True, axis="x", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _scatter_medians(rows: pd.DataFrame, group: str, title: str, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 6.0), dpi=180)
    v = rows["v2_median"].to_numpy(float)
    o = rows["official_median"].to_numpy(float)
    ax.scatter(v, o, s=22, color="#555", alpha=0.7, edgecolor="white", linewidth=0.3)
    lo = min(v.min(), o.min()); hi = max(v.max(), o.max())
    pad = (hi - lo) * 0.05
    ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#999", lw=0.9)
    ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlabel("v2 (custom a3_nr_zp) posterior median")
    ax.set_ylabel("official DSSAT posterior median")
    ax.set_title(title, fontsize=10)
    ax.grid(True, alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def _ic_layer_boxplot(rows: pd.DataFrame, out_png: Path) -> None:
    """rows: one per IC param with v2_median / official_median columns.
    Aggregate by (variable, layer) over treatments: pair of medians per cell."""
    def _key(name: str):
        m = re.match(r"IC_(SNH4|SNO3)_(?:XXQL\d+)_TN\d+_L(\d+)", name, re.IGNORECASE)
        return m.group(1), int(m.group(2)) if m else (name, 0)

    cells = {}
    for name, r in rows.iterrows():
        var, layer = _key(str(name))
        cells.setdefault((var, layer), {"v2": [], "official": []})
        cells[(var, layer)]["v2"].append(r["v2_median"])
        cells[(var, layer)]["official"].append(r["official_median"])

    keys = sorted(cells.keys(), key=lambda kv: (kv[0], kv[1]))
    n = len(keys)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=180, sharey=True)
    for ax, var in zip(axes, ["SNH4", "SNO3"]):
        sub = [(layer, cells[(var, layer)]) for layer in range(1, 6) if (var, layer) in cells]
        x = np.arange(len(sub))
        v2_vals = [np.median(v["v2"]) for _, v in sub]
        off_vals = [np.median(v["official"]) for _, v in sub]
        w = 0.34
        ax.bar(x - w / 2, v2_vals, w, color=COLORS["v2"], alpha=0.85, label="v2" if var == "SNH4" else None)
        ax.bar(x + w / 2, off_vals, w, color=COLORS["official"], alpha=0.85, label="official" if var == "SNH4" else None)
        for j, ((_, cell), _) in enumerate(zip(sub, v2_vals)):
            ax.scatter([j - w / 2] * len(cell["v2"]), cell["v2"], s=8, color=COLORS["v2"], alpha=0.45, zorder=3)
            ax.scatter([j + w / 2] * len(cell["official"]), cell["official"], s=8, color=COLORS["official"], alpha=0.45, zorder=3)
        ax.set_xticks(x, [f"L{l}" for l, _ in sub])
        ax.set_xlabel("Layer")
        ax.set_ylabel(f"Posterior median {var} (mg/kg)")
        ax.set_title(f"IC {var} — treatment medians by layer", fontsize=10)
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ens = {k: _load_ensemble(p) for k, p in ENSEMBLES.items()}
    shared = [c for c in ens["v2"].columns if c in ens["official"].columns]
    print(f"v2: {ens['v2'].shape[1]} params | official: {ens['official'].shape[1]} | shared: {len(shared)}")

    rows = []
    for name in shared:
        a = ens["v2"][name]
        b = ens["official"][name]
        sv, so = _posterior_stats(a), _posterior_stats(b)
        scale = sv["iqr"] if sv["iqr"] > 0 else max(abs(sv["median"]) * 0.1, 1e-9)
        rows.append({
            "param": name,
            **{f"v2_{k}": v for k, v in sv.items()},
            **{f"official_{k}": v for k, v in so.items()},
            "shift_abs": so["median"] - sv["median"],
            "shift_iqr": (so["median"] - sv["median"]) / scale,
            "overlap_5_95": float(((b >= sv["p5"]) & (b <= sv["p95"])).mean()),
            "ks_p": _ks_p(a, b),
        })
    table = pd.DataFrame(rows).set_index("param")
    table.to_csv(OUT_ROOT / "posterior_comparison_all.csv", encoding="utf-8-sig")

    genetic = [n for n in shared if not n.lower().startswith(("soil_", "ic_"))]
    soil = [n for n in shared if n.lower().startswith("soil_")]
    ic = [n for n in shared if n.lower().startswith("ic_")]
    print(f"genetic: {len(genetic)} | soil physical: {len(soil)} | IC: {len(ic)}")

    # Genetic caterpillar (sorted by |shift|)
    g = table.loc[genetic].copy()
    g["shift_abs"] = g["shift_abs"].abs()
    g.to_csv(OUT_ROOT / "posterior_comparison_genetic.csv", encoding="utf-8-sig")
    _caterpillar(g, "genetic", "Genetic params: v2 (custom) vs official posterior (median ± 5-95%)",
                 OUT_ROOT / "caterpillar_genetic.png")
    _scatter_medians(g, "genetic", "Genetic params: posterior median comparison",
                     OUT_ROOT / "scatter_medians_genetic.png")

    # Soil physical caterpillar
    s = table.loc[soil].copy()
    s["shift_abs"] = s["shift_abs"].abs()
    s.to_csv(OUT_ROOT / "posterior_comparison_soil_physical.csv", encoding="utf-8-sig")
    _caterpillar(s, "soil", "Soil physical params: v2 (custom) vs official posterior (median ± 5-95%)",
                 OUT_ROOT / "caterpillar_soil_physical.png")
    _scatter_medians(s, "soil", "Soil physical params: posterior median comparison",
                     OUT_ROOT / "scatter_medians_soil_physical.png")

    # IC summary
    ic_table = table.loc[ic].copy()
    ic_table.to_csv(OUT_ROOT / "posterior_comparison_ic.csv", encoding="utf-8-sig")
    _ic_layer_boxplot(ic_table, OUT_ROOT / "ic_layer_boxplot.png")

    # Shift histogram (all shared, genetic + soil physical; IC has its own view)
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=180)
    for name, color in (("genetic", "#2A6FA0"), ("soil_physical", "#B0782A")):
        sub = table.loc[{"genetic": genetic, "soil_physical": soil}[name]]
        ax.hist(sub["shift_iqr"], bins=24, alpha=0.55, color=color, label=name)
    ax.axvline(0, color="#999", lw=0.9, ls="--")
    ax.set_xlabel("Median shift (official − v2) / v2 IQR")
    ax.set_ylabel("Parameter count")
    ax.set_title("Posterior median shift distribution", fontsize=10)
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT_ROOT / "shift_histogram.png", bbox_inches="tight")
    plt.close(fig)

    # Top-shifted params (genetic + soil) table
    top = table.loc[genetic + soil].copy()
    top["abs_shift_iqr"] = top["shift_iqr"].abs()
    top = top.sort_values("abs_shift_iqr", ascending=False).head(15)
    top[["v2_median", "official_median", "shift_iqr", "overlap_5_95", "ks_p"]].to_csv(
        OUT_ROOT / "top_shifted_params.csv", encoding="utf-8-sig")

    manifest = {
        "artifact_type": "posterior_comparison_v2_vs_official_20260810",
        "v2_run": V2_CASE, "official_run": OFF_CASE,
        "ensembles": {k: str(p) for k, p in ENSEMBLES.items()},
        "n_realizations": 200,
        "shared_params": len(shared),
        "groups": {"genetic": len(genetic), "soil_physical": len(soil), "ic": len(ic)},
        "note": "ks_p from two-sample KS (200 vs 200); overlap_5_95 = fraction of official samples inside v2 5-95% posterior",
        "figures": sorted(str(p.relative_to(OUT_ROOT)) for p in OUT_ROOT.glob("*.png")),
    }
    (OUT_ROOT / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nWritten to: {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
