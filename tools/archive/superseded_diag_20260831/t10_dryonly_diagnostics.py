"""Diagnostic plots and posterior comparison for the T10 dry-only calibration.

This is a **Python run-time diagnostic** entry (outputs are prefixed
``diagnostic_*``). It never produces ``Fig``/``FigS`` paper figures -- those are
rendered exclusively by the R pipeline (``paper/R/``) from a frozen data bundle.

Two products:

1. CHPDT obs-vs-sim 1:1 scatter (log scale, ln(y+1)) per run, with the best
   (lowest-Phi) realization highlighted, plus the ensemble median point cloud.
2. Dry-only vs v4 (CHFPW+CHPDT) posterior parameter comparison: per-parameter
   median shift and best-realization delta, with a paired box plot of the
   ensembles for the most-shifted parameters.

Usage (run from repo root)::

    python tools/reporting/t10_dryonly_diagnostics.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# (label, run_dir, case) -- case is the PST/file prefix (= run id).
DRY_RUNS = {
    "single_25sp": "workspace/runs/eggplant_t10_dryonly_20260723_202942_single_25sp",
    "single_25fa": "workspace/runs/eggplant_t10_dryonly_20260723_202942_single_25fa",
    "joint": "workspace/runs/eggplant_t10_dryonly_20260723_202942_joint",
}
V4_RUNS = {
    "single_25sp": "workspace/runs/eggplant_t10_single_season_diag_20260723_115416_25sp",
    "single_25fa": "workspace/runs/eggplant_t10_single_season_diag_20260723_115416_25fa",
    "joint": "workspace/runs/eggplant_t10_joint_20260723_000453",
}
OUT_DIR = ROOT / "workspace" / "runs" / "t10_dryonly_diagnostics_20260723"


def _load_obs_sim(run_dir: str, case: str):
    """Return (obsnme, obs_vec, sim_ensemble_df, weight_vec) for active CHPDT obs."""
    rd = ROOT / run_dir
    sim_ens = pd.read_csv(rd / f"{case}.4.obs.csv", index_col=0)
    o = pd.read_csv(rd / f"{case}.adjusted.obs_data.csv")
    o["value"] = pd.to_numeric(o["value"], errors="coerce")
    o["weight"] = pd.to_numeric(o["weight"], errors="coerce").fillna(0.0)
    obs_map = dict(zip(o["name"], o["value"]))
    wmap = dict(zip(o["name"], o["weight"]))
    # active CHPDT only
    obsnme = [
        c for c in sim_ens.columns
        if c in obs_map and wmap.get(c, 0.0) > 0.0 and "CHPDT" in c.upper()
    ]
    obs_vec = np.array([obs_map[c] for c in obsnme], dtype=float)
    w_vec = np.array([wmap.get(c, 0.0) for c in obsnme], dtype=float)
    return obsnme, obs_vec, sim_ens[obsnme], w_vec


def _best_real(obs_vec, sim_ens_df, w_vec):
    ok = np.isfinite(obs_vec) & (obs_vec != -99.0)
    phi = ((sim_ens_df.values - obs_vec) ** 2 * w_vec**2)
    phi = pd.Series(np.nansum(np.where(ok, phi, 0.0), axis=1), index=sim_ens_df.index)
    best = phi.idxmin()
    return best, phi.loc[best]


def plot_chpdt_1to1(label: str, run_dir: str, case: str, out_dir: Path) -> Path:
    """CHPDT obs-vs-sim 1:1 scatter on the log (ln(y+1)) calibration scale."""
    obsnme, obs_vec, sim_ens, w_vec = _load_obs_sim(run_dir, case)
    best, best_phi = _best_real(obs_vec, sim_ens, w_vec)
    best_sim = sim_ens.loc[best].values

    # ensemble median + IQR across realizations, per observation
    ens_median = sim_ens.median(axis=0).values
    ens_q25 = sim_ens.quantile(0.25, axis=0).values
    ens_q75 = sim_ens.quantile(0.75, axis=0).values

    fig, ax = plt.subplots(figsize=(5.6, 5.2), dpi=150)
    # ensemble spread: faint band via q25/q75
    ax.fill_between(
        np.sort(obs_vec),
        np.sort(ens_q25),
        np.sort(ens_q75),
        color="#9ecae1",
        alpha=0.35,
        label="ensemble IQR (per obs)",
    )
    ax.scatter(obs_vec, ens_median, s=16, color="#6baed6", alpha=0.6, label="ensemble median", zorder=2)
    ax.scatter(obs_vec, best_sim, s=22, color="#de2d26", alpha=0.85, label=f"best real (#{best})", zorder=3, edgecolor="white", linewidth=0.4)

    vmin = float(np.nanmin([obs_vec.min(), best_sim.min()]))
    vmax = float(np.nanmax([obs_vec.max(), best_sim.max()]))
    pad = 0.04 * (vmax - vmin)
    ax.plot([vmin - pad, vmax + pad], [vmin - pad, vmax + pad], color="black", linewidth=1.0, linestyle="-", zorder=1)
    ax.set_xlim(vmin - pad, vmax + pad)
    ax.set_ylim(vmin - pad, vmax + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Observed CHPDT  ln(y+1)")
    ax.set_ylabel("Simulated CHPDT  ln(y+1)")
    ax.set_title(f"{label}: CHPDT obs vs sim (log scale)\nbest Phi={best_phi:.1f}, n={len(obsnme)}")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

    # residual bias annotation
    resid = best_sim - obs_vec
    me = float(np.mean(resid))
    mae = float(np.mean(np.abs(resid)))
    ax.text(
        0.97, 0.03,
        f"ME={me:+.3f}\nMAE={mae:.3f}",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.85),
    )

    out = out_dir / f"diagnostic_chpdt_obs_vs_sim_{label}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_chpdt_by_season(label: str, run_dir: str, case: str, out_dir: Path) -> Path | None:
    """CHPDT obs-vs-sim colored by season (25SP vs 25FA) for the joint run."""
    if label != "joint":
        return None
    obsnme, obs_vec, sim_ens, w_vec = _load_obs_sim(run_dir, case)
    best, best_phi = _best_real(obs_vec, sim_ens, w_vec)
    best_sim = sim_ens.loc[best].values
    season = np.array(["25FA" if str(n).lower().startswith("25fa") else "25SP" for n in obsnme])

    fig, ax = plt.subplots(figsize=(5.6, 5.2), dpi=150)
    for s, color in (("25SP", "#1f77b4"), ("25FA", "#d62728")):
        m = season == s
        ax.scatter(obs_vec[m], best_sim[m], s=20, color=color, alpha=0.8, label=s, edgecolor="white", linewidth=0.3)
    vmin = float(np.nanmin([obs_vec.min(), best_sim.min()]))
    vmax = float(np.nanmax([obs_vec.max(), best_sim.max()]))
    pad = 0.04 * (vmax - vmin)
    ax.plot([vmin - pad, vmax + pad], [vmin - pad, vmax + pad], color="black", linewidth=1.0)
    ax.set_xlim(vmin - pad, vmax + pad); ax.set_ylim(vmin - pad, vmax + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Observed CHPDT  ln(y+1)"); ax.set_ylabel("Simulated CHPDT  ln(y+1)")
    ax.set_title(f"{label}: CHPDT by season (best real #{best})")
    ax.legend(loc="upper left", fontsize=9)
    out = out_dir / f"diagnostic_chpdt_by_season_{label}.png"
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
    return out


def _load_posterior(run_dir: str, case: str) -> pd.DataFrame:
    rd = ROOT / run_dir
    return pd.read_csv(rd / f"{case}.4.par.csv", index_col=0)


def compare_posteriors(out_dir: Path) -> tuple[Path, Path, pd.DataFrame]:
    """Dry-only vs v4 posterior comparison for the joint run."""
    dry = _load_posterior(DRY_RUNS["joint"], "eggplant_t10_dryonly_20260723_202942_joint")
    v4 = _load_posterior(V4_RUNS["joint"], "eggplant_t10_joint_20260723_000453")
    params = [c for c in dry.columns if c != "real_name" and c in v4.columns]

    rows = []
    for p in params:
        d_med = float(np.median(dry[p].dropna()))
        v_med = float(np.median(v4[p].dropna()))
        rows.append({
            "parameter": p,
            "v4_median": v_med,
            "dryonly_median": d_med,
            "median_shift": d_med - v_med,
            "median_shift_pct": 100 * (d_med - v_med) / v_med if v_med != 0 else float("nan"),
            "v4_iqr": float(v4[p].quantile(0.75) - v4[p].quantile(0.25)),
            "dryonly_iqr": float(dry[p].quantile(0.75) - dry[p].quantile(0.25)),
        })
    comp = pd.DataFrame(rows).sort_values("median_shift_pct", key=lambda s: s.abs(), ascending=False)
    csv_path = out_dir / "diagnostic_posterior_comparison_joint.csv"
    comp.to_csv(csv_path, index=False)

    # box plot of the top-12 most-shifted parameters (normalized to v4 median)
    top = comp.head(12)["parameter"].tolist()
    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=150)
    data, labels, colors = [], [], []
    for p in top:
        base = float(np.median(v4[p].dropna())) or 1.0
        data.append((v4[p].dropna() / base).values)
        labels.append(f"{p}\n(v4 norm)")
        data.append((dry[p[p.find("_AUT"):] if False else p].dropna() / base).values if False else (dry[p].dropna() / base).values)
        labels.append("")
        colors.extend(["#bdbdbd", "#de2d26"])
    positions = []
    pos = 1
    for i in range(len(top)):
        positions.extend([pos, pos + 0.8]); pos += 1.8
    bp = ax.boxplot(data, positions=positions, widths=0.7, patch_artist=True, showfliers=False)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c); patch.set_alpha(0.75)
    # group separator labels
    ax.set_xticks([positions[i * 2] + 0.4 for i in range(len(top))])
    ax.set_xticklabels([p for p in top], rotation=55, ha="right", fontsize=7.5)
    ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.set_ylabel("posterior / v4-median (normalized)")
    ax.set_title("Joint posterior: dry-only vs v4 (CHFPW+CHPDT) — top 12 most-shifted parameters")
    # legend
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#bdbdbd", label="v4 (CHFPW+CHPDT)"), Patch(facecolor="#de2d26", label="dry-only (CHPDT only)")], loc="upper right", fontsize=8)
    fig.tight_layout()
    box_path = out_dir / "diagnostic_posterior_shift_joint.png"
    fig.savefig(box_path, dpi=150); plt.close(fig)
    return csv_path, box_path, comp


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {OUT_DIR}")
    cases = {
        "single_25sp": "eggplant_t10_dryonly_20260723_202942_single_25sp",
        "single_25fa": "eggplant_t10_dryonly_20260723_202942_single_25fa",
        "joint": "eggplant_t10_dryonly_20260723_202942_joint",
    }
    print("\n=== CHPDT obs-vs-sim diagnostic plots ===")
    for label, run_dir in DRY_RUNS.items():
        case = cases[label]
        p = plot_chpdt_1to1(label, run_dir, case, OUT_DIR)
        print(f"  {label}: {p.name}")
        pb = plot_chpdt_by_season(label, run_dir, case, OUT_DIR)
        if pb:
            print(f"  {label} by season: {pb.name}")

    print("\n=== Posterior comparison (dry-only vs v4, joint) ===")
    csv_path, box_path, comp = compare_posteriors(OUT_DIR)
    print(f"  CSV: {csv_path.name}")
    print(f"  Box: {box_path.name}")
    print("\nTop 8 most-shifted parameters (joint, dry-only vs v4):")
    print(comp.head(8)[["parameter", "v4_median", "dryonly_median", "median_shift_pct", "v4_iqr", "dryonly_iqr"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(int(main()))
