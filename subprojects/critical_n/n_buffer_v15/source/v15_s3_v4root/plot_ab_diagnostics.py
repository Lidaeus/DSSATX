#!/usr/bin/env python3
"""plot_ab_diagnostics.py -- water-N response diagnostic figures from the
calibrated S1 / S3(v4-R2) replays (Python diagnostic track: diagnostic_*
outputs only; not paper figures).

Inputs : --diag-dir containing replay_s1/ replay_s3/ (from replay_calibrated.py)
Outputs: diagnostic_*.png + diagnostic_*_data.csv in the same directory.
"""
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

REPO = Path(__file__).resolve().parents[5]
BUNDLE = REPO / "data/user/experiments/xxql2601_final_sasc70_20261106"

# ---- Chinese font (diagnostics only) -----------------------------------
for f in ("/System/Library/Fonts/PingFang.ttc",
          "/System/Library/Fonts/STHeiti Light.ttc",
          "/System/Library/Fonts/Hiragino Sans GB.ttc"):
    if Path(f).exists():
        try:
            font_manager.fontManager.addfont(f)
            name = font_manager.FontProperties(fname=f).get_name()
            plt.rcParams["font.family"] = name
            break
        except Exception:
            pass
plt.rcParams["axes.unicode_minus"] = False

S1C, S3C = "#8a8a8a", "#1f6fb2"
WC = {"W1": "#d95f02", "W2": "#e6a018", "W3": "#1b9e77"}


def treatments():
    meta = {}
    with (BUNDLE / "treatment_metadata.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            meta[int(r["treatment"])] = (r["treatment_label"],
                                         r["water_level"], r["nitrogen_level"])
    return meta


def parse_evaluate(path):
    rows = []
    lines = path.read_text(errors="replace").splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("@"):
            head = ln[1:].split()
            for d in lines[i + 1:]:
                if not d.strip():
                    continue
                if d.startswith("*") or d.startswith("$") or d.startswith("!"):
                    break
                parts = d.split()
                if len(parts) == len(head):
                    rows.append(dict(zip(head, parts)))
            break
    return rows


def parse_plantgro(path):
    """-> {trt: {"das": [...], "LAI": [...], "CWAD": [...]}}"""
    out = {}
    cur = None
    head = None
    for ln in path.read_text(errors="replace").splitlines():
        m = re.match(r"^\*RUN\s+(\d+)\s+:\s+(\S+)", ln)
        if m:
            cur = int(m.group(1))
            out[cur] = {"das": [], "LAI": [], "CWAD": [], "LWAD": [],
                        "SWAD": []}
            head = None
            continue
        if ln.startswith("@"):
            head = ln[1:].split()
            continue
        if head and cur and ln.lstrip()[:1].isdigit() and ln.strip():
            p = ln.split()
            if len(p) != len(head):
                continue
            r = dict(zip(head, p))
            try:
                out[cur]["das"].append(int(r["DAS"]))
                out[cur]["LAI"].append(float(r["LAID"]))
                out[cur]["CWAD"].append(float(r["CWAD"]))
                out[cur]["LWAD"].append(float(r["LWAD"]))
                out[cur]["SWAD"].append(float(r["SWAD"]))
            except (KeyError, ValueError):
                pass
    return out


def parse_csv_dicts(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def fnum(x):
    return float(x)


def fig_wn_response(diag, ev1, ev3, meta):
    metrics = [("PWAMS", "果重 PWAMS (kg/ha)", "fruit"),
               ("CWAMS", "地上生物量 CWAMS (kg/ha)", "biomass"),
               ("CNAMS", "植株氮 CNAMS (kg/ha)", "plantn")]
    norder = ["N0", "N1", "N2", "N3"]
    fig, axes = plt.subplots(3, 2, figsize=(10.5, 10), sharex=True)
    csv_rows = []
    for row, (key, title, slug) in enumerate(metrics):
        for col, (tag, ev) in enumerate((("S1 相加核", ev1), ("S3 v4-R2 联立核", ev3))):
            ax = axes[row][col]
            vals = {}
            for r in ev:
                trt = int(r["TN"])
                if trt in meta:
                    vals.setdefault(meta[trt][1], {})[meta[trt][2]] = \
                        fnum(r[key])
            for w in ("W1", "W2", "W3"):
                ys = [vals.get(w, {}).get(n) for n in norder]
                ax.plot(range(4), ys, "o-", color=WC[w], label=w)
                for i, v in enumerate(ys):
                    if v is not None:
                        csv_rows.append([slug, tag, w, norder[i], v])
            if row == 0:
                ax.set_title(tag, fontsize=11)
            if col == 0:
                ax.set_ylabel(title, fontsize=10)
            ax.grid(alpha=.3)
            if row == 0 and col == 0:
                ax.legend(title="水分", fontsize=8)
    axes[-1][0].set_xticks(range(4))
    axes[-1][0].set_xticklabels(norder)
    axes[-1][1].set_xticks(range(4))
    axes[-1][1].set_xticklabels(norder)
    fig.suptitle("diagnostic_水氮响应：率定最优成员确定性重放（S1 vs S3）"
                 " · engineering_validated", fontsize=12)
    fig.supxlabel("施氮水平", fontsize=10)
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_v4root_ab_wn_response.png", dpi=150)
    plt.close(fig)
    with (diag / "diagnostic_v4root_ab_wn_response_data.csv").open(
            "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "kernel", "water", "nitrogen", "value"])
        w.writerows(csv_rows)


def fig_trajectories(diag, pg1, pg3, nd1, nd3, meta):
    trts = pick_representative(meta)
    fig, axes = plt.subplots(3, 3, figsize=(13, 9))
    csv_rows = []
    for j, trt in enumerate(trts):
        label = meta[trt][0]
        a = axes[0][j]
        a.plot(pg1[trt]["das"], pg1[trt]["LAI"], "--", color=S1C,
               label="S1")
        a.plot(pg3[trt]["das"], pg3[trt]["LAI"], "-", color=S3C,
               label="S3")
        a.set_title(f"{label}", fontsize=10)
        a.set_ylabel("LAI" if j == 0 else "")
        a.grid(alpha=.3)
        if j == 0:
            a.legend(fontsize=8)

        a = axes[1][j]
        a.plot(pg1[trt]["das"], pg1[trt]["CWAD"], "--", color=S1C)
        a.plot(pg3[trt]["das"], pg3[trt]["CWAD"], "-", color=S3C)
        a.set_ylabel("地上生物量 (kg/ha)" if j == 0 else "")
        a.grid(alpha=.3)

        a = axes[2][j]
        for tag, nd, c, ls in (("S1", nd1, S1C, "--"), ("S3", nd3, S3C, "-")):
            rows = [r for r in nd if int(r["trt"]) == trt]
            das = [int(r["das"]) for r in rows]
            pn = [10 * (fnum(r["leaf_total_n"]) + fnum(r["stem_total_n"]))
                  for r in rows]
            a.plot(das, pn, ls, color=c)
            for d, v in zip(das, pn):
                csv_rows.append([label, tag, d, v])
        a.set_ylabel("地上部植株N (kg/ha)" if j == 0 else "")
        a.set_xlabel("DAS")
        a.grid(alpha=.3)
    fig.suptitle("diagnostic_过程曲线：LAI / 生物量 / 植株氮（率定最优成员重放）",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_v4root_ab_trajectories.png", dpi=150)
    plt.close(fig)
    with (diag / "diagnostic_v4root_ab_trajectories_data.csv").open(
            "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["treatment", "kernel", "das", "shoot_n_kg_ha"])
        w.writerows(csv_rows)


def pick_representative(meta):
    want = ["W3_N3", "W2_N2", "W1_N0"]
    by_label = {v[0]: k for k, v in meta.items()}
    return [by_label[w] for w in want if w in by_label]


def daily_uptake(nd_rows, trt):
    by_day = defaultdict(float)
    das_day = {}
    for r in nd_rows:
        if int(r["trt"]) != trt:
            continue
        d = int(r["das"])
        by_day[d] += fnum(r["actual_kgN_ha"])
        das_day[d] = int(r["yrdoy"])
    days = sorted(by_day)
    return days, [by_day[d] for d in days]


def fig_root_uptake(diag, nd1, nd3, ledger3, meta):
    reps = pick_representative(meta)       # [W3_N3, W2_N2, W1_N0]
    trts = [reps[0], reps[-1]]             # highest vs lowest input
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    csv_rows = []
    for j, trt in enumerate(trts):
        label = meta[trt][0]
        d1, u1 = daily_uptake(nd1, trt)
        d3, u3 = daily_uptake(nd3, trt)
        a = axes[0][j]
        a.plot(d1, u1, "--", color=S1C, label="S1")
        a.plot(d3, u3, "-", color=S3C, label="S3")
        a.set_title(f"{label}", fontsize=10)
        a.set_ylabel("根系吸氮速率 (kg N/ha/d)" if j == 0 else "")
        a.grid(alpha=.3)
        a.legend(fontsize=8)
        for d, v in zip(d1, u1):
            csv_rows.append([label, "S1", d, v, "", "", ""])
        for d, v in zip(d3, u3):
            csv_rows.append([label, "S3", d, v, "", "", ""])

        a = axes[1][j]
        c1 = _cumsum(u1)
        c3 = _cumsum(u3)
        a.plot(d1, c1, "--", color=S1C)
        a.plot(d3, c3, "-", color=S3C)
        a.set_ylabel("累计吸氮量 (kg N/ha)" if j == 0 else "")
        a.set_xlabel("DAS")
        a.grid(alpha=.3)
        for d, v in zip(d3, c3):
            csv_rows.append([label, "S3cum", d, v, "", "", ""])

    # S3 kernel internals: supply composition + rhizosphere drawdown
    a = axes[0][2]
    a2 = axes[1][2]
    if ledger3:
        days, mf, df, ratio = ledger_supply(ledger3, trts[0])
        a.stackplot(days, mf, df, labels=["质流 mf", "扩散 diffusion"],
                    colors=["#f0a30a", "#7aa6d9"], alpha=.85)
        a.set_title(f"{meta[trts[0]][0]} · S3 供给构成", fontsize=10)
        a.set_ylabel("供给通量 (g N/m²/d)")
        a.legend(fontsize=8, loc="upper left")
        a.grid(alpha=.3)
        for d, m, v in zip(days, mf, df):
            csv_rows.append(["supply", "S3", d, m + v, m, v, ""])
        a2.plot(days, ratio, "-", color=S3C)
        a2.set_ylabel("根表浓度比 cr/C")
        a2.set_xlabel("DAS")
        a2.set_ylim(0, 1)
        a2.grid(alpha=.3)
        for d, v in zip(days, ratio):
            csv_rows.append(["cr_ratio", "S3", d, v, "", "", ""])
    fig.suptitle("diagnostic_根系吸氮：速率/累计（S1 vs S3）与 S3 联立核供给机制",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_v4root_ab_root_uptake.png", dpi=150)
    plt.close(fig)
    with (diag / "diagnostic_v4root_ab_root_uptake_data.csv").open(
            "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["series", "kernel", "das", "value", "massflow",
                    "diffusion", "note"])
        w.writerows(csv_rows)


def _cumsum(xs):
    out, s = [], 0.0
    for x in xs:
        s += x
        out.append(s)
    return out


def ledger_supply(ledger_rows, trt_idx0):
    """RootKernelLedger has no trt column; blocks are delimited by
    day_index resets. Extract block trt_idx0 (0-based)."""
    blocks, cur = [], None
    for r in ledger_rows:
        d = int(r["day_index"])
        if d == 1:
            cur = []
            blocks.append(cur)
        if cur is not None:
            cur.append(r)
    blk = blocks[trt_idx0]
    by_day = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # mf, diff, C, cr*w
    for r in blk:
        d = int(r["day_index"])
        mf = fnum(r["mf_g_m2_d"])
        df = fnum(r["diffusion_g_m2_d"])
        c = fnum(r["c_mgN_L"])
        cr = fnum(r["cr_mgN_L"])
        by_day[d][0] += mf
        by_day[d][1] += df
        by_day[d][2] += c
        by_day[d][3] += cr
    days = sorted(by_day)
    mf = [by_day[d][0] for d in days]
    df = [by_day[d][1] for d in days]
    ratio = [by_day[d][3] / by_day[d][2] if by_day[d][2] > 0 else 0
             for d in days]
    return days, mf, df, ratio


def fig_psi(diag, nd1, nd3, meta):
    trts = pick_representative(meta)
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    csv_rows = []
    for j, trt in enumerate(trts):
        a = axes[j]
        for tag, nd, c, ls in (("S1", nd1, S1C, "--"), ("S3", nd3, S3C, "-")):
            rows = [r for r in nd if int(r["trt"]) == trt]
            a.plot([int(r["das"]) for r in rows],
                   [fnum(r["total_psi"]) for r in rows], ls, color=c,
                   label=tag)
            for r in rows:
                csv_rows.append([meta[trt][0], tag, int(r["das"]),
                                 fnum(r["total_psi"])])
        a.axhline(0, color="k", lw=.6)
        a.set_title(meta[trt][0], fontsize=10)
        a.set_ylabel("植株氮状态 ψ" if j == 0 else "")
        a.set_xlabel("DAS")
        a.grid(alpha=.3)
        if j == 0:
            a.legend(fontsize=8)
    fig.suptitle("diagnostic_植株氮状态 ψ（<0 亏缺 / >0 奢侈）", fontsize=12)
    fig.tight_layout()
    fig.savefig(diag / "diagnostic_v4root_ab_psi.png", dpi=150)
    plt.close(fig)
    with (diag / "diagnostic_v4root_ab_psi_data.csv").open("w",
                                                           newline="") as f:
        w = csv.writer(f)
        w.writerow(["treatment", "kernel", "das", "total_psi"])
        w.writerows(csv_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diag-dir", required=True)
    args = ap.parse_args()
    diag = Path(args.diag_dir).resolve()
    meta = treatments()
    ev1 = parse_evaluate(diag / "replay_s1/Evaluate.OUT")
    ev3 = parse_evaluate(diag / "replay_s3/Evaluate.OUT")
    pg1 = parse_plantgro(diag / "replay_s1/PlantGro.OUT")
    pg3 = parse_plantgro(diag / "replay_s3/PlantGro.OUT")
    nd1 = parse_csv_dicts(diag / "replay_s1/RootNSupply.csv")
    nd3 = parse_csv_dicts(diag / "replay_s3/RootNSupply.csv")
    dec1 = parse_csv_dicts(diag / "replay_s1/NDecision.csv")
    dec3 = parse_csv_dicts(diag / "replay_s3/NDecision.csv")
    ledger3 = []
    led = diag / "replay_s3/RootKernelLedger.csv"
    if led.is_file():
        ledger3 = parse_csv_dicts(led)

    fig_wn_response(diag, ev1, ev3, meta)
    fig_trajectories(diag, pg1, pg3, dec1, dec3, meta)
    fig_root_uptake(diag, nd1, nd3, ledger3, meta)
    fig_psi(diag, dec1, dec3, meta)
    print("figures written to", diag)


if __name__ == "__main__":
    main()
