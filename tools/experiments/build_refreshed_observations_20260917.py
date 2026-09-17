#!/usr/bin/env python3
"""Build refreshed DSSAT FileA/FileT + observation uncertainty tables for 25SP and 26SP.

Complies with docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md:
  - 25SP raw workbooks:
      产量: 2025春/2025春产量数据集.xlsx (standard column: 产量（千克每公顷）)
      生长: 2025春/2025春作物生长指标集.xlsx (with APPROVED_REMOVALS)
      品质: 2025春/2025春品质集优先采用品质集中的果实含水率.xlsx
      植株氮: 2025春/2025年春季茄子植株样氮磷钾测定.xlsx (D6=B: SNAD, LNAD, SNAM included)
      D8=A: 9 real harvests + 1 virtual harvest (25198); post-25198 truncated.
  - 26SP raw workbooks:
      产量: 2026春/2026春产量集.xlsx
      生长: 2026春/2026春生长指标集结果.xlsx (with APPROVED_REMOVALS and 26180 LAI imputation)
      品质: 2026春/2026春品质指标集.xlsx (半果含水率)
  - Strict FileA/FileT 6-char fixed-width formatting.
  - CHTD converted from cm to m (/ 100.0) for DSSAT standard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MISSING = -99.0
DENSITY = 27000.0  # plants/ha
FACTOR = DENSITY / 1000.0  # g/plant -> kg/ha (27.0)

SPRING25_INCLUDED_TN = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]
SPRING25_EXCLUDED_TN = [1, 7, 8]
SPRING25_EXCLUSION_REASON = "缺少实际 FileX 管理/初始条件定义"

# Approved replicate removals (docs/重复剔除方案_20260818.md)
APPROVED_REMOVALS = [
    ("25SP", 1, "25120", "茎干重", "中间行2", 1),
    ("25SP", 4, "25142", "茎干重", "中间行2", 1),
    ("25SP", 6, "25120", "LAI", "中间行2", 1),
    ("25SP", 6, "25142", "叶干重", "中间行2", 1),
    ("25SP", 8, "25170", "LAI", "边行", 1),
    ("26SP", 11, "0502", "LAI", "rep3", 1),
    ("26SP", 1, "0717", "茎干重", "rep2", 1),
    ("26SP", 2, "0717", "茎干重", "rep3", 1),
    ("26SP", 3, "0717", "LAI", "rep1", 1),
    ("26SP", 9, "0717", "叶干重", "rep2", 1),
    ("25SP", 3, "25194", "plant", "中间行1", 2),
    ("25SP", 13, "25170", "LAI", "中间行2", 2),
    ("26SP", 2, "0629", "plant", "rep3", 2),
    ("26SP", 5, "0629", "叶干重", "rep3", 1),
    ("26SP", 4, "0629", "叶干重", "rep3", 1),
    ("26SP", 7, "0629", "叶干重", "rep1", 1),
]
REMOVAL_FLAG = "repfilter_20260819"

# 26SP 26180 LAI imputation (user-approved R=18.52)
LAI_IMPUTED = {1: 2.646, 2: 2.912, 3: 2.629, 4: 3.079, 5: 3.113, 6: 2.143,
               7: 2.775, 8: 3.142, 9: 2.053, 10: 2.026, 11: 2.590, 12: 2.735}
LAI_IMPUTED_SD = {1: 0.678, 2: 0.447, 3: 0.842, 4: 0.508, 5: 0.297, 6: 0.387,
                  7: 0.220, 8: 0.340, 9: 0.243, 10: 0.349, 11: 0.717, 12: 0.357}
LAI_IMPUTED_N = {1: 3, 2: 2, 3: 3, 4: 2, 5: 2, 6: 3, 7: 2, 8: 3, 9: 3, 10: 3, 11: 3, 12: 3}

TMA_COLUMNS = ["TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "HWAM", "LWAM", "SWAM", "LAIX", "HIAM", "SNAM", "CNAM"]
TMT_COLUMNS = [
    "TRNO", "DATE", "L#SD", "LAID", "L#PA", "LWAD", "RWAD", "SWAD",
    "M#AD", "SLAD", "CHTD", "CWID", "CNAM", "SNAM", "LNAM",
    "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
]

DECIMALS = {"LAID": 3, "LAIX": 3, "CHTD": 3, "PDMCD": 3, "HIAM": 3}
INTEGER_COLS = {
    "TRNO", "DATE", "PDAT", "ADAT", "MDAT", "HDAT",
    "L#SD", "L#PA", "M#AD", "LWAD", "RWAD", "SWAD", "SLAD", "CWID",
    "HWAM", "LWAM", "SWAM", "HFPOW", "CHFPW", "HPODW", "CHPDT",
    "CNAM", "SNAM", "LNAM",
}

TMA_FILL = {"TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "LWAM", "SWAM", "LAIX", "SNAM", "CNAM"}

TMT_FILL = {"TRNO", "DATE", "LAID", "LWAD", "SWAD", "CHTD", "SNAM", "LNAM", "CNAM", "CHFPW", "HPODW", "CHPDT"}

PHENOLOGY_DATES = {
    "25SP": {"ADAT": pd.Timestamp("2025-04-22"), "PODD": pd.Timestamp("2025-05-04")},
    "25FA": {"ADAT": pd.Timestamp("2025-09-10"), "PODD": pd.Timestamp("2025-09-17")},
    "26SP": {"ADAT": pd.Timestamp("2026-04-20"), "PODD": pd.Timestamp("2026-05-02")},
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def yrdoy(ts: pd.Timestamp) -> int:
    return int(f"{ts.year % 100:02d}{ts.dayofyear:03d}")


def hybrid_sd(values, min_cv: float = 0.05, fallback_cv: float = 0.10):
    clean = np.array([float(v) for v in values if pd.notna(v)], dtype=float)
    n = len(clean)
    if n == 0:
        return float("nan"), "no_data", 0
    mean = float(np.mean(clean))
    if n < 2:
        sd = fallback_cv * abs(mean) if mean != 0 else fallback_cv
        return sd, f"fallback_cv_{int(fallback_cv*100)}pct", n
    sample_sd = float(np.std(clean, ddof=1))
    cv = sample_sd / abs(mean) if mean != 0 else float("inf")
    if cv < min_cv:
        sd = min_cv * abs(mean) if mean != 0 else min_cv
        return sd, f"replicate_sd_min_cv_{int(min_cv*100)}pct", n
    return sample_sd, "replicate_sd", n


def nearest_by_plot(left: pd.DataFrame, right: pd.DataFrame, left_date: str, right_date: str) -> pd.DataFrame:
    rows = []
    for trno, left_group in left.groupby("TRNO"):
        candidates = right[right["TRNO"] == trno]
        if candidates.empty:
            raise ValueError(f"TRNO={trno} 没有可用的品质匹配数据")
        for _, record in left_group.iterrows():
            distances = (candidates[right_date] - record[left_date]).abs()
            nearest = candidates.loc[distances.idxmin()]
            row = record.to_dict()
            row.update({c: v for c, v in nearest.items() if c != "TRNO"})
            row["MATCH_DAYS"] = int(distances.min().days)
            rows.append(row)
    return pd.DataFrame(rows)


def format_field(column: str, value, fill: bool) -> str:
    if not fill or pd.isna(value) or value == MISSING:
        return f"{int(MISSING):>6d}"
    if column in INTEGER_COLS or column in {"PDAT", "ADAT", "MDAT", "HDAT", "DATE"}:
        if column in {"DATE", "PDAT", "ADAT", "MDAT", "HDAT"}:
            if isinstance(value, (int, np.integer)) or (isinstance(value, float) and float(value).is_integer() and abs(value) >= 10000):
                num = int(round(float(value)))
            else:
                num = yrdoy(pd.Timestamp(value))
        else:
            num = int(round(float(value)))
        s = f"{num:>6d}"
        if len(s) > 6:
            raise ValueError(f"{column}={value} 无法放入 6 字符字段")
        return s
    decimals = DECIMALS.get(column, 1)
    s = f"{float(value):>6.{decimals}f}"
    if len(s) > 6:
        while decimals > 0 and len(s) > 6:
            decimals -= 1
            s = f"{float(value):>6.{decimals}f}"
        if len(s) > 6:
            raise ValueError(f"{column}={value} 无法放入 6 字符字段")
    return s


def write_dssat_file(path: Path, kind: str, title: str, comments: list[str], df: pd.DataFrame) -> None:
    columns = list(df.columns)
    fill_set = TMA_FILL if kind == "A" else TMT_FILL
    header_parts = ["@TRNO "]
    for col in columns[1:]:
        header_parts.append(f"{col:>6}")
    header = "".join(header_parts)
    lines = [f"*EXP.DATA ({kind}): {title}", "", *[f"! {c}" for c in comments], "", header]
    for row in df.itertuples(index=False, name=None):
        lines.append("".join(format_field(col, val, col in fill_set) for col, val in zip(columns, row)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class SeasonResult:
    season_id: str
    excode: str
    output_base: str
    title: str
    source_notes: list[str]
    growth: pd.DataFrame
    harvest: pd.DataFrame
    filea: pd.DataFrame
    observation_uncertainty: pd.DataFrame
    fruit_quality_match_audit: pd.DataFrame
    treatment_exclusion_audit: pd.DataFrame
    source_files: dict[str, str] = field(default_factory=dict)
    qa_metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_observation_uncertainty(
    season_id: str,
    excode: str,
    filea: pd.DataFrame,
    growth: pd.DataFrame,
    harvest: pd.DataFrame,
    source_workbook: str,
) -> pd.DataFrame:
    rows = []
    # FileA event dates (PDAT, ADAT, MDAT)
    for r in filea.itertuples(index=False):
        trno = int(r.TRNO)
        pdat_code = int(r.PDAT)
        try:
            pdat = pd.to_datetime(str(pdat_code), format="%y%j")
        except (TypeError, ValueError):
            pdat = pd.NaT
        for var, code_attr in [("PDAT", "PDAT"), ("ADAT", "ADAT"), ("MDAT", "MDAT")]:
            code = getattr(r, code_attr, np.nan)
            if pd.isna(code) or pd.isna(pdat):
                continue
            try:
                event = pd.to_datetime(str(int(code)), format="%y%j")
                value = float((event - pdat).days)
            except (TypeError, ValueError):
                continue
            rows.append({
                "season_id": season_id, "excode": excode, "trno": trno,
                "date": pdat_code, "variable": var, "value": value,
                "raw_sd": 1.0, "n_rep": 1, "sd_method": "fixed_event_date_sd_1d",
                "source_workbook": source_workbook, "source_sheet": "FileA",
                "source_row_rule": f"filea_{var.lower()}_event_date",
                "quality_flag": "ok",
            })

    # FileA end-state variables: LAIX, LWAM, SWAM, CNAM
    for r in filea.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.HDAT) if pd.notna(r.HDAT) else -99
        for var, val_attr, sd_attr, src_attr, n_attr in [
            ("LAIX", "LAIX", "LAIX_sd", "LAIX_sd_source", "LAIX_n_rep"),
            ("LWAM", "LWAM", "LWAM_sd", "LWAM_sd_source", "LWAM_n_rep"),
            ("SWAM", "SWAM", "SWAM_sd", "SWAM_sd_source", "SWAM_n_rep"),
            ("SNAM", "SNAM", "SNAM_sd", "SNAM_sd_source", "SNAM_n_rep"),
            ("CNAM", "CNAM", "CNAM_sd", "CNAM_sd_source", "CNAM_n_rep"),
        ]:
            val = getattr(r, val_attr, np.nan)
            sd = getattr(r, sd_attr, np.nan)
            src = getattr(r, src_attr, "no_data")
            n_rep = getattr(r, n_attr, 0)
            if pd.notna(val) and val != MISSING and pd.notna(sd) and sd > 0:
                rows.append({
                    "season_id": season_id, "excode": excode,
                    "trno": trno, "date": date_code, "variable": var,
                    "value": float(val), "raw_sd": float(sd),
                    "n_rep": int(n_rep) if pd.notna(n_rep) else 0,
                    "sd_method": src,
                    "source_workbook": source_workbook,
                    "source_sheet": "Sheet1",
                    "source_row_rule": f"per_trno_last_observed_{var.lower()}",
                    "quality_flag": "ok",
                })

    # FileT growth variables: LAID, LWAD, SWAD, CHTD, SNAM, LNAM
    for r in growth.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.DATE)
        for var, val_attr, sd_attr, src_attr, n_attr in [
            ("LAID", "LAID", "LAID_sd", "LAID_sd_source", "LAID_n_rep"),
            ("LWAD", "LWAD", "LWAD_sd", "LWAD_sd_source", "LWAD_n_rep"),
            ("SWAD", "SWAD", "SWAD_sd", "SWAD_sd_source", "SWAD_n_rep"),
            ("CHTD", "CHTD", "CHTD_sd", "CHTD_sd_source", "CHTD_n_rep"),
            ("SNAM", "SNAM", "SNAM_sd", "SNAM_sd_source", "SNAM_n_rep"),
            ("LNAM", "LNAM", "LNAM_sd", "LNAM_sd_source", "LNAM_n_rep"),
        ]:
            val = getattr(r, val_attr, np.nan)
            sd = getattr(r, sd_attr, np.nan)
            src = getattr(r, src_attr, "no_data")
            n_rep = getattr(r, n_attr, 0)
            if pd.notna(val) and val != MISSING and pd.notna(sd) and sd > 0:
                rows.append({
                    "season_id": season_id, "excode": excode,
                    "trno": trno, "date": date_code, "variable": var,
                    "value": float(val), "raw_sd": float(sd),
                    "n_rep": int(n_rep) if pd.notna(n_rep) else 0,
                    "sd_method": src,
                    "source_workbook": source_workbook,
                    "source_sheet": "Sheet1",
                    "source_row_rule": f"per_trno_date_{var.lower()}",
                    "quality_flag": "ok",
                })

    # Harvest variables: CHPDT (cumulative), HPODW (incremental), CHFPW
    for r in harvest.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.DATE)
        # CHPDT
        if pd.notna(r.CHPDT) and pd.notna(r.chpdt_sd):
            rows.append({
                "season_id": season_id, "excode": excode, "trno": trno,
                "date": date_code, "variable": "CHPDT", "value": float(r.CHPDT),
                "raw_sd": float(r.chpdt_sd), "n_rep": int(r.fresh_n_rep),
                "sd_method": r.chpdt_sd_source,
                "source_workbook": source_workbook, "source_sheet": "Sheet1",
                "source_row_rule": "cumulative_dry_yield_propagated_sd",
                "quality_flag": "ok",
            })
        # HPODW
        if pd.notna(r.HPODW) and pd.notna(r.dry_sd):
            rows.append({
                "season_id": season_id, "excode": excode, "trno": trno,
                "date": date_code, "variable": "HPODW", "value": float(r.HPODW),
                "raw_sd": float(r.dry_sd), "n_rep": int(r.fresh_n_rep),
                "sd_method": r.dry_sd_source,
                "source_workbook": source_workbook, "source_sheet": "Sheet1",
                "source_row_rule": "incremental_dry_yield_propagated_sd",
                "quality_flag": "ok",
            })

    return pd.DataFrame(rows)


def load_2025_spring(root: Path) -> SeasonResult:
    folder = root / "2025春"
    source_files = {}

    # 1. Yield
    y_path = folder / "2025春产量数据集.xlsx"
    source_files[str(y_path)] = sha256_file(y_path)
    y = pd.read_excel(y_path)
    y["小区号"] = pd.to_numeric(y["小区号"], errors="coerce")
    y = y[y["小区号"].notna() & (y["小区号"] > 0)].copy()
    y["TRNO"] = y["小区号"].astype(int)
    y["日期"] = pd.to_datetime(y["日期"], errors="coerce").dt.normalize()
    y = y[y["TRNO"].isin(SPRING25_INCLUDED_TN)].copy()

    # D8=A: 9 real harvests + 1 virtual (25198); cutoff after 25198 (i.e. 2025-07-17)
    harvest_cutoff = pd.Timestamp("2025-07-17")
    y = y[y["日期"] <= harvest_cutoff].copy()

    yield_summary = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        yield_vals = grp["产量（千克每公顷）"].dropna().values
        mean_yield = float(np.mean(yield_vals))
        sd, src, n = hybrid_sd(yield_vals)
        yield_summary.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": mean_yield,
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_summary).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # 2. Fruit quality moisture
    q_path = folder / "2025春品质集优先采用品质集中的果实含水率.xlsx"
    source_files[str(q_path)] = sha256_file(q_path)
    fruit = pd.read_excel(q_path)
    fruit["TRNO"] = pd.to_numeric(fruit["小区号"], errors="coerce").astype(int)
    fruit["日期"] = pd.to_datetime(fruit["日期"]).dt.normalize()
    fruit["果含水率"] = pd.to_numeric(fruit["果含水率"], errors="coerce")
    fruit = fruit[fruit["TRNO"].isin(SPRING25_INCLUDED_TN) & fruit["果含水率"].notna()].copy()
    fruit["DMFR"] = 1.0 - fruit["果含水率"]

    dm_by_plot = (fruit.groupby(["TRNO", "日期"], as_index=False)
                  .agg(DMFR=("DMFR", "mean"), N_REP=("重复", "nunique"))
                  .rename(columns={"日期": "GROWTH_DATE"}))
    dm_sd_rows = []
    for (trno, date), grp in fruit.groupby(["TRNO", "日期"]):
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_sd_rows.append({"TRNO": int(trno), "GROWTH_DATE": date, "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_by_plot = dm_by_plot.merge(pd.DataFrame(dm_sd_rows), on=["TRNO", "GROWTH_DATE"], how="left")

    events = yield_df.rename(columns={"DATE": "HARVEST_DATE"})
    matched = nearest_by_plot(events, dm_by_plot, "HARVEST_DATE", "GROWTH_DATE")
    matched["HARVEST_DRY"] = matched["HARVEST_FRESH"] * matched["DMFR"]
    matched["dry_sd"] = np.sqrt(
        (matched["DMFR"] ** 2) * (matched["fresh_sd"] ** 2) +
        (matched["HARVEST_FRESH"] ** 2) * (matched["DMFR_sd"] ** 2)
    )
    matched["dry_sd_source"] = "propagated_fresh_dmfr"
    matched = matched.sort_values(["TRNO", "HARVEST_DATE"]).reset_index(drop=True)
    matched["HFPOW"] = matched["HARVEST_FRESH"]
    matched["HPODW"] = matched["HARVEST_DRY"]
    matched["CHFPW"] = matched.groupby("TRNO")["HFPOW"].cumsum()
    matched["CHPDT"] = matched.groupby("TRNO")["HPODW"].cumsum()
    matched["PDMCD"] = matched["DMFR"]
    matched["fresh_var_inc"] = matched["fresh_sd"] ** 2
    matched["dry_var_inc"] = matched["dry_sd"] ** 2
    matched["chfpw_sd"] = np.sqrt(matched.groupby("TRNO")["fresh_var_inc"].cumsum())
    matched["chpdt_sd"] = np.sqrt(matched.groupby("TRNO")["dry_var_inc"].cumsum())
    matched["chfpw_sd_source"] = "cumulative_variance_propagation"
    matched["chpdt_sd_source"] = "cumulative_variance_propagation"
    matched["match_status"] = "nearest_unbounded"

    harvest = matched[["TRNO", "HARVEST_DATE", "CHFPW", "CHPDT",
                       "fresh_sd", "fresh_sd_source", "fresh_n_rep", "dry_sd", "dry_sd_source",
                       "chfpw_sd", "chfpw_sd_source", "chpdt_sd", "chpdt_sd_source",
                       "DMFR", "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep",
                       "GROWTH_DATE", "MATCH_DAYS", "match_status",
                       "HFPOW", "HPODW", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE", "GROWTH_DATE": "QUALITY_DATE"})

    # 3. Growth
    g_path = folder / "2025春作物生长指标集.xlsx"
    source_files[str(g_path)] = sha256_file(g_path)
    g = pd.read_excel(g_path)
    g["日期"] = pd.to_datetime(g["日期"], errors="coerce").dt.normalize()
    g["TRNO"] = pd.to_numeric(g["小区号"], errors="coerce").astype("Int64")
    g = g.dropna(subset=["TRNO", "日期"]).copy()
    g["TRNO"] = g["TRNO"].astype(int)
    g = g[g["TRNO"].isin(SPRING25_INCLUDED_TN)].copy()
    g["_date_code"] = g["日期"].map(yrdoy).astype(str)
    g["_rep_str"] = g["行位置"].astype(str)

    # Apply approved removals for 25SP
    for s_id, plot, date_str, target, rep_id, channel in APPROVED_REMOVALS:
        if s_id != "25SP" or plot not in SPRING25_INCLUDED_TN:
            continue
        mask = (g["TRNO"] == plot) & (g["_date_code"] == date_str) & (g["_rep_str"] == rep_id)
        if target == "茎干重":
            g.loc[mask, "茎干重"] = np.nan
        elif target == "叶干重":
            g.loc[mask, "叶干重"] = np.nan
        elif target == "LAI":
            g.loc[mask, "LAI"] = np.nan
        elif target == "plant":
            g.loc[mask, ["茎干重", "叶干重", "LAI", "株高"]] = np.nan

    growth_rows = []
    for (trno, date), grp in g.groupby(["TRNO", "日期"]):
        lai_vals = grp["LAI"].dropna().values
        stem_vals = grp["茎干重"].dropna().values
        leaf_vals = grp["叶干重"].dropna().values
        height_vals = grp["株高"].dropna().values
        lai_sd, lai_src, lai_n = hybrid_sd(lai_vals)
        stem_sd, stem_src, stem_n = hybrid_sd(stem_vals)
        leaf_sd, leaf_src, leaf_n = hybrid_sd(leaf_vals)
        height_sd, height_src, height_n = hybrid_sd(height_vals)
        growth_rows.append({
            "TRNO": int(trno), "DATE": date,
            "LAID": float(np.mean(lai_vals)) if len(lai_vals) else np.nan,
            "SWAD": float(np.mean(stem_vals)) * FACTOR if len(stem_vals) else np.nan,
            "LWAD": float(np.mean(leaf_vals)) * FACTOR if len(leaf_vals) else np.nan,
            "CHTD": float(np.mean(height_vals)) if len(height_vals) else np.nan,
            "LAID_sd": lai_sd, "LAID_sd_source": lai_src, "LAID_n_rep": lai_n,
            "SWAD_sd": stem_sd * FACTOR if not pd.isna(stem_sd) else np.nan,
            "SWAD_sd_source": stem_src, "SWAD_n_rep": stem_n,
            "LWAD_sd": leaf_sd * FACTOR if not pd.isna(leaf_sd) else np.nan,
            "LWAD_sd_source": leaf_src, "LWAD_n_rep": leaf_n,
            "CHTD_sd": height_sd, "CHTD_sd_source": height_src, "CHTD_n_rep": height_n,
        })
    growth = pd.DataFrame(growth_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # 4. Plant NPK (D6=B: SNAD, LNAD, SNAM)
    p_path = folder / "2025年春季茄子植株样氮磷钾测定.xlsx"
    source_files[str(p_path)] = sha256_file(p_path)
    p_df = pd.read_excel(p_path)
    p_df["TRNO"] = pd.to_numeric(p_df["小区号"], errors="coerce").astype(int)
    p_df["取样日期"] = pd.to_datetime(p_df["取样日期"]).dt.normalize()

    # Target date: 2025-07-13
    plant_date = pd.Timestamp("2025-07-13")
    growth_25194 = growth[growth["DATE"] == plant_date].set_index("TRNO")

    # Add SNAM, LNAM columns to growth
    growth["SNAM"] = np.nan
    growth["SNAM_sd"] = np.nan
    growth["SNAM_sd_source"] = "no_data"
    growth["SNAM_n_rep"] = 0
    growth["LNAM"] = np.nan
    growth["LNAM_sd"] = np.nan
    growth["LNAM_sd_source"] = "no_data"
    growth["LNAM_n_rep"] = 0
    growth["CNAM"] = np.nan
    growth["CNAM_sd"] = np.nan
    growth["CNAM_sd_source"] = "no_data"
    growth["CNAM_n_rep"] = 0

    plant_n_summary = {}
    for trno in SPRING25_INCLUDED_TN:
        sub_p = p_df[(p_df["TRNO"] == trno) & (p_df["取样日期"] == plant_date)]
        if sub_p.empty or trno not in growth_25194.index:
            continue
        g_row = growth_25194.loc[trno]
        swad = g_row["SWAD"]
        swad_sd = g_row["SWAD_sd"]
        lwad = g_row["LWAD"]
        lwad_sd = g_row["LWAD_sd"]

        stem_p = sub_p[sub_p["取样部位"] == "茎"]["全氮（mg/g)"].dropna().values
        leaf_p = sub_p[sub_p["取样部位"] == "叶"]["全氮（mg/g)"].dropna().values
        if len(stem_p) == 0 or len(leaf_p) == 0:
            continue

        n_stem_mean = float(np.mean(stem_p))
        n_stem_sd, _, n_stem_n = hybrid_sd(stem_p)
        n_leaf_mean = float(np.mean(leaf_p))
        n_leaf_sd, _, n_leaf_n = hybrid_sd(leaf_p)

        # Organ N mass = Dry weight (kg/ha) * N_conc (g/kg) / 1000
        snam = swad * (n_stem_mean / 1000.0)
        snam_sd = snam * np.sqrt((swad_sd / swad) ** 2 + (n_stem_sd / n_stem_mean) ** 2) if swad > 0 else 0.0

        lnam = lwad * (n_leaf_mean / 1000.0)
        lnam_sd = lnam * np.sqrt((lwad_sd / lwad) ** 2 + (n_leaf_sd / n_leaf_mean) ** 2) if lwad > 0 else 0.0

        cnam = snam + lnam
        cnam_sd = np.sqrt(snam_sd ** 2 + lnam_sd ** 2)

        plant_n_summary[trno] = {
            "SNAM": snam, "SNAM_sd": snam_sd, "SNAM_n": n_stem_n,
            "LNAM": lnam, "LNAM_sd": lnam_sd, "LNAM_n": n_leaf_n,
            "CNAM": cnam, "CNAM_sd": cnam_sd, "CNAM_n": min(n_stem_n, n_leaf_n),
        }

        # Update growth row on 25194
        g_mask = (growth["TRNO"] == trno) & (growth["DATE"] == plant_date)
        growth.loc[g_mask, ["SNAM", "SNAM_sd", "SNAM_sd_source", "SNAM_n_rep"]] = [
            snam, snam_sd, "propagated_concentration_drymass", n_stem_n
        ]
        growth.loc[g_mask, ["LNAM", "LNAM_sd", "LNAM_sd_source", "LNAM_n_rep"]] = [
            lnam, lnam_sd, "propagated_concentration_drymass", n_leaf_n
        ]
        growth.loc[g_mask, ["CNAM", "CNAM_sd", "CNAM_sd_source", "CNAM_n_rep"]] = [
            cnam, cnam_sd, "propagated_concentration_drymass", min(n_stem_n, n_leaf_n)
        ]

    # 5. FileA
    pdat_code = 25075
    adat_code = 25112
    podd_code = 25124
    filea_rows = []
    for trno in sorted(harvest["TRNO"].unique()):
        h = harvest[harvest["TRNO"] == trno].sort_values("DATE")
        final_h = h.iloc[-1]
        g_trno = growth[growth["TRNO"] == trno]
        laix = float(g_trno["LAID"].max()) if not g_trno.empty and g_trno["LAID"].notna().any() else np.nan
        laix_sd, laix_src, laix_n = (hybrid_sd(g_trno["LAID"].dropna().values) if not g_trno.empty else (float("nan"), "no_data", 0))
        lwam = float(g_trno["LWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["LWAD"].iloc[-1]) else np.nan
        swam = float(g_trno["SWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["SWAD"].iloc[-1]) else np.nan
        lwam_sd = float(g_trno["LWAD_sd"].iloc[-1]) if "LWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        swam_sd = float(g_trno["SWAD_sd"].iloc[-1]) if "SWAD_sd" in g_trno.columns and not g_trno.empty else np.nan

        pn = plant_n_summary.get(trno, {})
        cnam_val = pn.get("CNAM", np.nan)
        cnam_sd = pn.get("CNAM_sd", np.nan)
        cnam_n = pn.get("CNAM_n", 0)
        snam_val = pn.get("SNAM", np.nan)
        snam_sd = pn.get("SNAM_sd", np.nan)
        snam_n = pn.get("SNAM_n", 0)

        filea_rows.append({
            "TRNO": int(trno), "PDAT": pdat_code, "ADAT": adat_code, "MDAT": podd_code,
            "HDAT": final_h["DATE"], "HWAM": np.nan, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "SNAM": snam_val, "CNAM": cnam_val,
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth", "LWAM_n_rep": 3,
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth", "SWAM_n_rep": 3,
            "SNAM_sd": snam_sd, "SNAM_sd_source": "last_obs_growth" if pd.notna(snam_val) else "no_data",
            "SNAM_n_rep": snam_n,
            "CNAM_sd": cnam_sd, "CNAM_sd_source": "propagated_concentration_drymass" if pd.notna(cnam_val) else "no_data",
            "CNAM_n_rep": cnam_n,
        })
    filea = pd.DataFrame(filea_rows)

    # 6. Uncertainty table
    src_wb_str = "2025春产量数据集.xlsx;2025春作物生长指标集.xlsx;2025年春季茄子植株样氮磷钾测定.xlsx"
    unc = build_observation_uncertainty("25SP", "XXQL2501", filea, growth, harvest, source_workbook=src_wb_str)

    # 7. Fruit match audit
    audit = matched[["TRNO", "HARVEST_DATE", "GROWTH_DATE", "MATCH_DAYS",
                     "HARVEST_FRESH", "fresh_sd", "DMFR", "DMFR_sd",
                     "HARVEST_DRY", "dry_sd", "CHPDT", "chpdt_sd", "match_status"]].copy()
    audit = audit.rename(columns={
        "HARVEST_DATE": "harvest_date", "GROWTH_DATE": "quality_date", "MATCH_DAYS": "match_days",
        "HARVEST_FRESH": "fresh_yield", "DMFR": "dmfr", "HARVEST_DRY": "dry_increment",
        "dry_sd": "dry_increment_sd", "CHPDT": "chpdt",
    })

    # 8. Exclusion audit
    exclusion_audit = pd.DataFrame([
        {"season_id": "25SP", "trno": tn, "reason": SPRING25_EXCLUSION_REASON}
        for tn in SPRING25_EXCLUDED_TN
    ])

    return SeasonResult(
        season_id="25SP", excode="XXQL2501", output_base="2025SPR",
        title="2025 SPRING EGGPLANT; TRNO = DSSAT treatment number (TN 1,7,8 excluded)",
        source_notes=[
            "Fresh yield uses direct arithmetic mean of row replicates (unweighted).",
            "Fruit DM fraction = 1 - measured fruit moisture fraction (2025春品质集优先采用品质集中的果实含水率.xlsx).",
            "Each harvest uses the nearest plot-level moisture measurement date (no max interval).",
            "SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).",
            "Cumulative yield SD propagates incremental variances.",
            "Plant NPK: SNAD, LNAD, SNAM incorporated from 2025年春季茄子植株样氮磷钾测定.xlsx (D6=B).",
            "TN 1,7,8 excluded per FileA/FileT uncertainty adaptation plan (TN 6 included, N missing safe).",
            "D8=A: 9 real harvests + 1 virtual harvest (25198); records after 25198 truncated.",
        ],
        growth=growth, harvest=harvest, filea=filea,
        observation_uncertainty=unc, fruit_quality_match_audit=audit,
        treatment_exclusion_audit=exclusion_audit, source_files=source_files,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "total_observations": int(len(unc)),
            "excluded_tn": SPRING25_EXCLUDED_TN,
            "density": DENSITY,
        }
    )


def load_2026_spring(root: Path) -> SeasonResult:
    folder = root / "2026春"
    source_files = {}

    # 1. Yield
    y_path = folder / "2026春产量集.xlsx"
    source_files[str(y_path)] = sha256_file(y_path)
    y = pd.read_excel(y_path)
    y["日期"] = pd.to_datetime(y["日期"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
    y["TRNO"] = pd.to_numeric(y["小区号"], errors="coerce").astype(int)

    yield_summary = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        yield_vals = grp["产量"].dropna().values
        mean_yield = float(np.mean(yield_vals))
        sd, src, n = hybrid_sd(yield_vals)
        yield_summary.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": mean_yield,
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_summary).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # 2. Quality
    q_path = folder / "2026春品质指标集.xlsx"
    source_files[str(q_path)] = sha256_file(q_path)
    fruit = pd.read_excel(q_path)
    # Map (水处理, 氮处理) to TRNO (1..12) to properly map 20260603 field plot numbers (1..48)
    t_map_26 = {
        ("W3", "N3"): 1, ("W2", "N3"): 2, ("W1", "N3"): 3,
        ("W3", "N2"): 4, ("W2", "N2"): 5, ("W1", "N2"): 6,
        ("W3", "N1"): 7, ("W2", "N1"): 8, ("W3", "N0"): 9,
        ("W1", "N1"): 10, ("W2", "N0"): 11, ("W1", "N0"): 12,
    }
    fruit["TRNO"] = fruit.apply(
        lambda r: t_map_26.get((str(r["水处理"]).strip(), str(r["氮处理"]).strip()), pd.to_numeric(r.get("小区号"), errors="coerce")),
        axis=1,
    ).astype(int)
    fruit["日期"] = pd.to_datetime(fruit["日期"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
    fruit["半果含水率"] = pd.to_numeric(fruit["半果含水率"], errors="coerce")
    fruit = fruit[fruit["半果含水率"].notna()].copy()
    fruit["DMFR"] = 1.0 - fruit["半果含水率"]

    dm_by_plot = (fruit.groupby(["TRNO", "日期"], as_index=False)
                  .agg(DMFR=("DMFR", "mean"), N_REP=("重复", "nunique"))
                  .rename(columns={"日期": "GROWTH_DATE"}))
    dm_sd_rows = []
    for (trno, date), grp in fruit.groupby(["TRNO", "日期"]):
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_sd_rows.append({"TRNO": int(trno), "GROWTH_DATE": date, "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_by_plot = dm_by_plot.merge(pd.DataFrame(dm_sd_rows), on=["TRNO", "GROWTH_DATE"], how="left")

    events = yield_df.rename(columns={"DATE": "HARVEST_DATE"})
    matched = nearest_by_plot(events, dm_by_plot, "HARVEST_DATE", "GROWTH_DATE")
    matched["HARVEST_DRY"] = matched["HARVEST_FRESH"] * matched["DMFR"]
    matched["dry_sd"] = np.sqrt(
        (matched["DMFR"] ** 2) * (matched["fresh_sd"] ** 2) +
        (matched["HARVEST_FRESH"] ** 2) * (matched["DMFR_sd"] ** 2)
    )
    matched["dry_sd_source"] = "propagated_fresh_dmfr"
    matched = matched.sort_values(["TRNO", "HARVEST_DATE"]).reset_index(drop=True)
    matched["HFPOW"] = matched["HARVEST_FRESH"]
    matched["HPODW"] = matched["HARVEST_DRY"]
    matched["CHFPW"] = matched.groupby("TRNO")["HFPOW"].cumsum()
    matched["CHPDT"] = matched.groupby("TRNO")["HPODW"].cumsum()
    matched["PDMCD"] = matched["DMFR"]
    matched["fresh_var_inc"] = matched["fresh_sd"] ** 2
    matched["dry_var_inc"] = matched["dry_sd"] ** 2
    matched["chfpw_sd"] = np.sqrt(matched.groupby("TRNO")["fresh_var_inc"].cumsum())
    matched["chpdt_sd"] = np.sqrt(matched.groupby("TRNO")["dry_var_inc"].cumsum())
    matched["chfpw_sd_source"] = "cumulative_variance_propagation"
    matched["chpdt_sd_source"] = "cumulative_variance_propagation"
    matched["match_status"] = "nearest_unbounded"

    harvest = matched[["TRNO", "HARVEST_DATE", "CHFPW", "CHPDT",
                       "fresh_sd", "fresh_sd_source", "fresh_n_rep", "dry_sd", "dry_sd_source",
                       "chfpw_sd", "chfpw_sd_source", "chpdt_sd", "chpdt_sd_source",
                       "DMFR", "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep",
                       "GROWTH_DATE", "MATCH_DAYS", "match_status",
                       "HFPOW", "HPODW", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE", "GROWTH_DATE": "QUALITY_DATE"})

    # 3. Growth
    g_path = folder / "2026春生长指标集结果.xlsx"
    source_files[str(g_path)] = sha256_file(g_path)
    xls_g = pd.ExcelFile(g_path)

    g_records = []
    # Sheet 0502: 2026-05-02 (26122)
    df_0502 = pd.read_excel(xls_g, sheet_name="0502")
    # Sheet 0502 contains consolidated rows across multiple dates; strictly filter to sampling date 20260502
    df_0502 = df_0502[df_0502["取样日期"] == 20260502].copy()
    for _, r in df_0502.iterrows():
        g_records.append({
            "TRNO": int(r["小区"]), "DATE": pd.Timestamp("2026-05-02"),
            "rep": f"rep{int(r['重复'])}", "sheet": "0502",
            "株高": float(r["株高"]) if pd.notna(r["株高"]) else np.nan,
            "茎干重": float(r["茎干重"]) if pd.notna(r["茎干重"]) else np.nan,
            "叶干重": float(r["叶干重"]) if pd.notna(r["叶干重"]) else np.nan,
            "LAI": float(r["LAI"]) if pd.notna(r["LAI"]) else np.nan,
        })
    # Sheet 0602: 2026-06-02 (26153)
    df_0602 = pd.read_excel(xls_g, sheet_name="0602")
    for _, r in df_0602.iterrows():
        g_records.append({
            "TRNO": int(r["处理"]), "DATE": pd.Timestamp("2026-06-02"),
            "rep": f"rep{int(r['重复'])}", "sheet": "0602",
            "株高": float(r["株高 (cm)"]) if pd.notna(r.get("株高 (cm)")) else np.nan,
            "茎干重": float(r["茎干重"]) if pd.notna(r["茎干重"]) else np.nan,
            "叶干重": float(r["叶干重"]) if pd.notna(r["叶干重"]) else np.nan,
            "LAI": float(r["LAI"]) if pd.notna(r.get("LAI")) else np.nan,
        })
    # Sheet 0629: 2026-06-29 (26180)
    df_0629 = pd.read_excel(xls_g, sheet_name="0629")
    for _, r in df_0629.iterrows():
        g_records.append({
            "TRNO": int(r["处理 (Treatment)"]), "DATE": pd.Timestamp("2026-06-29"),
            "rep": f"rep{int(r['重复'])}", "sheet": "0629",
            "株高": float(r["株高 (Plant Height / cm)"]) if pd.notna(r.get("株高 (Plant Height / cm)")) else np.nan,
            "茎干重": float(r["茎干重"]) if pd.notna(r["茎干重"]) else np.nan,
            "叶干重": float(r["叶干重"]) if pd.notna(r["叶干重"]) else np.nan,
            "LAI": np.nan,
        })
    # Sheet 0717: 2026-07-17 (26198)
    df_0717 = pd.read_excel(xls_g, sheet_name="0717")
    for _, r in df_0717.iterrows():
        g_records.append({
            "TRNO": int(r["处理"]), "DATE": pd.Timestamp("2026-07-17"),
            "rep": f"rep{int(r['重复'])}", "sheet": "0717",
            "株高": float(r["株高 (cm)"]) if pd.notna(r.get("株高 (cm)")) else np.nan,
            "茎干重": float(r["茎干重"]) if pd.notna(r["茎干重"]) else np.nan,
            "叶干重": float(r["叶干重"]) if pd.notna(r["叶干重"]) else np.nan,
            "LAI": float(r["LAI"]) if pd.notna(r.get("LAI")) else np.nan,
        })

    g_all = pd.DataFrame(g_records)

    # Apply approved removals for 26SP
    for s_id, plot, sheet_name, target, rep_id, channel in APPROVED_REMOVALS:
        if s_id != "26SP":
            continue
        mask = (g_all["TRNO"] == plot) & (g_all["sheet"] == sheet_name) & (g_all["rep"] == rep_id)
        if target == "茎干重":
            g_all.loc[mask, "茎干重"] = np.nan
        elif target == "叶干重":
            g_all.loc[mask, "叶干重"] = np.nan
        elif target == "LAI":
            g_all.loc[mask, "LAI"] = np.nan
        elif target == "plant":
            g_all.loc[mask, ["茎干重", "叶干重", "LAI", "株高"]] = np.nan

    growth_rows = []
    for (trno, date), grp in g_all.groupby(["TRNO", "DATE"]):
        lai_vals = grp["LAI"].dropna().values
        stem_vals = grp["茎干重"].dropna().values
        leaf_vals = grp["叶干重"].dropna().values
        height_vals = grp["株高"].dropna().values

        # Imputed LAI for 0629 (26180)
        if yrdoy(date) == 26180:
            lai_val = LAI_IMPUTED[trno]
            lai_sd = LAI_IMPUTED_SD[trno]
            lai_src = "imputed_sla_ratio_20260831"
            lai_n = LAI_IMPUTED_N[trno]
        else:
            lai_val = float(np.mean(lai_vals)) if len(lai_vals) else np.nan
            lai_sd, lai_src, lai_n = hybrid_sd(lai_vals)

        stem_sd, stem_src, stem_n = hybrid_sd(stem_vals)
        leaf_sd, leaf_src, leaf_n = hybrid_sd(leaf_vals)
        height_sd, height_src, height_n = hybrid_sd(height_vals)

        growth_rows.append({
            "TRNO": int(trno), "DATE": date,
            "LAID": lai_val,
            "SWAD": float(np.mean(stem_vals)) * FACTOR if len(stem_vals) else np.nan,
            "LWAD": float(np.mean(leaf_vals)) * FACTOR if len(leaf_vals) else np.nan,
            "CHTD": float(np.mean(height_vals)) if len(height_vals) else np.nan,
            "LAID_sd": lai_sd, "LAID_sd_source": lai_src, "LAID_n_rep": lai_n,
            "SWAD_sd": stem_sd * FACTOR if not pd.isna(stem_sd) else np.nan,
            "SWAD_sd_source": stem_src, "SWAD_n_rep": stem_n,
            "LWAD_sd": leaf_sd * FACTOR if not pd.isna(leaf_sd) else np.nan,
            "LWAD_sd_source": leaf_src, "LWAD_n_rep": leaf_n,
            "CHTD_sd": height_sd, "CHTD_sd_source": height_src, "CHTD_n_rep": height_n,
        })
    growth = pd.DataFrame(growth_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # 4. FileA
    pdat_code = 26075
    adat_code = 26110
    podd_code = 26122
    filea_rows = []
    for trno in sorted(harvest["TRNO"].unique()):
        h = harvest[harvest["TRNO"] == trno].sort_values("DATE")
        final_h = h.iloc[-1]
        g_trno = growth[growth["TRNO"] == trno]
        laix = float(g_trno["LAID"].max()) if not g_trno.empty and g_trno["LAID"].notna().any() else np.nan
        laix_sd, laix_src, laix_n = (hybrid_sd(g_trno["LAID"].dropna().values) if not g_trno.empty else (float("nan"), "no_data", 0))
        lwam = float(g_trno["LWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["LWAD"].iloc[-1]) else np.nan
        swam = float(g_trno["SWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["SWAD"].iloc[-1]) else np.nan
        lwam_sd = float(g_trno["LWAD_sd"].iloc[-1]) if "LWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        swam_sd = float(g_trno["SWAD_sd"].iloc[-1]) if "SWAD_sd" in g_trno.columns and not g_trno.empty else np.nan

        filea_rows.append({
            "TRNO": int(trno), "PDAT": pdat_code, "ADAT": adat_code, "MDAT": podd_code,
            "HDAT": final_h["DATE"], "HWAM": np.nan, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "SNAM": np.nan, "CNAM": np.nan,
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth", "LWAM_n_rep": 3,
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth", "SWAM_n_rep": 3,
            "SNAM_sd": np.nan, "SNAM_sd_source": "no_data", "SNAM_n_rep": 0,
            "CNAM_sd": np.nan, "CNAM_sd_source": "no_data", "CNAM_n_rep": 0,
        })
    filea = pd.DataFrame(filea_rows)

    # 5. Uncertainty table
    src_wb_str = "2026春产量集.xlsx;2026春生长指标集结果.xlsx;2026春品质指标集.xlsx"
    unc = build_observation_uncertainty("26SP", "XXQL2601", filea, growth, harvest, source_workbook=src_wb_str)

    # Flag imputed LAI in uncertainty table
    mask_imp = (unc["date"].astype(str) == "26180") & (unc["variable"] == "LAID")
    unc.loc[mask_imp, "quality_flag"] = "imputed_20260831"
    unc.loc[mask_imp, "sd_method"] = "imputed_sla_ratio_20260831"

    # 6. Fruit match audit
    audit = matched[["TRNO", "HARVEST_DATE", "GROWTH_DATE", "MATCH_DAYS",
                     "HARVEST_FRESH", "fresh_sd", "DMFR", "DMFR_sd",
                     "HARVEST_DRY", "dry_sd", "CHPDT", "chpdt_sd", "match_status"]].copy()
    audit = audit.rename(columns={
        "HARVEST_DATE": "harvest_date", "GROWTH_DATE": "quality_date", "MATCH_DAYS": "match_days",
        "HARVEST_FRESH": "fresh_yield", "DMFR": "dmfr", "HARVEST_DRY": "dry_increment",
        "dry_sd": "dry_increment_sd", "CHPDT": "chpdt",
    })

    return SeasonResult(
        season_id="26SP", excode="XXQL2601", output_base="2026SPR",
        title="2026 SPRING EGGPLANT; TRNO = DSSAT treatment number",
        source_notes=[
            "Fresh yield uses arithmetic mean of replicates.",
            "Fruit DM fraction = 1 - 半果含水率 (2026春品质指标集.xlsx).",
            "Each harvest uses the nearest plot-level moisture measurement date (no max interval).",
            "SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).",
            "Cumulative yield SD propagates incremental variances.",
            "LAI at 26180 imputed from leaf dry weight / SLA ratio R=18.52 (12 points flagged imputed_20260831).",
            "Strict FileA/FileT fill rule per project standard.",
        ],
        growth=growth, harvest=harvest, filea=filea,
        observation_uncertainty=unc, fruit_quality_match_audit=audit,
        treatment_exclusion_audit=pd.DataFrame(), source_files=source_files,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "total_observations": int(len(unc)),
            "density": DENSITY,
        }
    )


def write_season_outputs(result: SeasonResult, out_dir: Path, generator_sha: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    growth_out = result.growth.copy()
    if "CHTD" in growth_out.columns:
        growth_out["CHTD"] = pd.to_numeric(growth_out["CHTD"], errors="coerce") / 100.0
    if "CHTD_sd" in growth_out.columns:
        growth_out["CHTD_sd"] = pd.to_numeric(growth_out["CHTD_sd"], errors="coerce") / 100.0

    uncertainty_out = result.observation_uncertainty.copy()
    chtd_mask = uncertainty_out["variable"].astype(str).str.upper().eq("CHTD")
    for column in ("value", "raw_sd"):
        uncertainty_out.loc[chtd_mask, column] = (
            pd.to_numeric(uncertainty_out.loc[chtd_mask, column], errors="coerce") / 100.0
        )
    uncertainty_out.loc[chtd_mask, "source_row_rule"] = (
        uncertainty_out.loc[chtd_mask, "source_row_rule"].astype(str) + "; converted_cm_to_m_for_DSSAT"
    )

    # FileA
    filea_out = result.filea[TMA_COLUMNS].copy()
    write_dssat_file(out_dir / f"{result.excode}.TMA", "A", result.title, result.source_notes, filea_out)

    # FileT
    for col in ("SNAM", "LNAM", "CNAM"):
        if col not in growth_out.columns:
            growth_out[col] = np.nan
    growth_tmt = growth_out[["TRNO", "DATE", "LAID", "LWAD", "SWAD", "CHTD", "SNAM", "LNAM", "CNAM"]].copy()
    harvest_tmt = result.harvest[["TRNO", "DATE", "CHFPW", "HPODW", "CHPDT"]].copy()
    tmt = growth_tmt.merge(harvest_tmt, on=["TRNO", "DATE"], how="outer").sort_values(["TRNO", "DATE"])
    for col in TMT_COLUMNS:
        if col not in tmt.columns:
            tmt[col] = np.nan
    tmt = tmt[TMT_COLUMNS].reset_index(drop=True)
    write_dssat_file(out_dir / f"{result.excode}.TMT", "T", result.title, result.source_notes, tmt)

    # CSV outputs
    uncertainty_out.to_csv(out_dir / "observation_uncertainty.csv", index=False)
    result.fruit_quality_match_audit.to_csv(out_dir / "fruit_quality_match_audit.csv", index=False)
    if not result.treatment_exclusion_audit.empty:
        result.treatment_exclusion_audit.to_csv(out_dir / "treatment_exclusion_audit.csv", index=False)

    result.filea.to_csv(out_dir / "FileA_values.csv", index=False)
    tmt.to_csv(out_dir / "FileT_values.csv", index=False)

    # Generator log
    log = {
        "season_id": result.season_id,
        "excode": result.excode,
        "generator": "tools/experiments/build_refreshed_observations_20260917.py",
        "generator_sha256": generator_sha,
        "spec_compliance": "docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md",
        "source_files": result.source_files,
        "qa_metrics": result.qa_metrics,
        "source_notes": result.source_notes,
        "output_files": [
            f"{result.excode}.TMA",
            f"{result.excode}.TMT",
            "observation_uncertainty.csv",
            "fruit_quality_match_audit.csv",
            "FileA_values.csv",
            "FileT_values.csv",
        ] + (["treatment_exclusion_audit.csv"] if not result.treatment_exclusion_audit.empty else []),
    }
    (out_dir / "generator_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build refreshed observations for 2025春 and 2026春.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "data/user/ref/DSSAT文件")
    parser.add_argument("--seasons", nargs="+", default=["25SP", "26SP"], choices=["25SP", "26SP"])
    args = parser.parse_args()

    generator_sha = sha256_file(Path(__file__).resolve())
    loaders = {"25SP": load_2025_spring, "26SP": load_2026_spring}
    folder_map = {"25SP": "2025春", "26SP": "2026春"}

    for s in args.seasons:
        print(f"=== Generating refreshed observations for {s} ===")
        res = loaders[s](args.root)
        out_dir = args.root / folder_map[s] / "DSSAT输出_v2"
        write_season_outputs(res, out_dir, generator_sha)
        print(f"  Output directory: {out_dir}")
        print(f"  Plots: {res.qa_metrics['plots']}")
        print(f"  Growth dates: {res.qa_metrics['growth_dates']}")
        print(f"  Harvest dates: {res.qa_metrics['harvest_dates']}")
        print(f"  Total observations in uncertainty: {res.qa_metrics['total_observations']}")


if __name__ == "__main__":
    main()
