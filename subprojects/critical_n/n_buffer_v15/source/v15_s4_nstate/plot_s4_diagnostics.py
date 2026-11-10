#!/usr/bin/env python3
"""plot_s4_diagnostics.py -- fused-state (psi*) diagnostics for the S4 2x2
factor matrix (root_kernel x nstate_mode), Python diagnostic track.

Figures (into --diag-dir):
  diagnostic_s4_psi_4combo.png   growth-state psi trajectories, 4 combos
  diagnostic_s4_psi_fusion.png   S1-basis psi vs fused psi* (+NNI_f axis)
  diagnostic_s4_fresh_2x2.png    fresh-yield water-N response, 4 combos
"""
import argparse
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "v15_s3_v4root"))
from plot_ab_diagnostics import (  # noqa: E402
    treatments, parse_pest_harvest_fresh, WC)

REPO = Path(__file__).resolve().parents[5]
AB = REPO / "workspace/runs/v4root_ab_diag_20261108"

for f in ("/System/Library/Fonts/PingFang.ttc",
          "/System/Library/Fonts/STHeiti Light.ttc"):
    if Path(f).exists():
        try:
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = \
                font_manager.FontProperties(fname=f).get_name()
            break
        except Exception:
            pass
plt.rcParams["axes.unicode_minus"] = False

COMBOS = [
    ("S1 (k1,状态1)", AB / "replay_s1/NDecision.csv", "psi_total", "#999999", ":"),
    ("S3 (k2,状态1)", AB / "replay_s3/NDecision.csv", "psi_total", "#8a8a8a", "--"),
    ("(k1,状态2)", None, "psi_star", "#1f9ec7", "-."),
    ("S4 主推 (k2,状态2)", None, "psi_star", "#1f6fb2", "-"),
]
TRTS = ["W3_N3", "W2_N2", "W1_N0"]


def load_psi(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def s4_rows(diag, tag):
    return load_psi(diag / f"replay_s4_{tag}/NStatePsi.csv")


def fig_4combo(diag):
    meta = treatments()
    by_label = {v[0]: k for k, v in meta.items()}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    k12 = s4_rows(diag, "k1_state2")
    k22 = s4_rows(diag, "k2_state2")
    for j, label in enumerate(TRTS):
        trt = by_label[label]
        ax = axes[j]
        for name, path, key, color, ls in COMBOS:
            if path is not None:
                rows = [r for r in load_psi(path) if int(r["trt"]) == trt]
                vals = [float(r["total_psi"]) for r in rows]
            else:
                rows = [r for r in (k12 if "k1" in name else k22)
                        if int(r["trt"]) == trt]
                vals = [float(r[key]) for r in rows]
            das = [int(r["das"]) for r in rows]
            ax.plot(das, vals, ls, color=color, label=name, lw=1.6)
        ax.axhline(0, color="k", lw=.6)
        ax.set_title(label, fontsize=10)
        ax.set_ylabel("生长侧氮状态" if j == 0 else "")
        ax.set_xlabel("DAS")
        ax.grid(alpha=.3)
        if j == 0:
            ax.legend(fontsize=7.5, loc="lower left")
    fig.suptitle("diagnostic_S4 氮状态 2×2 因子：ψ 轨迹（率定最优成员重放）",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_s4_psi_4combo.png", dpi=150)
    plt.close(fig)


def fig_fusion(diag):
    meta = treatments()
    by_label = {v[0]: k for k, v in meta.items()}
    s3 = load_psi(AB / "replay_s3/NDecision.csv")
    s4 = s4_rows(diag, "k2_state2")
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for j, label in enumerate(TRTS):
        trt = by_label[label]
        r3 = [r for r in s3 if int(r["trt"]) == trt]
        r4 = [r for r in s4 if int(r["trt"]) == trt]
        ax = axes[j]
        ax.plot([int(r["das"]) for r in r3],
                [float(r["total_psi"]) for r in r3], "--", color="#8a8a8a",
                label="S1 基准 ψ（总氮）")
        ax.plot([int(r["das"]) for r in r4],
                [float(r["psi_star"]) for r in r4], "-", color="#1f6fb2",
                label="融合 ψ*（功能氮）")
        ax.axhline(0, color="k", lw=.6)
        ax.set_ylim(-1.05, 1.05)
        ax.set_title(label, fontsize=10)
        ax.set_ylabel("氮状态" if j == 0 else "")
        ax.set_xlabel("DAS")
        ax.grid(alpha=.3)
        if j == 0:
            ax.legend(fontsize=8, loc="lower left")
        ax2 = ax.twinx()
        ax2.plot([int(r["das"]) for r in r4],
                 [float(r["nni_func"]) for r in r4], ":", color="#d95f02",
                 lw=1)
        ax2.set_ylabel("NNI_f", color="#d95f02", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="#d95f02", labelsize=7)
        ax2.set_ylim(0, 2.1)
    fig.suptitle("diagnostic_状态融合：总氮基准假奢侈 vs 功能氮 ψ*（同核 k2 同参数）"
                 " · NNI_f 副轴", fontsize=12)
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_s4_psi_fusion.png", dpi=150)
    plt.close(fig)


def fig_fresh(diag):
    meta = treatments()
    norder = ["N0", "N1", "N2", "N3"]
    srcs = [
        ("(k1,状态1) S1", AB / "replay_s1/PestHarvest.OUT"),
        ("(k2,状态1) S3", AB / "replay_s3/PestHarvest.OUT"),
        ("(k1,状态2)", diag / "replay_s4_k1_state2/PestHarvest.OUT"),
        ("(k2,状态2) S4", diag / "replay_s4_k2_state2/PestHarvest.OUT"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 8), sharex=True,
                             sharey=True)
    csv_rows = []
    for idx, (tag, path) in enumerate(srcs):
        ax = axes[idx // 2][idx % 2]
        fresh = parse_pest_harvest_fresh(path)
        vals = {}
        for trt, v in fresh.items():
            if trt in meta:
                vals.setdefault(meta[trt][1], {})[meta[trt][2]] = v
        for w in ("W1", "W2", "W3"):
            ys = [vals.get(w, {}).get(n) for n in norder]
            ax.plot(range(4), ys, "o-", color=WC[w], label=w)
            for i, v in enumerate(ys):
                if v is not None:
                    csv_rows.append([tag, w, norder[i], v])
        ax.set_title(tag, fontsize=10)
        ax.grid(alpha=.3)
        if idx // 2 == 1:
            ax.set_xticks(range(4))
            ax.set_xticklabels(norder)
        if idx % 2 == 0:
            ax.set_ylabel("鲜果产量 CHFPWS (kg/ha)")
        if idx == 0:
            ax.legend(title="水分", fontsize=8)
    fig.suptitle("diagnostic_鲜果产量水氮响应：root_kernel × nstate_mode 2×2",
                 fontsize=12)
    fig.supxlabel("施氮水平")
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_s4_fresh_2x2.png", dpi=150)
    plt.close(fig)
    with (diag / "diagnostic_s4_fresh_2x2_data.csv").open("w",
                                                          newline="") as f:
        w = csv.writer(f)
        w.writerow(["combo", "water", "nitrogen", "fresh_yield_kg_ha"])
        w.writerows(csv_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diag-dir", required=True)
    args = ap.parse_args()
    diag = Path(args.diag_dir).resolve()
    fig_4combo(diag)
    fig_fusion(diag)
    fig_fresh(diag)
    print("figures written to", diag)


if __name__ == "__main__":
    main()
