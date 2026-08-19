"""Apply the approved replicate-exclusion scheme (2026-08-18) and build
_repfilter_v1 bundles.

Per docs/重复剔除方案_20260818.md (user-approved 2026-08-18):
- Channel 1 (statistical single-variable anomalies): 10 value-level removals
- Channel 2 (field-confirmed non-representative plants): 2 whole-plant + 3
  value-level removals

Execution contract (user-approved):
- Source xlsx gain a `剔除标记` column — NO row deletion, NO value edits
- New bundle copies `*_repfilter_v1_20260818` with affected observations
  recomputed from the remaining replicates (exact linear rescaling by the
  treatment's density factor), FileT_values.csv / TMT /
  observation_uncertainty.csv updated in lockstep
- Original v8/v7 bundles and all frozen calibration results untouched

Usage:
    python tools/experiments/apply_repfilter_v1_20260818.py --dry-run | --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
X25 = ROOT / "data/user/ref/DSSAT文件/2025春/2025春作物生长指标集.xlsx"
X26 = ROOT / "data/user/ref/DSSAT文件/2026春/2026春生长指标集.xlsx"
B25 = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"
B26 = ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"
NEW25 = ROOT / "data/user/experiments/xxql2501_repfilter_v1_20260818"
NEW26 = ROOT / "data/user/experiments/xxql2601_repfilter_v1_20260818"

VAR_MAP = {"株高": "CHTD", "茎干重": "SWAD", "叶干重": "LWAD", "LAI": "LAID"}
SHEET26 = {"0502": "26122", "0602": "26153", "0629": "26180", "0717": "26198"}

# (season, plot, date, target, rep_id, channel)
REMOVALS = [
    # ── channel 1: single-variable anomalies (statistical) ──
    ("25SP", 1,  "25120", "茎干重", "中间行2", 1),
    ("25SP", 4,  "25142", "茎干重", "中间行2", 1),
    ("25SP", 6,  "25120", "LAI",   "中间行2", 1),
    ("25SP", 6,  "25142", "叶干重", "中间行2", 1),
    ("25SP", 8,  "25170", "LAI",   "边行",   1),
    ("26SP", 11, "0502",  "LAI",   "rep3",   1),
    ("26SP", 1,  "0717",  "茎干重", "rep2",   1),
    ("26SP", 2,  "0717",  "茎干重", "rep3",   1),
    ("26SP", 3,  "0717",  "LAI",   "rep1",   1),
    ("26SP", 9,  "0717",  "叶干重", "rep2",   1),
    # ── channel 2: field-confirmed non-representative ──
    ("25SP", 3,  "25194", "plant", "中间行1", 2),
    ("25SP", 13, "25170", "LAI",   "中间行2", 2),
    ("26SP", 2,  "0629",  "plant", "rep3",   2),
    ("26SP", 5,  "0629",  "叶干重", "rep3",   2),
    ("26SP", 4,  "0629",  "叶干重", "rep3",   2),
]
# 25SP plots 1/6/7/8 are excluded from calibration TNs; marks still go to source.
INCLUDED_25SP = {2, 3, 4, 5, 9, 10, 11, 12, 13, 14}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rep_key_25(row) -> str:
    return str(row["行位置"])


def rep_key_26(rep: int) -> str:
    return f"rep{int(rep)}"


def load_25() -> pd.DataFrame:
    df = pd.ExcelFile(X25).parse("Sheet1")
    df["doy"] = pd.to_datetime(df["日期"]).dt.strftime("%y%j")
    return df


def load_26(sheet: str) -> pd.DataFrame:
    df = pd.ExcelFile(X26).parse(sheet)
    trcol = "小区" if sheet == "0502" else ("处理 (Treatment)" if sheet == "0629" else "处理")
    df = df.rename(columns={trcol: "plot"})
    return df


def vars_for(target: str, available: list[str]) -> list[str]:
    if target == "plant":
        return [v for v in ("株高", "茎干重", "叶干重", "LAI") if v in available]
    return [target]


def affected_vars(season: str, date: str) -> list[str]:
    if season == "25SP":
        return ["株高", "茎干重", "叶干重", "LAI"]
    specs = {"0502": ["株高", "茎干重", "叶干重", "LAI"], "0602": ["株高 (cm)", "茎干重", "叶干重", "LAI"],
             "0629": ["株高 (Plant Height / cm)", "茎干重", "叶干重"], "0717": ["株高 (cm)", "茎干重", "叶干重", "LAI"]}
    return specs[date]


def base_colname(var: str) -> str:
    return var.split(" ")[0].split("(")[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not (args.dry_run or args.apply):
        parser.error("choose --dry-run or --apply")

    # ── 1. compute new means/sds from raw data ──
    df25 = load_25()
    updates: list[dict] = []
    for season, plot, date, target, rep_id, channel in REMOVALS:
        if season == "25SP":
            g = df25[(df25.小区号 == plot) & (df25.doy == date)].copy()
            g["_rep"] = g.apply(rep_key_25, axis=1)
            avail = ["株高", "茎干重", "叶干重", "LAI"]
            varcols = {v: v for v in avail}
        else:
            g = load_26(date)
            g = g[g["plot"] == plot].copy()
            g["_rep"] = g["重复"].apply(rep_key_26)
            avail = affected_vars(season, date)
            varcols = {v: c for v, c in zip([base_colname(c) for c in avail], avail)}
        for var in vars_for(target, [base_colname(c) for c in avail]):
            col = varcols[var]
            vals = pd.to_numeric(g[col], errors="coerce")
            old_mean = float(vals.mean())
            keep = g["_rep"] != rep_id
            new_mean = float(vals[keep].mean())
            new_sd = float(vals[keep].std(ddof=1)) if keep.sum() >= 2 else float("nan")
            old_sd = float(vals.std(ddof=1))
            updates.append({
                "season": season, "plot": plot, "date": date, "var": var, "rep": rep_id,
                "channel": channel, "old_mean": old_mean, "new_mean": new_mean,
                "old_sd": old_sd, "new_sd": new_sd, "n_new": int(keep.sum()),
                "in_calibration": (season == "26SP") or (plot in INCLUDED_25SP),
                "doy": date if season == "25SP" else SHEET26[date],
            })

    print(f"{'season':6s} {'plot':>4s} {'doy':6s} {'var':5s} {'rep':8s} ch  old_mean  new_mean   change")
    for u in updates:
        chg = (u["new_mean"] / u["old_mean"] - 1) * 100 if u["old_mean"] else float("nan")
        star = "" if u["in_calibration"] else "  (excluded-TN, source mark only)"
        print(f"{u['season']:6s} {u['plot']:>4d} {u['doy']:6s} {u['var']:5s} {u['rep']:8s} "
              f"{u['channel']}   {u['old_mean']:8.2f} {u['new_mean']:8.2f} {chg:+7.1f}%{star}")

    if args.dry_run:
        print("\n[dry-run] no files modified")
        return 0

    # ── 2. mark source xlsx ──
    # The mark column position is derived from the ORIGINAL header only, so
    # repeated runs write to one fixed column instead of marching rightward.
    def mark(ws, header_row: int, find_row, tag: str, mark_col: int) -> None:
        if ws.cell(row=header_row, column=mark_col).value != "剔除标记":
            ws.cell(row=header_row, column=mark_col, value="剔除标记")
        r = find_row()
        if r is None:
            raise RuntimeError("row not found for marking")
        ws.cell(row=r, column=mark_col, value=tag)

    def mark_col_of(ws) -> int:
        hdr = {c.value: c.column for c in ws[1]}
        existing = [col for name, col in hdr.items()
                    if name is not None and str(name).split(".")[0] == "剔除标记"]
        return existing[0] if existing else max(col for name, col in hdr.items()
                                                if name is not None and str(name) != "剔除标记") + 1

    tag = {1: "剔除:{}:通道1-单变量异常:20260818", 2: "剔除:{}:通道2-非代表性样株(用户田间确认):20260818"}
    wb25 = load_workbook(X25)
    ws25 = wb25["Sheet1"]
    hdr25 = {c.value: c.column for c in ws25[1]}
    mc25 = mark_col_of(ws25)
    for season, plot, date, target, rep_id, channel in [r for r in REMOVALS if r[0] == "25SP"]:
        target_vars = vars_for(target, ["株高", "茎干重", "叶干重", "LAI"])
        joined = "+".join(target_vars) if target != "plant" else "整株"
        t = tag[channel].format(joined)
        def find_row(p=plot, d=date, rp=rep_id):
            import datetime as dt
            dd = dt.datetime.strptime("20" + d, "%Y%j")
            for r in range(2, ws25.max_row + 1):
                if ws25.cell(row=r, column=hdr25["小区号"]).value == p \
                        and ws25.cell(row=r, column=hdr25["日期"]).value == dd \
                        and ws25.cell(row=r, column=hdr25["行位置"]).value == rp:
                    return r
            return None
        mark(ws25, 1, find_row, t, mc25)
    wb25.save(X25)
    print("marked 25SP xlsx")

    wb26 = load_workbook(X26)
    for season, plot, date, target, rep_id, channel in [r for r in REMOVALS if r[0] == "26SP"]:
        ws = wb26[date]
        joined = "+".join(vars_for(target, [base_colname(c) for c in affected_vars("26SP", date)])) \
            if target != "plant" else "整株"
        t = tag[channel].format(joined)
        repno = int(rep_id.replace("rep", ""))
        hdr = {c.value: c.column for c in ws[1]}
        trcol = "小区" if date == "0502" else ("处理 (Treatment)" if date == "0629" else "处理")
        mc = mark_col_of(ws)
        def find_row(p=plot, rn=repno, w=ws, h=hdr, tc=trcol):
            for r in range(2, w.max_row + 1):
                if w.cell(row=r, column=h[tc]).value == p and w.cell(row=r, column=h["重复"]).value == rn:
                    return r
            return None
        mark(ws, 1, find_row, t, mc)
    wb26.save(X26)
    print("marked 26SP xlsx")

    # ── 3. build repfilter bundles ──
    for src, dst in ((B25, NEW25), (B26, NEW26)):
        if dst.exists():
            raise FileExistsError(dst)
        shutil.copytree(src, dst)

    def update_filet(bundle: Path, u: dict, value: float) -> None:
        path = bundle / "FileT_values.csv"
        ft = pd.read_csv(path)
        doys = pd.to_datetime(ft["DATE"]).dt.strftime("%y%j")
        m = (ft["TRNO"] == u["plot"]) & (doys == u["doy"])
        assert int(m.sum()) == 1, (u, m.sum())
        ft.loc[m, VAR_MAP[u["var"]]] = value
        ft.to_csv(path, index=False)

    def update_tmt(bundle: Path, excode: str, u: dict, value: float) -> None:
        path = bundle / f"{excode}.TMT"
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        idx = next(i for i, l in enumerate(lines) if l.startswith("@"))
        hdr = [c.lstrip("@") for c in lines[idx].split()]
        # hdr tokens align 1:1 with row tokens (hdr[0] is '@TRNO' -> 'TRNO')
        vi = hdr.index(VAR_MAP[u["var"]])
        hit = 0
        for i in range(idx + 1, len(lines)):
            parts = lines[i].split()
            if len(parts) < len(hdr) or not parts[0].lstrip("-").isdigit():
                continue
            if int(parts[0]) == u["plot"] and parts[1] == u["doy"]:
                old = parts[vi]
                if old == "-99" or float(old) <= -99:
                    raise AssertionError(f"target cell missing in TMT: {u} col {hdr[vi]}")
                width = len(old)
                dec = len(old.split(".")[1]) if "." in old else 0
                parts[vi] = f"{value:{width}.{dec}f}" if dec else f"{value:{width}.0f}"
                lines[i] = " ".join(parts)
                hit += 1
        assert hit == 1, (u, hit)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def update_uncertainty(bundle: Path, season: str, excode: str, u: dict, value: float, sd: float) -> None:
        path = bundle / "observation_uncertainty.csv"
        un = pd.read_csv(path)
        m = (un["trno"] == u["plot"]) & (un["date"].astype(str) == u["doy"]) \
            & (un["variable"] == VAR_MAP[u["var"]])
        assert int(m.sum()) == 1, (u, m.sum())
        un.loc[m, "value"] = value
        un.loc[m, "raw_sd"] = sd
        un.loc[m, "n_rep"] = u["n_new"]
        un.loc[m, "quality_flag"] = "repfilter_20260818"
        un.to_csv(path, index=False)

    scale_cache: dict[tuple, float] = {}
    for u in updates:
        if not u["in_calibration"]:
            continue
        bundle = NEW25 if u["season"] == "25SP" else NEW26
        excode = "XXQL2501" if u["season"] == "25SP" else "XXQL2601"
        key = (u["season"], u["plot"], VAR_MAP[u["var"]])
        ft = pd.read_csv(bundle / "FileT_values.csv")
        doys = pd.to_datetime(ft["DATE"]).dt.strftime("%y%j")
        m = (ft["TRNO"] == u["plot"]) & (doys == u["doy"])
        old_ft = float(ft.loc[m, VAR_MAP[u["var"]]].iloc[0])
        scale = old_ft / u["old_mean"] if u["old_mean"] else 1.0
        new_ft = u["new_mean"] * scale
        new_sd = u["new_sd"] * scale if math.isfinite(u["new_sd"]) else u["old_sd"] * scale
        update_filet(bundle, u, new_ft)
        update_tmt(bundle, excode, u, new_ft)
        update_uncertainty(bundle, u["season"], excode, u, new_ft, new_sd)
        scale_cache[key] = scale

    print(f"bundle updates applied: {sum(1 for u in updates if u['in_calibration'])} values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
