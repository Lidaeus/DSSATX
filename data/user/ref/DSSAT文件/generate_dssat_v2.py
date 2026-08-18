#!/usr/bin/env python3
"""Generate DSSAT File A / File T (full reference column structure) for 2025春/2025秋/2026春.

Reference format: d:\\Tomato_Cal\\data\\user\\experiments\\XXQL2501\\XXQL2501.TMA / .TMT
  TMA columns: @TRNO  PDAT  ADAT  MDAT  HDAT  HWAM  LWAM  SWAM  LAIX  HIAM  CNAM
  TMT columns: @TRNO   DATE  L#SD  LAID  L#PA  LWAD  RWAD  SWAD  M#AD  SLAD  CHTD  CWID  CNAM  SNAM  LNAM HFPOW CHFPW HPODW CHPDT PDMCD

Key rules:
* 6-char fixed-width fields, right-aligned. -99 for missing.
* Dates as 5-digit YYDDD.
* PDAT/ADAT/MDAT left as -99 (phenology not measured).
* HWAM = final cumulative DRY fruit yield (CHPDT at last harvest).
* HWAHF (cumulative fresh) is NOT a standard DSSAT FileA column -> only in TMT as CHFPW.
* HFPOW/HPODW = INCREMENTAL per-harvest fresh/dry yield; CHFPW/CHPDT = cumulative.
* PDMCD = fruit dry-matter fraction used for that harvest.

SD (standard deviation) for PEST++-IES weights — hybrid method:
* If n_rep >= 2: sample SD (ddof=1); if SD/|mean| < 0.05, use 0.05*|mean| (min CV=5%).
* If n_rep < 2: use 0.10*|mean| (fixed CV=10%).
* For cumulative yield (CHFPW/CHPDT): SD = sqrt(sum of incremental variances).

Output (overwrites each season's DSSAT输出/ folder):
  {season}.TMA, {season}.TMT, {season}_observations.csv, {season}_FileA_values.csv,
  {season}_FileT_values.csv, {season}_QA.md
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


MISSING = -99.0
DENSITY = 27000.0  # plants/ha
FACTOR = DENSITY / 1000.0  # g/plant -> kg/ha

# Full reference column structures (matching XXQL2501.TMA / .TMT)
TMA_COLUMNS = ["TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "HWAM", "LWAM", "SWAM", "LAIX", "HIAM", "CNAM"]
TMT_COLUMNS = [
    "TRNO", "DATE", "L#SD", "LAID", "L#PA", "LWAD", "RWAD", "SWAD",
    "M#AD", "SLAD", "CHTD", "CWID", "CNAM", "SNAM", "LNAM",
    "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
]

# Per-column decimal places for formatting (6-char field max)
DECIMALS = {
    "LAID": 3, "LAIX": 3,
    "SNAM": 1, "LNAM": 1, "CNAM": 1,
    "PDMCD": 3, "HIAM": 3,
}
INTEGER_COLS = {"TRNO", "DATE", "PDAT", "ADAT", "MDAT", "HDAT",
                "L#SD", "L#PA", "M#AD",
                "LWAD", "RWAD", "SWAD", "SLAD", "CHTD", "CWID",
                "HWAM", "LWAM", "SWAM",
                "HFPOW", "CHFPW", "HPODW", "CHPDT"}


# ----------------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------------

def yrdoy(ts: pd.Timestamp) -> int:
    """Convert a Timestamp to 5-digit YYDDD."""
    return int(f"{ts.year % 100:02d}{ts.dayofyear:03d}")


def parse_yyyymmdd(series: pd.Series) -> pd.Series:
    """Parse numeric yyyymmdd or datetime strings to normalized Timestamps."""
    numeric = pd.to_numeric(series, errors="coerce")
    return pd.to_datetime(numeric.astype("Int64").astype(str), format="%Y%m%d", errors="coerce").dt.normalize()


def require_columns(df: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{label} 缺少必需列: {missing}")


def hybrid_sd(values: np.ndarray, min_cv: float = 0.05, fallback_cv: float = 0.10) -> tuple[float, str, int]:
    """Compute hybrid SD.

    Returns (sd, source, n_rep).
    * n_rep >= 2: sample SD (ddof=1); apply min_cv floor.
    * n_rep < 2: fallback_cv * |mean| (if mean != 0), else fallback_cv.
    """
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


def verify_treatment_mapping(frames: list[tuple[pd.DataFrame, str]], label: str) -> None:
    mappings = []
    for df, plot_col in frames:
        m = (df[[plot_col, "水处理", "氮处理"]].dropna(subset=[plot_col]).drop_duplicates()
             .rename(columns={plot_col: "TRNO"}).sort_values("TRNO").reset_index(drop=True))
        if m["TRNO"].duplicated().any():
            raise ValueError(f"{label}: 同一小区对应多个水氮处理")
        mappings.append(m)
    first = mappings[0]
    for other in mappings[1:]:
        if not first.equals(other):
            raise ValueError(f"{label}: 数据源之间的小区—处理映射不一致")


def nearest_by_plot(left: pd.DataFrame, right: pd.DataFrame, left_date: str, right_date: str) -> pd.DataFrame:
    """For each row in left, find the nearest-date row in right (same TRNO)."""
    rows = []
    for trno, left_group in left.groupby("TRNO"):
        candidates = right[right["TRNO"] == trno]
        if candidates.empty:
            raise ValueError(f"TRNO={trno} 没有可用的日期匹配数据")
        for _, record in left_group.iterrows():
            distances = (candidates[right_date] - record[left_date]).abs()
            nearest = candidates.loc[distances.idxmin()]
            row = record.to_dict()
            row.update({c: v for c, v in nearest.items() if c != "TRNO"})
            row["MATCH_DAYS"] = int(distances.min().days)
            rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Formatting (6-char fixed-width)
# ----------------------------------------------------------------------------

def format_field(column: str, value) -> str:
    """Format a value into a 6-char right-aligned field."""
    if pd.isna(value):
        return f"{int(MISSING):>6d}"
    if column in INTEGER_COLS or column in {"PDAT", "ADAT", "MDAT", "HDAT", "DATE"}:
        if column in {"DATE", "PDAT", "ADAT", "MDAT", "HDAT"}:
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
        # Try fewer decimals
        while decimals > 0 and len(s) > 6:
            decimals -= 1
            s = f"{float(value):>6.{decimals}f}"
        if len(s) > 6:
            raise ValueError(f"{column}={value} 无法放入 6 字符字段")
    return s


def write_dssat_file(path: Path, kind: str, title: str, comments: list[str], df: pd.DataFrame) -> None:
    """Write a DSSAT FileA or FileT (6-char fixed-width)."""
    columns = list(df.columns)
    # Header: @TRNO followed by other columns, each right-aligned in 6 chars
    header_parts = ["@TRNO"]
    for col in columns[1:]:
        header_parts.append(f"{col:>6}")
    header = "".join(header_parts)
    lines = [f"*EXP.DATA ({kind}): {title}", "", *[f"! {c}" for c in comments], "", header]
    for row in df.itertuples(index=False, name=None):
        lines.append("".join(format_field(col, val) for col, val in zip(columns, row)))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------

@dataclass
class SeasonResult:
    key: str
    output_base: str
    title: str
    source_notes: list[str]
    # TMT data frames (each row = one observation date per TRNO)
    growth: pd.DataFrame  # TRNO, DATE, LAID, SWAD, LWAD (+ maybe CNAM, SNAM, LNAM)
    nitrogen: pd.DataFrame  # TRNO, DATE, CNAM, SNAM, LNAM
    harvest: pd.DataFrame  # TRNO, DATE, HFPOW, CHFPW, HPODW, CHPDT, PDMCD
    # FileA summary
    filea: pd.DataFrame
    # Observations with SD (for PEST++)
    observations: pd.DataFrame
    qa_metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------
# 2025 春季
# ----------------------------------------------------------------------------

def load_2025_spring(root: Path) -> SeasonResult:
    folder = root / "2025春"
    # --- Yield data (加权小区产量 already pre-calculated) ---
    y = pd.read_excel(folder / "2025春产量数据集.xlsx", sheet_name="Sheet1")
    y["小区号"] = pd.to_numeric(y["小区号"], errors="coerce")
    y = y[y["小区号"].notna() & (y["小区号"] > 0)].copy()
    y["TRNO"] = y["小区号"].astype(int)
    y["日期"] = pd.to_datetime(y["日期"], errors="coerce").dt.normalize()
    require_columns(y, ["TRNO", "日期", "行位置", "产量", "加权小区产量", "水处理", "氮处理"], "2025春产量")

    # Per (TRNO, date): use 加权小区产量 as the plot-level fresh yield.
    # SD from 3 row replicates (边行, 中间行1, 中间行2) using 产量 column.
    yield_summary = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        weighted_val = float(grp["加权小区产量"].iloc[0])  # constant within group
        row_yields = grp["产量"].dropna().values
        sd, src, n = hybrid_sd(row_yields)
        yield_summary.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": weighted_val,  # weighted
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_summary).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Fruit moisture -> DMFR ---
    g = pd.read_excel(folder / "2025春作物生长指标集.xlsx", sheet_name="Sheet1")
    require_columns(g, ["日期", "小区号", "重复", "果含水率", "茎干重", "叶干重", "LAI", "水处理", "氮处理"], "2025春生长")
    g["日期"] = pd.to_datetime(g["日期"], errors="coerce").dt.normalize()
    g["TRNO"] = pd.to_numeric(g["小区号"], errors="coerce").astype("Int64")
    g = g.dropna(subset=["TRNO", "日期"]).copy()
    g["TRNO"] = g["TRNO"].astype(int)

    # DMFR from moisture: DMFR = 1 - 果含水率
    fruit = g[g["果含水率"].notna()].copy()
    fruit["DMFR"] = 1.0 - fruit["果含水率"]
    dm_by_plot = (fruit.groupby(["TRNO", "日期"], as_index=False)
                  .agg(DMFR=("DMFR", "mean"), N_REP=("重复", "nunique"))
                  .rename(columns={"日期": "DATE"}))
    # Also compute DMFR SD from replicates
    dm_sd_rows = []
    for (trno, date), grp in fruit.groupby(["TRNO", "日期"]):
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_sd_rows.append({"TRNO": int(trno), "DATE": date, "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_sd = pd.DataFrame(dm_sd_rows)
    dm_by_plot = dm_by_plot.merge(dm_sd, on=["TRNO", "DATE"], how="left")

    # --- Match harvest dates to nearest DMFR measurement ---
    events = yield_df[["TRNO", "DATE", "HARVEST_FRESH", "fresh_sd", "fresh_sd_source", "fresh_n_rep"]].rename(
        columns={"DATE": "HARVEST_DATE"})
    matched = nearest_by_plot(events, dm_by_plot.rename(columns={"DATE": "GROWTH_DATE"}), "HARVEST_DATE", "GROWTH_DATE")
    matched["HARVEST_DRY"] = matched["HARVEST_FRESH"] * matched["DMFR"]
    # SD of dry yield: propagate fresh_sd and DMFR_sd
    # var(dry) = DMFR^2 * var(fresh) + fresh^2 * var(DMFR)
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

    # Cumulative SD: sqrt(sum of incremental variances)
    matched["fresh_var_inc"] = matched["fresh_sd"] ** 2
    matched["dry_var_inc"] = matched["dry_sd"] ** 2
    matched["chfpw_sd"] = np.sqrt(matched.groupby("TRNO")["fresh_var_inc"].cumsum())
    matched["chpdt_sd"] = np.sqrt(matched.groupby("TRNO")["dry_var_inc"].cumsum())
    matched["chfpw_sd_source"] = "cumulative_variance_propagation"
    matched["chpdt_sd_source"] = "cumulative_variance_propagation"

    harvest = matched[["TRNO", "HARVEST_DATE", "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE"})
    harvest_obs = matched[["TRNO", "HARVEST_DATE", "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
                           "fresh_sd", "fresh_sd_source", "fresh_n_rep",
                           "dry_sd", "dry_sd_source",
                           "chfpw_sd", "chfpw_sd_source",
                           "chpdt_sd", "chpdt_sd_source",
                           "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep"]].rename(
        columns={"HARVEST_DATE": "DATE"})

    # --- Growth data (LAID, SWAD, LWAD) ---
    growth_raw = g[g["LAI"].notna() | g["茎干重"].notna() | g["叶干重"].notna()].copy()
    growth_rows = []
    for (trno, date), grp in growth_raw.groupby(["TRNO", "日期"]):
        lai_vals = grp["LAI"].dropna().values
        stem_vals = grp["茎干重"].dropna().values
        leaf_vals = grp["叶干重"].dropna().values
        lai_sd, lai_src, lai_n = hybrid_sd(lai_vals)
        stem_sd, stem_src, stem_n = hybrid_sd(stem_vals)
        leaf_sd, leaf_src, leaf_n = hybrid_sd(leaf_vals)
        growth_rows.append({
            "TRNO": int(trno), "DATE": date,
            "LAID": float(np.mean(lai_vals)) if len(lai_vals) else np.nan,
            "SWAD": float(np.mean(stem_vals)) * FACTOR if len(stem_vals) else np.nan,
            "LWAD": float(np.mean(leaf_vals)) * FACTOR if len(leaf_vals) else np.nan,
            "LAID_sd": lai_sd, "LAID_sd_source": lai_src, "LAID_n_rep": lai_n,
            "SWAD_sd": stem_sd * FACTOR if not pd.isna(stem_sd) else np.nan,
            "SWAD_sd_source": stem_src, "SWAD_n_rep": stem_n,
            "LWAD_sd": leaf_sd * FACTOR if not pd.isna(leaf_sd) else np.nan,
            "LWAD_sd_source": leaf_src, "LWAD_n_rep": leaf_n,
        })
    growth = pd.DataFrame(growth_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Nitrogen data ---
    n_path = folder / "2025年春季茄子植株样氮磷钾测定.xlsx"
    nitrogen = pd.DataFrame(columns=["TRNO", "DATE", "CNAM", "SNAM", "LNAM"])
    if n_path.exists():
        n = pd.read_excel(n_path, sheet_name="Sheet1")
        if "全氮（mg/g)" in n.columns and "取样部位" in n.columns and "小区号" in n.columns:
            n["TRNO"] = pd.to_numeric(n["小区号"], errors="coerce").astype("Int64")
            n = n.dropna(subset=["TRNO"]).copy()
            n["TRNO"] = n["TRNO"].astype(int)
            n["取样日期"] = pd.to_datetime(n["取样日期"], errors="coerce").dt.normalize()
            wide = n.pivot_table(index=["TRNO", "取样日期", "重复"], columns="取样部位", values="全氮（mg/g)", aggfunc="first").reset_index()
            wide = wide.rename(columns={"取样日期": "DATE"})
            # Aggregate growth by (TRNO, date) for mean stem/leaf dry weight
            growth_mean = (g.groupby(["TRNO", "日期"], as_index=False)
                          .agg(STEM_G=("茎干重", "mean"), LEAF_G=("叶干重", "mean"))
                          .rename(columns={"日期": "GROWTH_DATE"}))
            growth_mean = growth_mean.dropna(subset=["STEM_G", "LEAF_G"])
            if not wide.empty and not growth_mean.empty:
                date_match = nearest_by_plot(
                    wide[["TRNO", "DATE"]].drop_duplicates(),
                    growth_mean[["TRNO", "GROWTH_DATE"]].drop_duplicates(),
                    "DATE", "GROWTH_DATE")
                wide = wide.merge(date_match[["TRNO", "DATE", "GROWTH_DATE", "MATCH_DAYS"]], on=["TRNO", "DATE"], validate="many_to_one")
                wide = wide.merge(growth_mean, on=["TRNO", "GROWTH_DATE"], validate="many_to_one")
                if "茎" in wide.columns:
                    wide["SNAM"] = wide["STEM_G"] * FACTOR * wide["茎"] / 1000.0
                if "叶" in wide.columns:
                    wide["LNAM"] = wide["LEAF_G"] * FACTOR * wide["叶"] / 1000.0
                if "SNAM" in wide.columns and "LNAM" in wide.columns:
                    wide["CNAM"] = wide["SNAM"] + wide["LNAM"]
                n_rows = []
                for (trno, date), grp in wide.groupby(["TRNO", "DATE"]):
                    snam_vals = grp["SNAM"].dropna().values if "SNAM" in grp.columns else np.array([])
                    lnam_vals = grp["LNAM"].dropna().values if "LNAM" in grp.columns else np.array([])
                    cnam_vals = grp["CNAM"].dropna().values if "CNAM" in grp.columns else np.array([])
                    snam_sd, snam_src, snam_n = hybrid_sd(snam_vals)
                    lnam_sd, lnam_src, lnam_n = hybrid_sd(lnam_vals)
                    cnam_sd, cnam_src, cnam_n = hybrid_sd(cnam_vals)
                    n_rows.append({
                        "TRNO": int(trno), "DATE": date,
                        "CNAM": float(np.mean(cnam_vals)) if len(cnam_vals) else np.nan,
                        "SNAM": float(np.mean(snam_vals)) if len(snam_vals) else np.nan,
                        "LNAM": float(np.mean(lnam_vals)) if len(lnam_vals) else np.nan,
                        "CNAM_sd": cnam_sd, "CNAM_sd_source": cnam_src, "CNAM_n_rep": cnam_n,
                        "SNAM_sd": snam_sd, "SNAM_sd_source": snam_src, "SNAM_n_rep": snam_n,
                        "LNAM_sd": lnam_sd, "LNAM_sd_source": lnam_src, "LNAM_n_rep": lnam_n,
                    })
                nitrogen = pd.DataFrame(n_rows)
                if not nitrogen.empty:
                    nitrogen = nitrogen.sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Build FileA ---
    filea_rows = []
    for trno in sorted(harvest["TRNO"].unique()):
        h = harvest[harvest["TRNO"] == trno].sort_values("DATE")
        final = h.iloc[-1]
        g_trno = growth[growth["TRNO"] == trno]
        n_trno = nitrogen[nitrogen["TRNO"] == trno] if not nitrogen.empty else pd.DataFrame()
        laix = float(g_trno["LAID"].max()) if not g_trno.empty and g_trno["LAID"].notna().any() else np.nan
        laix_sd, laix_src, laix_n = (hybrid_sd(g_trno["LAID"].dropna().values) if not g_trno.empty else (float("nan"), "no_data", 0))
        lwam = float(g_trno["LWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["LWAD"].iloc[-1]) else np.nan
        swam = float(g_trno["SWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["SWAD"].iloc[-1]) else np.nan
        lwam_sd = float(g_trno["LWAD_sd"].iloc[-1]) if "LWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        swam_sd = float(g_trno["SWAD_sd"].iloc[-1]) if "SWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        cnam = float(n_trno["CNAM"].iloc[-1]) if not n_trno.empty and pd.notna(n_trno["CNAM"].iloc[-1]) else np.nan
        cnam_sd = float(n_trno["CNAM_sd"].iloc[-1]) if not n_trno.empty else np.nan
        hwam = float(final["CHPDT"])  # final cumulative dry yield
        hwam_sd = float(harvest_obs[harvest_obs["TRNO"] == trno]["chpdt_sd"].iloc[-1])
        filea_rows.append({
            "TRNO": int(trno), "PDAT": np.nan, "ADAT": np.nan, "MDAT": np.nan,
            "HDAT": final["DATE"], "HWAM": hwam, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "CNAM": cnam,
            "HWAM_sd": hwam_sd, "HWAM_sd_source": "final_cumulative_dry",
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth",
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth",
            "CNAM_sd": cnam_sd, "CNAM_sd_source": "last_obs_nitrogen",
        })
    filea = pd.DataFrame(filea_rows)

    # --- Build observations DataFrame (for PEST++) ---
    obs_rows = []
    # FileA observations: HWAM, LAIX, LWAM, SWAM, CNAM, HDAT
    for r in filea.itertuples(index=False):
        trno = int(r.TRNO)
        for var, sd_var, src_var in [("HWAM", "HWAM_sd", "HWAM_sd_source"),
                                      ("LAIX", "LAIX_sd", "LAIX_sd_source"),
                                      ("LWAM", "LWAM_sd", "LWAM_sd_source"),
                                      ("SWAM", "SWAM_sd", "SWAM_sd_source"),
                                      ("CNAM", "CNAM_sd", "CNAM_sd_source")]:
            val = getattr(r, var)
            sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}",
                    "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "joint_season_end",
                    "sim_token": var, "model_output_file": "Evaluate.OUT",
                    "trno": trno, "date": yrdoy(r.HDAT) if pd.notna(r.HDAT) else -99,
                    "variable": var, "n_rep": getattr(r, f"{var}_n_rep", 1) if hasattr(r, f"{var}_n_rep") else 1,
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    # FileT growth observations: LAID, SWAD, LWAD
    for r in growth.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("LAID", "LAID_sd", "LAID_sd_source"),
                                      ("SWAD", "SWAD_sd", "SWAD_sd_source"),
                                      ("LWAD", "LWAD_sd", "LWAD_sd_source")]:
            val = getattr(r, var)
            sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}",
                    "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "growth_process",
                    "sim_token": var, "model_output_file": "PlantGro.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": getattr(r, f"{var}_n_rep", 1),
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    # FileT nitrogen observations: CNAM, SNAM, LNAM
    if not nitrogen.empty:
        for r in nitrogen.itertuples(index=False):
            trno = int(r.TRNO)
            date_code = yrdoy(r.DATE)
            for var, sd_var, src_var in [("CNAM", "CNAM_sd", "CNAM_sd_source"),
                                          ("SNAM", "SNAM_sd", "SNAM_sd_source"),
                                          ("LNAM", "LNAM_sd", "LNAM_sd_source")]:
                val = getattr(r, var)
                sd = getattr(r, sd_var)
                if pd.notna(val) and pd.notna(sd) and sd > 0:
                    obs_rows.append({
                        "obsnme": f"{var.lower()}_t{trno}_d{date_code}",
                        "obsval": float(val), "weight": 1.0 / float(sd),
                        "obgnme": "growth_process",
                        "sim_token": var, "model_output_file": "PlantGro.OUT",
                        "trno": trno, "date": date_code, "variable": var,
                        "n_rep": getattr(r, f"{var}_n_rep", 1),
                        "sd": float(sd), "sd_source": getattr(r, src_var),
                    })
    # FileT harvest observations: CHFPW, CHPDT, HFPOW, HPODW, PDMCD
    for r in harvest_obs.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("CHFPW", "chfpw_sd", "chfpw_sd_source"),
                                      ("CHPDT", "chpdt_sd", "chpdt_sd_source"),
                                      ("HFPOW", "fresh_sd", "fresh_sd_source"),
                                      ("HPODW", "dry_sd", "dry_sd_source")]:
            val = getattr(r, var)
            sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}",
                    "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "harvest_event",
                    "sim_token": var, "model_output_file": "FreshWt.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": int(getattr(r, "fresh_n_rep", 1) if var in ("CHFPW", "HFPOW") else 1),
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    observations = pd.DataFrame(obs_rows)

    return SeasonResult(
        key="2025spring", output_base="2025SPR",
        title="2025 SPRING EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield uses pre-computed weighted plot yield (edge*0.5 + middle-row mean*0.5).",
            "Fruit DM fraction = 1 - measured fruit moisture fraction (2025春作物生长指标集.果含水率).",
            "Each harvest uses the nearest plot-level moisture measurement date.",
            "SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).",
            "Cumulative yield SD propagates incremental variances.",
        ],
        growth=growth, nitrogen=nitrogen, harvest=harvest, filea=filea,
        observations=observations,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "dmfr_dates": int(dm_by_plot["DATE"].nunique()),
            "nitrogen_rows": int(len(nitrogen)),
            "total_observations": int(len(observations)),
            "density": DENSITY,
        },
    )


# ----------------------------------------------------------------------------
# 2025 秋季
# ----------------------------------------------------------------------------

def load_2025_fall(root: Path, dm_method: str = "mean", min_fruit_dry_weight: float = 10.0) -> SeasonResult:
    folder = root / "2025秋"
    # --- Yield ---
    y = pd.read_excel(folder / "2025秋季产量集.xlsx", sheet_name="2025秋季产量集")
    y["日期"] = parse_yyyymmdd(y["日期"])
    y["TRNO"] = pd.to_numeric(y["小区号"], errors="coerce").astype("Int64")
    y = y.dropna(subset=["TRNO", "日期"]).copy()
    y["TRNO"] = y["TRNO"].astype(int)
    require_columns(y, ["TRNO", "日期", "重复", "小区产量", "水处理", "氮处理"], "2025秋产量")

    # Per (TRNO, date): mean 小区产量 across reps; SD from reps
    yield_rows = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        vals = grp["小区产量"].dropna().values
        sd, src, n = hybrid_sd(vals)
        yield_rows.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": float(np.mean(vals)),
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Growth (茎干重, 叶干重, 果干重, 果含水率, LAI) ---
    g = pd.read_excel(folder / "2025年秋季茄子生长指标集.xlsx", sheet_name="Sheet1")
    # Normalize column names (strip whitespace)
    g = g.rename(columns={c: str(c).strip() for c in g.columns})
    require_columns(g, ["日期", "小区", "行号", "茎干重", "叶干重", "果干重", "果含水率", "LAI", "水处理", "氮处理"], "2025秋生长")
    g["日期"] = pd.to_datetime(g["日期"], errors="coerce").dt.normalize()
    g["TRNO"] = pd.to_numeric(g["小区"], errors="coerce").astype("Int64")
    g = g.dropna(subset=["TRNO", "日期"]).copy()
    g["TRNO"] = g["TRNO"].astype(int)

    # --- DMFR from 果含水率 (DMFR = 1 - moisture) with IQR filtering ---
    candidates = g[g["果含水率"].notna()].copy()
    candidates["DMFR"] = 1.0 - candidates["果含水率"]
    # User-specified outliers
    manual_mask = (
        ((candidates["日期"] == pd.Timestamp("2025-12-08")) & (candidates["TRNO"] == 2) & (candidates["行号"] == 1))
        | ((candidates["日期"] == pd.Timestamp("2026-01-10")) & (candidates["TRNO"] == 11) & (candidates["行号"] == 1))
    )
    low_weight_mask = ~manual_mask & (candidates["果干重"] < min_fruit_dry_weight)
    reliable_mask = ~manual_mask & ~low_weight_mask
    # Date-specific IQR
    iqr_mask = pd.Series(False, index=candidates.index)
    for date, dg in candidates.loc[reliable_mask].groupby("日期"):
        q1, q3 = dg["DMFR"].quantile([0.25, 0.75])
        spread = q3 - q1
        iqr_mask.loc[dg.index] = ~dg["DMFR"].between(q1 - 1.5 * spread, q3 + 1.5 * spread)
    kept_mask = reliable_mask & ~iqr_mask

    # Aggregate DMFR per (TRNO, date)
    kept = candidates.loc[kept_mask].copy()
    dm_rows = []
    for (trno, date), grp in kept.groupby(["TRNO", "日期"]):
        if dm_method == "mean":
            dmfr = float(grp["DMFR"].mean())
        elif dm_method == "median":
            dmfr = float(grp["DMFR"].median())
        else:  # pooled
            dmfr = float(grp["果干重"].sum() / grp["果鲜重"].sum())
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_rows.append({"TRNO": int(trno), "GROWTH_DATE": date, "DMFR": dmfr,
                        "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_by_plot = pd.DataFrame(dm_rows)

    # --- Match harvest to nearest DMFR ---
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

    harvest = matched[["TRNO", "HARVEST_DATE", "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE"})
    harvest_obs = matched[["TRNO", "HARVEST_DATE", "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
                           "fresh_sd", "fresh_sd_source", "fresh_n_rep",
                           "dry_sd", "dry_sd_source",
                           "chfpw_sd", "chfpw_sd_source",
                           "chpdt_sd", "chpdt_sd_source",
                           "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep"]].rename(
        columns={"HARVEST_DATE": "DATE"})

    # --- Growth summary (LAID, SWAD, LWAD) ---
    growth_rows = []
    for (trno, date), grp in g.groupby(["TRNO", "日期"]):
        lai_vals = grp["LAI"].dropna().values
        stem_vals = grp["茎干重"].dropna().values
        leaf_vals = grp["叶干重"].dropna().values
        lai_sd, lai_src, lai_n = hybrid_sd(lai_vals)
        stem_sd, stem_src, stem_n = hybrid_sd(stem_vals)
        leaf_sd, leaf_src, leaf_n = hybrid_sd(leaf_vals)
        growth_rows.append({
            "TRNO": int(trno), "DATE": date,
            "LAID": float(np.mean(lai_vals)) if len(lai_vals) else np.nan,
            "SWAD": float(np.mean(stem_vals)) * FACTOR if len(stem_vals) else np.nan,
            "LWAD": float(np.mean(leaf_vals)) * FACTOR if len(leaf_vals) else np.nan,
            "LAID_sd": lai_sd, "LAID_sd_source": lai_src, "LAID_n_rep": lai_n,
            "SWAD_sd": stem_sd * FACTOR if not pd.isna(stem_sd) else np.nan,
            "SWAD_sd_source": stem_src, "SWAD_n_rep": stem_n,
            "LWAD_sd": leaf_sd * FACTOR if not pd.isna(leaf_sd) else np.nan,
            "LWAD_sd_source": leaf_src, "LWAD_n_rep": leaf_n,
        })
    growth = pd.DataFrame(growth_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Nitrogen ---
    n = pd.read_excel(folder / "2025年秋季茄子植株样氮磷钾测定.xlsx", sheet_name="Sheet1", usecols="A:I")
    require_columns(n, ["取样日期", "取样部位", "小区号", "重复", "全氮（mg/g)"], "2025秋养分")
    n["TRNO"] = pd.to_numeric(n["小区号"], errors="coerce").astype("Int64")
    n = n.dropna(subset=["TRNO"]).copy()
    n["TRNO"] = n["TRNO"].astype(int)
    n["取样日期"] = pd.to_datetime(n["取样日期"], errors="coerce").dt.normalize()
    wide = n.pivot_table(index=["TRNO", "取样日期", "重复"], columns="取样部位", values="全氮（mg/g)", aggfunc="first").reset_index()
    wide = wide.rename(columns={"取样日期": "DATE"})
    # Aggregate growth by (TRNO, date) for mean stem/leaf dry weight
    growth_mean = (g.groupby(["TRNO", "日期"], as_index=False)
                  .agg(STEM_G=("茎干重", "mean"), LEAF_G=("叶干重", "mean"))
                  .rename(columns={"日期": "GROWTH_DATE"}))
    growth_mean = growth_mean.dropna(subset=["STEM_G", "LEAF_G"])
    date_match = nearest_by_plot(wide[["TRNO", "DATE"]].drop_duplicates(), growth_mean[["TRNO", "GROWTH_DATE"]].drop_duplicates(), "DATE", "GROWTH_DATE")
    wide = wide.merge(date_match[["TRNO", "DATE", "GROWTH_DATE", "MATCH_DAYS"]], on=["TRNO", "DATE"], validate="many_to_one")
    wide = wide.merge(growth_mean, on=["TRNO", "GROWTH_DATE"], validate="many_to_one")
    if "茎" in wide.columns:
        wide["SNAM"] = wide["STEM_G"] * FACTOR * wide["茎"] / 1000.0
    if "叶" in wide.columns:
        wide["LNAM"] = wide["LEAF_G"] * FACTOR * wide["叶"] / 1000.0
    if "SNAM" in wide.columns and "LNAM" in wide.columns:
        wide["CNAM"] = wide["SNAM"] + wide["LNAM"]
    n_rows = []
    for (trno, date), grp in wide.groupby(["TRNO", "DATE"]):
        snam_vals = grp["SNAM"].dropna().values if "SNAM" in grp.columns else np.array([])
        lnam_vals = grp["LNAM"].dropna().values if "LNAM" in grp.columns else np.array([])
        cnam_vals = grp["CNAM"].dropna().values if "CNAM" in grp.columns else np.array([])
        snam_sd, snam_src, snam_n = hybrid_sd(snam_vals)
        lnam_sd, lnam_src, lnam_n = hybrid_sd(lnam_vals)
        cnam_sd, cnam_src, cnam_n = hybrid_sd(cnam_vals)
        n_rows.append({
            "TRNO": int(trno), "DATE": date,
            "CNAM": float(np.mean(cnam_vals)) if len(cnam_vals) else np.nan,
            "SNAM": float(np.mean(snam_vals)) if len(snam_vals) else np.nan,
            "LNAM": float(np.mean(lnam_vals)) if len(lnam_vals) else np.nan,
            "CNAM_sd": cnam_sd, "CNAM_sd_source": cnam_src, "CNAM_n_rep": cnam_n,
            "SNAM_sd": snam_sd, "SNAM_sd_source": snam_src, "SNAM_n_rep": snam_n,
            "LNAM_sd": lnam_sd, "LNAM_sd_source": lnam_src, "LNAM_n_rep": lnam_n,
        })
    nitrogen = pd.DataFrame(n_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- FileA ---
    filea_rows = []
    for trno in sorted(harvest["TRNO"].unique()):
        h = harvest[harvest["TRNO"] == trno].sort_values("DATE")
        final = h.iloc[-1]
        g_trno = growth[growth["TRNO"] == trno]
        n_trno = nitrogen[nitrogen["TRNO"] == trno]
        laix = float(g_trno["LAID"].max()) if not g_trno.empty and g_trno["LAID"].notna().any() else np.nan
        laix_sd, laix_src, laix_n = (hybrid_sd(g_trno["LAID"].dropna().values) if not g_trno.empty else (float("nan"), "no_data", 0))
        lwam = float(g_trno["LWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["LWAD"].iloc[-1]) else np.nan
        swam = float(g_trno["SWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["SWAD"].iloc[-1]) else np.nan
        lwam_sd = float(g_trno["LWAD_sd"].iloc[-1]) if "LWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        swam_sd = float(g_trno["SWAD_sd"].iloc[-1]) if "SWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        cnam = float(n_trno["CNAM"].iloc[-1]) if not n_trno.empty and pd.notna(n_trno["CNAM"].iloc[-1]) else np.nan
        cnam_sd = float(n_trno["CNAM_sd"].iloc[-1]) if not n_trno.empty else np.nan
        hwam = float(final["CHPDT"])
        hwam_sd = float(harvest_obs[harvest_obs["TRNO"] == trno]["chpdt_sd"].iloc[-1])
        filea_rows.append({
            "TRNO": int(trno), "PDAT": np.nan, "ADAT": np.nan, "MDAT": np.nan,
            "HDAT": final["DATE"], "HWAM": hwam, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "CNAM": cnam,
            "HWAM_sd": hwam_sd, "HWAM_sd_source": "final_cumulative_dry",
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth",
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth",
            "CNAM_sd": cnam_sd, "CNAM_sd_source": "last_obs_nitrogen",
        })
    filea = pd.DataFrame(filea_rows)

    # --- Observations ---
    obs_rows = []
    for r in filea.itertuples(index=False):
        trno = int(r.TRNO)
        for var, sd_var, src_var in [("HWAM", "HWAM_sd", "HWAM_sd_source"),
                                      ("LAIX", "LAIX_sd", "LAIX_sd_source"),
                                      ("LWAM", "LWAM_sd", "LWAM_sd_source"),
                                      ("SWAM", "SWAM_sd", "SWAM_sd_source"),
                                      ("CNAM", "CNAM_sd", "CNAM_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "joint_season_end", "sim_token": var, "model_output_file": "Evaluate.OUT",
                    "trno": trno, "date": yrdoy(r.HDAT) if pd.notna(r.HDAT) else -99,
                    "variable": var, "n_rep": getattr(r, f"{var}_n_rep", 1) if hasattr(r, f"{var}_n_rep") else 1,
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    for r in growth.itertuples(index=False):
        trno = int(r.TRNO); date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("LAID", "LAID_sd", "LAID_sd_source"),
                                      ("SWAD", "SWAD_sd", "SWAD_sd_source"),
                                      ("LWAD", "LWAD_sd", "LWAD_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "growth_process", "sim_token": var, "model_output_file": "PlantGro.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": getattr(r, f"{var}_n_rep", 1), "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    for r in nitrogen.itertuples(index=False):
        trno = int(r.TRNO); date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("CNAM", "CNAM_sd", "CNAM_sd_source"),
                                      ("SNAM", "SNAM_sd", "SNAM_sd_source"),
                                      ("LNAM", "LNAM_sd", "LNAM_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "growth_process", "sim_token": var, "model_output_file": "PlantGro.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": getattr(r, f"{var}_n_rep", 1), "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    for r in harvest_obs.itertuples(index=False):
        trno = int(r.TRNO); date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("CHFPW", "chfpw_sd", "chfpw_sd_source"),
                                      ("CHPDT", "chpdt_sd", "chpdt_sd_source"),
                                      ("HFPOW", "fresh_sd", "fresh_sd_source"),
                                      ("HPODW", "dry_sd", "dry_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "harvest_event", "sim_token": var, "model_output_file": "FreshWt.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": int(getattr(r, "fresh_n_rep", 1) if var in ("CHFPW", "HFPOW") else 1),
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    observations = pd.DataFrame(obs_rows)

    return SeasonResult(
        key="2025fall", output_base="2025FALL",
        title="2025 FALL EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield is a per-harvest measurement (mean across replicates), cumulatively summed by plot.",
            f"Dry harvested yield uses the nearest measured plot fruit DM fraction ({dm_method}).",
            f"Fruit DM samples below the dry-weight threshold ({min_fruit_dry_weight}g) are excluded.",
            "Remaining DM fractions are screened within measurement date using Tukey 1.5*IQR fences.",
            "Two user-identified fruit DM outliers are always excluded.",
            "SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).",
        ],
        growth=growth, nitrogen=nitrogen, harvest=harvest, filea=filea,
        observations=observations,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "dmfr_samples_kept": int(kept_mask.sum()),
            "dmfr_samples_excluded_user": int(manual_mask.sum()),
            "dmfr_samples_excluded_low_weight": int(low_weight_mask.sum()),
            "dmfr_samples_excluded_iqr": int(iqr_mask.sum()),
            "nitrogen_rows": int(len(nitrogen)),
            "total_observations": int(len(observations)),
            "density": DENSITY,
        },
    )


# ----------------------------------------------------------------------------
# 2026 春季
# ----------------------------------------------------------------------------

def load_2026_spring(root: Path) -> SeasonResult:
    folder = root / "2026春"
    # --- Yield ---
    y = pd.read_excel(folder / "2026春产量集.xlsx", sheet_name="Sheet1")
    y["TRNO"] = pd.to_numeric(y["小区号"], errors="coerce")
    y = y[y["TRNO"].notna()].copy()
    y["TRNO"] = y["TRNO"].astype(int)
    y["日期"] = parse_yyyymmdd(y["日期"])
    require_columns(y, ["TRNO", "日期", "重复", "小区产量", "水处理", "氮处理"], "2026春产量")

    yield_rows = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        vals = grp["小区产量"].dropna().values
        sd, src, n = hybrid_sd(vals)
        yield_rows.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": float(np.mean(vals)),
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Quality -> DMFR (1 - 半果含水率) ---
    q = pd.read_excel(folder / "2026春品质指标集.xlsx", sheet_name="Sheet1")
    moisture_col = "半果含水率" if "半果含水率" in q.columns else "含水率"
    require_columns(q, ["日期", "小区号", "重复", moisture_col, "水处理", "氮处理"], "2026春品质")
    q["TRNO"] = pd.to_numeric(q["小区号"], errors="coerce").astype("Int64")
    q = q.dropna(subset=["TRNO"]).copy()
    q["TRNO"] = q["TRNO"].astype(int)
    q["QUALITY_DATE"] = parse_yyyymmdd(q["日期"])
    q["DMFR"] = 1.0 - pd.to_numeric(q[moisture_col], errors="coerce")

    dm_rows = []
    for (trno, date), grp in q.groupby(["TRNO", "QUALITY_DATE"]):
        vals = grp["DMFR"].dropna().values
        sd, src, n = hybrid_sd(vals)
        dm_rows.append({"TRNO": int(trno), "GROWTH_DATE": date,
                        "DMFR": float(np.mean(vals)), "DMFR_sd": sd,
                        "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_by_plot = pd.DataFrame(dm_rows)

    # --- Match harvest to nearest DMFR ---
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

    harvest = matched[["TRNO", "HARVEST_DATE", "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE"})
    harvest_obs = matched[["TRNO", "HARVEST_DATE", "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
                           "fresh_sd", "fresh_sd_source", "fresh_n_rep",
                           "dry_sd", "dry_sd_source",
                           "chfpw_sd", "chfpw_sd_source",
                           "chpdt_sd", "chpdt_sd_source",
                           "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep"]].rename(
        columns={"HARVEST_DATE": "DATE"})

    # --- Growth (4 sheets: 0502, 0602, 0629, 0717) ---
    growth_frames = []
    # 0502: 小区, 重复, 茎干重, 叶干重, LAI, 取样日期
    g1 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0502")
    require_columns(g1, ["取样日期", "小区", "重复", "茎干重", "叶干重", "LAI", "水处理", "氮处理"], "2026春 0502")
    g1["TRNO"] = pd.to_numeric(g1["小区"], errors="coerce").astype("Int64")
    g1 = g1.dropna(subset=["TRNO"]).copy()
    g1["TRNO"] = g1["TRNO"].astype(int)
    g1["DATE"] = parse_yyyymmdd(g1["取样日期"])
    g1["SOURCE"] = "0502"
    growth_frames.append(g1)

    # 0602: 处理, 重复, 茎干重, 叶干重, LAI
    g2 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0602")
    require_columns(g2, ["处理", "重复", "茎干重", "叶干重", "LAI", "水处理", "氮处理"], "2026春 0602")
    g2["TRNO"] = pd.to_numeric(g2["处理"], errors="coerce").astype("Int64")
    g2 = g2.dropna(subset=["TRNO"]).copy()
    g2["TRNO"] = g2["TRNO"].astype(int)
    # 0602 has no 取样日期; use 2026-06-02 as the date
    g2["DATE"] = pd.Timestamp("2026-06-02")
    g2["SOURCE"] = "0602"
    growth_frames.append(g2)

    # 0629: 处理 (Treatment), 重复, 茎干重, 叶干重 (no LAI)
    g3 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0629")
    require_columns(g3, ["处理 (Treatment)", "重复", "茎干重", "叶干重", "水处理", "氮处理"], "2026春 0629")
    g3["TRNO"] = pd.to_numeric(g3["处理 (Treatment)"], errors="coerce").astype("Int64")
    g3 = g3.dropna(subset=["TRNO"]).copy()
    g3["TRNO"] = g3["TRNO"].astype(int)
    g3["DATE"] = pd.Timestamp("2026-06-29")
    g3["LAI"] = np.nan
    g3["SOURCE"] = "0629"
    growth_frames.append(g3)

    # 0717: 日期, 处理, 重复, 茎干重, 叶干重, LAI
    g4 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0717")
    require_columns(g4, ["日期", "处理", "重复", "茎干重", "叶干重", "LAI", "水处理", "氮处理"], "2026春 0717")
    g4["TRNO"] = pd.to_numeric(g4["处理"], errors="coerce").astype("Int64")
    g4 = g4.dropna(subset=["TRNO"]).copy()
    g4["TRNO"] = g4["TRNO"].astype(int)
    g4["DATE"] = parse_yyyymmdd(g4["日期"])
    g4["SOURCE"] = "0717"
    growth_frames.append(g4)

    g_all = pd.concat(growth_frames, ignore_index=True, sort=False)
    g_all = g_all.dropna(subset=["DATE"]).copy()

    growth_rows = []
    for (trno, date), grp in g_all.groupby(["TRNO", "DATE"]):
        lai_vals = grp["LAI"].dropna().values
        stem_vals = grp["茎干重"].dropna().values
        leaf_vals = grp["叶干重"].dropna().values
        lai_sd, lai_src, lai_n = hybrid_sd(lai_vals)
        stem_sd, stem_src, stem_n = hybrid_sd(stem_vals)
        leaf_sd, leaf_src, leaf_n = hybrid_sd(leaf_vals)
        growth_rows.append({
            "TRNO": int(trno), "DATE": date,
            "LAID": float(np.mean(lai_vals)) if len(lai_vals) else np.nan,
            "SWAD": float(np.mean(stem_vals)) * FACTOR if len(stem_vals) else np.nan,
            "LWAD": float(np.mean(leaf_vals)) * FACTOR if len(leaf_vals) else np.nan,
            "LAID_sd": lai_sd, "LAID_sd_source": lai_src, "LAID_n_rep": lai_n,
            "SWAD_sd": stem_sd * FACTOR if not pd.isna(stem_sd) else np.nan,
            "SWAD_sd_source": stem_src, "SWAD_n_rep": stem_n,
            "LWAD_sd": leaf_sd * FACTOR if not pd.isna(leaf_sd) else np.nan,
            "LWAD_sd_source": leaf_src, "LWAD_n_rep": leaf_n,
        })
    growth = pd.DataFrame(growth_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)
    nitrogen = pd.DataFrame(columns=["TRNO", "DATE", "CNAM", "SNAM", "LNAM"])

    # --- FileA ---
    filea_rows = []
    for trno in sorted(harvest["TRNO"].unique()):
        h = harvest[harvest["TRNO"] == trno].sort_values("DATE")
        final = h.iloc[-1]
        g_trno = growth[growth["TRNO"] == trno]
        laix = float(g_trno["LAID"].max()) if not g_trno.empty and g_trno["LAID"].notna().any() else np.nan
        laix_sd, laix_src, laix_n = (hybrid_sd(g_trno["LAID"].dropna().values) if not g_trno.empty else (float("nan"), "no_data", 0))
        lwam = float(g_trno["LWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["LWAD"].iloc[-1]) else np.nan
        swam = float(g_trno["SWAD"].iloc[-1]) if not g_trno.empty and pd.notna(g_trno["SWAD"].iloc[-1]) else np.nan
        lwam_sd = float(g_trno["LWAD_sd"].iloc[-1]) if "LWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        swam_sd = float(g_trno["SWAD_sd"].iloc[-1]) if "SWAD_sd" in g_trno.columns and not g_trno.empty else np.nan
        hwam = float(final["CHPDT"])
        hwam_sd = float(harvest_obs[harvest_obs["TRNO"] == trno]["chpdt_sd"].iloc[-1])
        filea_rows.append({
            "TRNO": int(trno), "PDAT": np.nan, "ADAT": np.nan, "MDAT": np.nan,
            "HDAT": final["DATE"], "HWAM": hwam, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "CNAM": np.nan,
            "HWAM_sd": hwam_sd, "HWAM_sd_source": "final_cumulative_dry",
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth",
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth",
            "CNAM_sd": np.nan, "CNAM_sd_source": "no_nitrogen_data",
        })
    filea = pd.DataFrame(filea_rows)

    # --- Observations ---
    obs_rows = []
    for r in filea.itertuples(index=False):
        trno = int(r.TRNO)
        for var, sd_var, src_var in [("HWAM", "HWAM_sd", "HWAM_sd_source"),
                                      ("LAIX", "LAIX_sd", "LAIX_sd_source"),
                                      ("LWAM", "LWAM_sd", "LWAM_sd_source"),
                                      ("SWAM", "SWAM_sd", "SWAM_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "joint_season_end", "sim_token": var, "model_output_file": "Evaluate.OUT",
                    "trno": trno, "date": yrdoy(r.HDAT) if pd.notna(r.HDAT) else -99,
                    "variable": var, "n_rep": getattr(r, f"{var}_n_rep", 1) if hasattr(r, f"{var}_n_rep") else 1,
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    for r in growth.itertuples(index=False):
        trno = int(r.TRNO); date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("LAID", "LAID_sd", "LAID_sd_source"),
                                      ("SWAD", "SWAD_sd", "SWAD_sd_source"),
                                      ("LWAD", "LWAD_sd", "LWAD_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "growth_process", "sim_token": var, "model_output_file": "PlantGro.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": getattr(r, f"{var}_n_rep", 1), "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    for r in harvest_obs.itertuples(index=False):
        trno = int(r.TRNO); date_code = yrdoy(r.DATE)
        for var, sd_var, src_var in [("CHFPW", "chfpw_sd", "chfpw_sd_source"),
                                      ("CHPDT", "chpdt_sd", "chpdt_sd_source"),
                                      ("HFPOW", "fresh_sd", "fresh_sd_source"),
                                      ("HPODW", "dry_sd", "dry_sd_source")]:
            val = getattr(r, var); sd = getattr(r, sd_var)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                obs_rows.append({
                    "obsnme": f"{var.lower()}_t{trno}_d{date_code}", "obsval": float(val), "weight": 1.0 / float(sd),
                    "obgnme": "harvest_event", "sim_token": var, "model_output_file": "FreshWt.OUT",
                    "trno": trno, "date": date_code, "variable": var,
                    "n_rep": int(getattr(r, "fresh_n_rep", 1) if var in ("CHFPW", "HFPOW") else 1),
                    "sd": float(sd), "sd_source": getattr(r, src_var),
                })
    observations = pd.DataFrame(obs_rows)

    return SeasonResult(
        key="2026spring", output_base="2026SPR",
        title="2026 SPRING EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield is a per-harvest measurement (mean across replicates), cumulatively summed by plot.",
            "Fruit DM fraction = 1 - measured half-fruit moisture fraction (2026春品质指标集.半果含水率).",
            "Each harvest uses the nearest plot-level quality measurement date.",
            "2026春 has no nitrogen data; SNAM/LNAM/CNAM are -99.",
            "SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).",
        ],
        growth=growth, nitrogen=nitrogen, harvest=harvest, filea=filea,
        observations=observations,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "quality_dates": int(dm_by_plot["GROWTH_DATE"].nunique()),
            "total_observations": int(len(observations)),
            "density": DENSITY,
        },
    )


# ----------------------------------------------------------------------------
# Build TMT / TMA / Observations
# ----------------------------------------------------------------------------

def prepare_filet(result: SeasonResult) -> pd.DataFrame:
    """Combine growth + nitrogen + harvest into a single TMT dataframe."""
    frames = []
    for frame in (result.growth, result.nitrogen, result.harvest):
        if not frame.empty:
            sub = frame[["TRNO", "DATE"] + [c for c in TMT_COLUMNS if c in frame.columns and c not in ("TRNO", "DATE")]].copy()
            frames.append(sub)
    if not frames:
        return pd.DataFrame(columns=TMT_COLUMNS)
    stacked = pd.concat(frames, ignore_index=True, sort=False)
    # Group by (TRNO, DATE) and take first non-null
    def first_nonnull(s):
        v = s.dropna()
        return np.nan if v.empty else v.iloc[0]
    filet = stacked.groupby(["TRNO", "DATE"], as_index=False).agg(first_nonnull)
    for col in TMT_COLUMNS:
        if col not in filet:
            filet[col] = np.nan
    return filet[TMT_COLUMNS].sort_values(["TRNO", "DATE"]).reset_index(drop=True)


def prepare_filea(result: SeasonResult) -> pd.DataFrame:
    """FileA is already built in result.filea; ensure column order."""
    df = result.filea.copy()
    for col in TMA_COLUMNS:
        if col not in df:
            df[col] = np.nan
    return df[TMA_COLUMNS].sort_values("TRNO").reset_index(drop=True)


def write_csv(path: Path, df: pd.DataFrame) -> None:
    export = df.copy()
    for dc in ("DATE", "HDAT", "PDAT", "ADAT", "MDAT"):
        if dc in export:
            export[dc] = export[dc].map(lambda v: yrdoy(v) if pd.notna(v) else -99)
    export = export.fillna(MISSING)
    export.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")


def write_observations(path: Path, observations: pd.DataFrame) -> None:
    observations.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")


def write_qa(path: Path, result: SeasonResult, filea: pd.DataFrame, filet: pd.DataFrame) -> None:
    harvest_rows = filet[filet[["CHFPW", "CHPDT"]].notna().any(axis=1)]
    lines = [
        f"# {result.title.split(';')[0]} DSSAT File A / File T 质量检查",
        "",
        "## 输出摘要",
        "",
        f"- File A：{len(filea)} 行，TRNO {int(filea['TRNO'].min())}–{int(filea['TRNO'].max())}。",
        f"- File T：{len(filet)} 行，{filet['DATE'].nunique()} 个不同观测日。",
        f"- 含采收数据的 File T 行：{len(harvest_rows)}。",
        f"- 观测总数 (PEST++ CSV)：{len(result.observations)}。",
        "",
        "## 列结构 (参考 XXQL2501.TMA/TMT)",
        "",
        f"- File A: `{'  '.join(TMA_COLUMNS)}`",
        f"- File T: `{'  '.join(TMT_COLUMNS)}`",
        "",
        "## 源数据与换算",
        "",
        *[f"- {n}" for n in result.source_notes],
        "",
        "## 关键指标",
        "",
    ]
    for k, v in result.qa_metrics.items():
        lines.append(f"- `{k}`: {v}")
    lines.extend(["", "## SD 计算方案", "",
                  "- 混合方法：重复数 >= 2 时用样本 SD (ddof=1)，CV < 5% 时取 5%*|mean| 为下限；重复数 < 2 时用固定 CV=10%。",
                  "- 累计产量 SD：通过增量方差求和 (sqrt(Σvar_inc)) 传播。",
                  "- 干产量 SD：通过 fresh_sd 和 DMFR_sd 误差传播 (sqrt(DMFR²·var_fresh + fresh²·var_DMFR))。",
                  ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_one(result: SeasonResult, root: Path) -> dict[str, Path]:
    filet = prepare_filet(result)
    filea = prepare_filea(result)
    season_folder = {"2025spring": "2025春", "2025fall": "2025秋", "2026spring": "2026春"}[result.key]
    folder = root / season_folder / "DSSAT输出"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "filea": folder / f"{result.output_base}.TMA",
        "filet": folder / f"{result.output_base}.TMT",
        "observations": folder / f"{result.output_base}_observations.csv",
        "filea_csv": folder / f"{result.output_base}_FileA_values.csv",
        "filet_csv": folder / f"{result.output_base}_FileT_values.csv",
        "qa": folder / f"{result.output_base}_QA.md",
    }
    comments_tma = [
        "Full reference column structure (matches XXQL2501.TMA).",
        "PDAT/ADAT/MDAT/HIAM are -99 (phenology/harvest-index not measured).",
        "HWAM = final cumulative DRY fruit yield (kg/ha).",
        "LWAM/SWAM = last observed leaf/stem dry weight (kg/ha).",
        "LAIX = seasonal max LAI. CNAM = last observed canopy N (kg/ha).",
    ]
    comments_tmt = [
        "Full reference column structure (matches XXQL2501.TMT).",
        "CHFPW/CHPDT cumulative; HFPOW/HPODW incremental; PDMCD = fruit DM fraction.",
        "LAID/SWAD/LWAD daily; CNAM/SNAM/LNAM daily N (kg/ha).",
        "Missing values = -99; dates = YYDDD.",
    ]
    write_dssat_file(paths["filea"], "A", result.title, comments_tma, filea)
    write_dssat_file(paths["filet"], "T", result.title, comments_tmt, filet)
    write_csv(paths["filea_csv"], filea)
    write_csv(paths["filet_csv"], filet)
    write_observations(paths["observations"], result.observations)
    write_qa(paths["qa"], result, filea, filet)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 2025春/2025秋/2026春 DSSAT FileA/FileT + PEST++ 观测文件 (v2, 参考格式)")
    parser.add_argument("--season", action="append", choices=("2025spring", "2025fall", "2026spring"))
    parser.add_argument("--dm-method", choices=("mean", "median", "pooled"), default="mean")
    parser.add_argument("--min-fruit-dry-weight", type=float, default=10.0)
    args = parser.parse_args()
    seasons = args.season or ["2025spring", "2025fall", "2026spring"]
    root = Path(__file__).resolve().parent
    loaders = {
        "2025spring": lambda: load_2025_spring(root),
        "2025fall": lambda: load_2025_fall(root, args.dm_method, args.min_fruit_dry_weight),
        "2026spring": lambda: load_2026_spring(root),
    }
    for key in seasons:
        result = loaders[key]()
        paths = build_one(result, root)
        print(f"{key}:")
        for p in paths.values():
            print(f"  {p}")


if __name__ == "__main__":
    main()
