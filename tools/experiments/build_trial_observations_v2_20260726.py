#!/usr/bin/env python3
"""Build DSSAT FileA/FileT + observation uncertainty tables for 25SP/25FA/26SP.

Complies with docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md:

Phenology and harvest contract (2026-07-26):
  FileA carries measured PDAT/ADAT and MDAT as a documented PODD proxy; HDAT is
  retained for reference only and is never added to Phi.  PDAT is read from
  the corresponding FileX transplant date, not inferred from seedling age.
  FileT carries process states plus both cumulative CHPDT and incremental HPODW.
  PWAD/PWAI/HWAM/CNAM/PDMCD remain excluded from calibration.

25SP treatment exclusion (Section 6.1):
  Only TN 2,3,4,5,9,10,11,12,13,14 (10 treatments); TN 1,6,7,8 excluded with audit.

DMFR matching (Section 4):
  Half-fruit moisture -> DMFR = 1 - moisture_fraction (units must be 0-1, not 0-100).
  Each harvest uses nearest plot-level moisture measurement date, NO max interval.
  match_status = "nearest_unbounded"; match_days and quality_date recorded per row.

observation_uncertainty.csv (Section 3.1 schema, NO PEST weight column):
  season_id, excode, trno, date, variable, value, raw_sd, n_rep, sd_method,
  source_workbook, source_sheet, source_row_rule, quality_flag

  CHPDT raw_sd: incremental fresh-yield and DMFR variance propagation, then
  cumulative sum of incremental variances (sqrt).  Incremental raw_sd retained
  via separate rows so cumulative events are not mistaken for independent reps.

fruit_quality_match_audit.csv (Section 4):
  trno, harvest_date, quality_date, match_days, fresh_yield, fresh_sd,
  dmfr, dmfr_sd, dry_increment, dry_increment_sd, chpdt, chpdt_sd, match_status

treatment_exclusion_audit.csv (Section 6.1, 25SP only):
  season_id, trno, reason

SD hybrid method (Section 3.1):
  * n_rep >= 2: sample SD (ddof=1); if SD/|mean| < 0.05, use 0.05*|mean| (min CV=5%)
  * n_rep < 2: 0.10*|mean| fallback CV=10% (or 0.10 if mean==0)

Output directory layout (per season):
  {season_folder}/DSSAT输出_v2/
    {EXCODE}.TMA                          (text FileA, 6-char fixed width)
    {EXCODE}.TMT                          (text FileT, 6-char fixed width)
    observation_uncertainty.csv           (NO PEST weight)
    fruit_quality_match_audit.csv         (harvest↔moisture match audit)
    treatment_exclusion_audit.csv         (only 25SP)
    FileA_values.csv, FileT_values.csv    (human-readable copies)
    generator_log.json                    (provenance: source files + SHA-256)

Reference format: data/user/ref/XXQL2501.TMX management schedule;
observations are written to the season's ``DSSAT输出_v2`` directory.
"""
from __future__ import annotations
import csv

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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.common.experiment_inputs import filex_observed_harvest_dates


MISSING = -99.0
DENSITY = 27000.0  # plants/ha
FACTOR = DENSITY / 1000.0  # g/plant -> kg/ha

# 25SP treatment exclusion: only FileX-definable TNs are kept
SPRING25_INCLUDED_TN = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
SPRING25_EXCLUDED_TN = [1, 6, 7, 8]
SPRING25_EXCLUSION_REASON = "缺少实际 FileX 管理/初始条件定义"

# Full reference column structures (matches XXQL2501.TMA / .TMT)
TMA_COLUMNS = ["TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "HWAM", "LWAM", "SWAM", "LAIX", "HIAM", "CNAM"]
TMT_COLUMNS = [
    "TRNO", "DATE", "L#SD", "LAID", "L#PA", "LWAD", "RWAD", "SWAD",
    "M#AD", "SLAD", "CHTD", "CWID", "CNAM", "SNAM", "LNAM",
    "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
]

# Per-column decimal places for 6-char field formatting
DECIMALS = {
    "LAID": 3, "LAIX": 3, "CHTD": 3,
    "PDMCD": 3, "HIAM": 3,
}
INTEGER_COLS = {"TRNO", "DATE", "PDAT", "ADAT", "MDAT", "HDAT",
                "L#SD", "L#PA", "M#AD",
                "LWAD", "RWAD", "SWAD", "SLAD", "CWID",
                "HWAM", "LWAM", "SWAM",
                "HFPOW", "CHFPW", "HPODW", "CHPDT",
                "CNAM", "SNAM", "LNAM"}

# Strict fill rules: only these columns receive measured values; all others = -99
TMA_FILL = {"TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "LWAM", "SWAM", "LAIX"}
TMT_FILL = {"TRNO", "DATE", "LAID", "LWAD", "SWAD", "CHTD", "CHFPW", "HPODW", "CHPDT"}

PHENOLOGY_DATES = {
    "25SP": {"ADAT": pd.Timestamp("2025-04-22"), "PODD": pd.Timestamp("2025-05-04")},
    "25FA": {"ADAT": pd.Timestamp("2025-09-10"), "PODD": pd.Timestamp("2025-09-17")},
    "26SP": {"ADAT": pd.Timestamp("2026-04-20"), "PODD": pd.Timestamp("2026-05-02")},
}

EXPERIMENTS_ROOT = Path(r"D:\Tomato_Cal\data\user\experiments")


def phenology_filea_values(season_id: str, excode: str) -> tuple[int, int, int]:
    """Return DSSAT YYDDD PDAT, ADAT and MDAT(PODD proxy) values."""
    pdat = filex_transplant_date(EXPERIMENTS_ROOT / excode / f"{excode}.TMX")
    dates = PHENOLOGY_DATES[season_id]
    return yrdoy(pdat), yrdoy(dates["ADAT"]), yrdoy(dates["PODD"])


def filex_transplant_date(path: Path) -> pd.Timestamp:
    """Read the first DSSAT @P PDATE value from a TMX/FileX file."""
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    for idx, line in enumerate(lines):
        if line.strip().upper().startswith("@P "):
            for candidate in lines[idx + 1: idx + 4]:
                parts = candidate.split()
                if len(parts) >= 2:
                    try:
                        code = int(float(parts[1]))
                        yy = 2000 + code // 1000
                        doy = code % 1000
                        return pd.Timestamp(yy, 1, 1) + pd.Timedelta(days=doy - 1)
                    except (TypeError, ValueError, OverflowError):
                        pass
    raise ValueError(f"FileX has no parseable @P PDATE: {path}")


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


def hybrid_sd(values, min_cv: float = 0.05, fallback_cv: float = 0.10):
    """Compute hybrid SD.

    Returns (sd, sd_method, n_rep).
    * n_rep >= 2: sample SD (ddof=1); if SD/|mean| < min_cv, use min_cv*|mean|.
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


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def nearest_by_plot(left: pd.DataFrame, right: pd.DataFrame, left_date: str, right_date: str) -> pd.DataFrame:
    """For each row in left, find the nearest-date row in right (same TRNO).

    Records match_days; match_status is set to "nearest_unbounded" by the caller
    (no max-interval filter, per docs Section 4).
    """
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

def format_field(column: str, value, fill: bool) -> str:
    """Format a value into a 6-char right-aligned field.

    If `fill` is False, always emit -99 (strict fill rule compliance).
    """
    if not fill:
        return f"{int(MISSING):>6d}"
    if pd.isna(value):
        return f"{int(MISSING):>6d}"
    if column in INTEGER_COLS or column in {"PDAT", "ADAT", "MDAT", "HDAT", "DATE"}:
        if column in {"DATE", "PDAT", "ADAT", "MDAT", "HDAT"}:
            # FileA/FileT data frames may carry either a Timestamp or an
            # already-normalized DSSAT YYDDD integer.  Treat the latter as a
            # date code; pandas would otherwise interpret 25075 as nanoseconds
            # after the Unix epoch and silently emit 70001.
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
    """Write a DSSAT FileA or FileT (6-char fixed-width) with strict fill rule.

    Columns not in TMA_FILL / TMT_FILL are written as -99.
    """
    columns = list(df.columns)
    fill_set = TMA_FILL if kind == "A" else TMT_FILL
    # DSSAT treats the identifier header as the same six-character field as
    # the first data field.  The previous ``@TRNO`` (5 chars) shifted every
    # subsequent label one column left relative to the 6-char data records.
    # Keep the leading @ in column 1 and pad the identifier field to 6 chars.
    header_parts = ["@TRNO "]
    for col in columns[1:]:
        header_parts.append(f"{col:>6}")
    header = "".join(header_parts)
    lines = [f"*EXP.DATA ({kind}): {title}", "", *[f"! {c}" for c in comments], "", header]
    for row in df.itertuples(index=False, name=None):
        lines.append("".join(format_field(col, val, col in fill_set) for col, val in zip(columns, row)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------

@dataclass
class SeasonResult:
    season_id: str          # "25SP" | "25FA" | "26SP"
    excode: str             # "XXQL2501" | "XXQL2502" | "XXQL2601"
    output_base: str        # "2025SPR" | "2025FALL" | "2026SPR"
    title: str
    source_notes: list[str]
    # TMT data frames (each row = one observation date per TRNO)
    growth: pd.DataFrame       # TRNO, DATE, LAID, LWAD, SWAD (+ SD columns)
    harvest: pd.DataFrame      # TRNO, DATE, CHFPW, CHPDT (+ SD columns, audit columns)
    # FileA summary
    filea: pd.DataFrame
    # Uncertainty table (schema-compliant; NO PEST weight)
    observation_uncertainty: pd.DataFrame
    # Fruit quality match audit
    fruit_quality_match_audit: pd.DataFrame
    # Treatment exclusion audit (empty for 25FA/26SP)
    treatment_exclusion_audit: pd.DataFrame
    # Source file provenance
    source_files: dict[str, str] = field(default_factory=dict)   # path -> SHA-256
    qa_metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------
# observation_uncertainty builder
# ----------------------------------------------------------------------------

def build_observation_uncertainty(
    season_id: str,
    excode: str,
    filea: pd.DataFrame,
    growth: pd.DataFrame,
    harvest: pd.DataFrame,
    source_workbook: str,
) -> pd.DataFrame:
    """Build schema-compliant observation_uncertainty.csv (NO PEST weight)."""
    rows = []
    # FileA variables: phenology event dates plus LAIX/LWAM/SWAM.  The date
    # fields are represented in PEST as days after PDAT, so their uncertainty
    # is an event-date SD (one day), not a YYDDD numeric SD.
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

    # FileA end-state variables
    for r in filea.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.HDAT) if pd.notna(r.HDAT) else -99
        for var, val_attr, sd_attr, src_attr, n_attr in [
            ("LAIX", "LAIX", "LAIX_sd", "LAIX_sd_source", "LAIX_n_rep"),
            ("LWAM", "LWAM", "LWAM_sd", "LWAM_sd_source", "LWAM_n_rep"),
            ("SWAM", "SWAM", "SWAM_sd", "SWAM_sd_source", "SWAM_n_rep"),
        ]:
            val = getattr(r, val_attr, np.nan)
            sd = getattr(r, sd_attr, np.nan)
            src = getattr(r, src_attr, "no_data")
            n_rep = getattr(r, n_attr, 0)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
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
    # FileT growth variables: LAID, LWAD, SWAD, CHTD
    for r in growth.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.DATE)
        for var, val_attr, sd_attr, src_attr, n_attr in [
            ("LAID", "LAID", "LAID_sd", "LAID_sd_source", "LAID_n_rep"),
            ("LWAD", "LWAD", "LWAD_sd", "LWAD_sd_source", "LWAD_n_rep"),
            ("SWAD", "SWAD", "SWAD_sd", "SWAD_sd_source", "SWAD_n_rep"),
            ("CHTD", "CHTD", "CHTD_sd", "CHTD_sd_source", "CHTD_n_rep"),
        ]:
            val = getattr(r, val_attr, np.nan)
            sd = getattr(r, sd_attr, np.nan)
            src = getattr(r, src_attr, "no_data")
            n_rep = getattr(r, n_attr, 0)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                rows.append({
                    "season_id": season_id, "excode": excode,
                    "trno": trno, "date": date_code, "variable": var,
                    "value": float(val), "raw_sd": float(sd),
                    "n_rep": int(n_rep) if pd.notna(n_rep) else 0,
                    "sd_method": src,
                    "source_workbook": source_workbook,
                    "source_sheet": "Sheet1",
                    "source_row_rule": f"per_trno_date_mean_replicates_{var.lower()}",
                    "quality_flag": "ok",
                })
    # FileT harvest variables: CHFPW, HPODW and CHPDT
    for r in harvest.itertuples(index=False):
        trno = int(r.TRNO)
        date_code = yrdoy(r.DATE)
        for var, val_attr, sd_attr, src_attr, n_attr in [
            ("CHFPW", "CHFPW", "chfpw_sd", "chfpw_sd_source", "fresh_n_rep"),
            ("CHPDT", "CHPDT", "chpdt_sd", "chpdt_sd_source", "fresh_n_rep"),
            ("HPODW", "HPODW", "dry_sd", "dry_sd_source", "fresh_n_rep"),
        ]:
            val = getattr(r, val_attr, np.nan)
            sd = getattr(r, sd_attr, np.nan)
            src = getattr(r, src_attr, "no_data")
            n_rep = getattr(r, n_attr, 1)
            if pd.notna(val) and pd.notna(sd) and sd > 0:
                rows.append({
                    "season_id": season_id, "excode": excode,
                    "trno": trno, "date": date_code, "variable": var,
                    "value": float(val), "raw_sd": float(sd),
                    "n_rep": int(n_rep) if pd.notna(n_rep) else 1,
                    "sd_method": src,
                    "source_workbook": source_workbook,
                    "source_sheet": "Sheet1",
                    "source_row_rule": f"cumulative_variance_propagation_{var.lower()}",
                    "quality_flag": "ok",
                })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 2025 春季
# ----------------------------------------------------------------------------

def load_2025_spring(root: Path) -> SeasonResult:
    folder = root / "2025春"
    source_files = {}

    # --- Yield data (加权小区产量 already pre-calculated) ---
    y_path = folder / "2025春产量数据集.xlsx"
    source_files[str(y_path)] = sha256_file(y_path)
    y = pd.read_excel(y_path, sheet_name="Sheet1")
    y["小区号"] = pd.to_numeric(y["小区号"], errors="coerce")
    y = y[y["小区号"].notna() & (y["小区号"] > 0)].copy()
    y["TRNO"] = y["小区号"].astype(int)
    y["日期"] = pd.to_datetime(y["日期"], errors="coerce").dt.normalize()
    # FileT stores the original observation date from the workbook.
    # The FileX harvest management table is the sole authority for harvest
    # event dates; the runner must not re-shift them. DSSAT's FreshWt.OUT
    # is matched to FileT dates via the d±1 bounded-nearest window.
    require_columns(y, ["TRNO", "日期", "行位置", "产量", "加权小区产量", "水处理", "氮处理"], "2025春产量")
    # Apply 25SP TN exclusion
    y = y[y["TRNO"].isin(SPRING25_INCLUDED_TN)].copy()

    yield_summary = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        row_yields = grp["产量"].dropna().values
        direct_mean = float(np.mean(row_yields)) if len(row_yields) else float(grp["加权小区产量"].iloc[0])
        sd, src, n = hybrid_sd(row_yields)
        yield_summary.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": direct_mean,
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_summary).sort_values(["TRNO", "DATE"]).reset_index(drop=True)
    # Corrected FileX management is authoritative for which harvest events
    # are real observations.  The source workbook contains a final estimated
    # harvest after the corrected schedule; exclude all yield records after
    # the last FileX harvest date so FileA/FileT/TMT/TMA cannot reintroduce it.
    filex_path = PROJECT_ROOT / "data/user/ref/XXQL2501.TMX"
    harvest_dates = filex_observed_harvest_dates(filex_path)
    if not harvest_dates:
        raise ValueError(f"No harvest dates found in corrected FileX: {filex_path}")
    harvest_cutoff = max(harvest_dates)
    yield_df["_DATE_CODE"] = yield_df["DATE"].map(yrdoy)
    excluded = yield_df[yield_df["_DATE_CODE"] > harvest_cutoff]
    if not excluded.empty:
        print(
            f"  25SP: excluded {len(excluded)} post-FileX estimated harvest records "
            f"after {harvest_cutoff}: {sorted(excluded['_DATE_CODE'].unique().tolist())}"
        )
    yield_df = yield_df[yield_df["_DATE_CODE"] <= harvest_cutoff].drop(columns=["_DATE_CODE"])

    # --- Growth workbook for LAID, SWAD, LWAD ---
    g_path = folder / "2025春作物生长指标集.xlsx"
    source_files[str(g_path)] = sha256_file(g_path)
    g = pd.read_excel(g_path, sheet_name="Sheet1")
    g = g.rename(columns={c: str(c).strip() for c in g.columns})
    require_columns(g, ["日期", "小区号", "重复", "株高", "茎干重", "叶干重", "LAI", "水处理", "氮处理"], "2025春生长")
    g["日期"] = pd.to_datetime(g["日期"], errors="coerce").dt.normalize()
    g["TRNO"] = pd.to_numeric(g["小区号"], errors="coerce").astype("Int64")
    g = g.dropna(subset=["TRNO", "日期"]).copy()
    g["TRNO"] = g["TRNO"].astype(int)
    g = g[g["TRNO"].isin(SPRING25_INCLUDED_TN)].copy()

    # --- Fruit quality (moisture -> DMFR) from 2025春品质集.csv ---
    q_path = folder / "2025春品质集.csv"
    source_files[str(q_path)] = sha256_file(q_path)
    q_lines = q_path.read_text(encoding="utf-8").splitlines()
    q_reader = csv.reader(q_lines)
    q_header = next(q_reader)
    q_valid_cols = [c.strip() for c in q_header if c.strip()]
    q_rows = []
    for r in q_reader:
        if not r or not any(x.strip() for x in r): continue
        q_rows.append({q_valid_cols[k]: r[k].strip() for k in range(len(q_valid_cols)) if k < len(r)})
    fruit = pd.DataFrame(q_rows)
    fruit["小区号"] = pd.to_numeric(fruit["小区号"], errors="coerce").astype(int)
    fruit["重复"] = pd.to_numeric(fruit["重复"], errors="coerce")
    fruit["果含水率"] = pd.to_numeric(fruit["果含水率"], errors="coerce")
    fruit["日期"] = pd.to_datetime(fruit["日期"]).dt.normalize()
    fruit["TRNO"] = fruit["小区号"]
    fruit = fruit[fruit["TRNO"].isin(SPRING25_INCLUDED_TN) & fruit["果含水率"].notna()].copy()
    if fruit["果含水率"].max() > 1.5:
        raise ValueError("2025春品质集 果含水率 单位异常（应 0-1，实测 >1.5）")
    fruit["DMFR"] = 1.0 - fruit["果含水率"]
    dm_by_plot = (fruit.groupby(["TRNO", "日期"], as_index=False)
                  .agg(DMFR=("DMFR", "mean"), N_REP=("重复", "nunique"))
                  .rename(columns={"日期": "GROWTH_DATE"}))
    dm_sd_rows = []
    for (trno, date), grp in fruit.groupby(["TRNO", "日期"]):
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_sd_rows.append({"TRNO": int(trno), "GROWTH_DATE": date, "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_sd = pd.DataFrame(dm_sd_rows)
    dm_by_plot = dm_by_plot.merge(dm_sd, on=["TRNO", "GROWTH_DATE"], how="left")

    # --- Match harvest dates to nearest DMFR (no max interval) ---
    events = yield_df[["TRNO", "DATE", "HARVEST_FRESH", "fresh_sd", "fresh_sd_source", "fresh_n_rep"]].rename(
        columns={"DATE": "HARVEST_DATE"})
    matched = nearest_by_plot(events, dm_by_plot, "HARVEST_DATE", "GROWTH_DATE")
    matched["HARVEST_DRY"] = matched["HARVEST_FRESH"] * matched["DMFR"]
    # Error propagation: var(dry) = DMFR^2 * var(fresh) + fresh^2 * var(DMFR)
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
    matched["match_status"] = "nearest_unbounded"

    # harvest (TMT rows: cumulative fresh/dry plus incremental dry harvest)
    harvest = matched[["TRNO", "HARVEST_DATE", "CHFPW", "CHPDT",
                       "fresh_sd", "fresh_sd_source", "fresh_n_rep", "dry_sd", "dry_sd_source",
                       "chfpw_sd", "chfpw_sd_source",
                       "chpdt_sd", "chpdt_sd_source",
                       "DMFR", "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep",
                       "GROWTH_DATE", "MATCH_DAYS", "match_status",
                       "HFPOW", "HPODW", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE", "GROWTH_DATE": "QUALITY_DATE"})

    # --- Growth data (LAID, SWAD, LWAD) ---
    growth_raw = g[g["LAI"].notna() | g["茎干重"].notna() | g["叶干重"].notna()].copy()
    growth_rows = []
    for (trno, date), grp in growth_raw.groupby(["TRNO", "日期"]):
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

    # --- Build FileA (phenology plus end-state diagnostic fields) ---
    pdat_code, adat_code, podd_code = phenology_filea_values("25SP", "XXQL2501")
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
        filea_rows.append({
            "TRNO": int(trno), "PDAT": pdat_code, "ADAT": adat_code, "MDAT": podd_code,
            "HDAT": final["DATE"], "HWAM": np.nan, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "CNAM": np.nan,
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth",
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth",
        })
    filea = pd.DataFrame(filea_rows)

    # --- observation_uncertainty ---
    observation_uncertainty = build_observation_uncertainty(
        "25SP", "XXQL2501", filea, growth, harvest,
        source_workbook="2025春产量数据集.xlsx;2025春作物生长指标集.xlsx")

    # --- fruit_quality_match_audit ---
    audit = matched[["TRNO", "HARVEST_DATE", "GROWTH_DATE", "MATCH_DAYS",
                     "HARVEST_FRESH", "fresh_sd",
                     "DMFR", "DMFR_sd",
                     "HARVEST_DRY", "dry_sd",
                     "CHPDT", "chpdt_sd", "match_status"]].copy()
    audit = audit.rename(columns={
        "HARVEST_DATE": "harvest_date", "GROWTH_DATE": "quality_date", "MATCH_DAYS": "match_days",
        "HARVEST_FRESH": "fresh_yield", "fresh_sd": "fresh_sd",
        "DMFR": "dmfr", "DMFR_sd": "dmfr_sd",
        "HARVEST_DRY": "dry_increment", "dry_sd": "dry_increment_sd",
        "CHPDT": "chpdt", "chpdt_sd": "chpdt_sd",
    })
    fruit_quality_match_audit = audit

    # --- treatment_exclusion_audit (25SP only) ---
    treatment_exclusion_audit = pd.DataFrame([
        {"season_id": "25SP", "trno": tn, "reason": SPRING25_EXCLUSION_REASON}
        for tn in SPRING25_EXCLUDED_TN
    ])
    estimated_harvest_dates = sorted(set(excluded["_DATE_CODE"].astype(int).tolist())) if not excluded.empty else []

    return SeasonResult(
        season_id="25SP", excode="XXQL2501",
        output_base="2025SPR",
        title="2025 SPRING EGGPLANT; TRNO=PLOT NUMBER (TN 1,6,7,8 excluded)",
        source_notes=[
            "Fresh yield uses direct arithmetic mean of row replicates (unweighted).",
            "Fruit DM fraction = 1 - measured fruit moisture fraction (2025春品质集.csv).",
            "Each harvest uses the nearest plot-level moisture measurement date (no max interval).",
            "SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).",
            "Cumulative yield SD propagates incremental variances.",
            "FileA carries PDAT/ADAT/MDAT(PODD proxy) plus end-state diagnostics; FileT carries process, CHPDT and HPODW.",
            "TN 1,6,7,8 excluded per FileA/FileT uncertainty adaptation plan v1 (2026-07-26) section 6.1.",
            f"Estimated post-FileX harvest records excluded from observations: {estimated_harvest_dates}; FileX cutoff={harvest_cutoff}.",
        ],
        growth=growth, harvest=harvest, filea=filea,
        observation_uncertainty=observation_uncertainty,
        fruit_quality_match_audit=fruit_quality_match_audit,
        treatment_exclusion_audit=treatment_exclusion_audit,
        source_files=source_files,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "total_observations": int(len(observation_uncertainty)),
            "excluded_tn": SPRING25_EXCLUDED_TN,
            "density": DENSITY,
        },
    )


# ----------------------------------------------------------------------------
# 2025 秋季
# ----------------------------------------------------------------------------

def load_2025_fall(root: Path, dm_method: str = "mean", min_fruit_dry_weight: float = 10.0) -> SeasonResult:
    folder = root / "2025秋"
    source_files = {}

    y_path = folder / "2025秋季产量集.xlsx"
    source_files[str(y_path)] = sha256_file(y_path)
    y = pd.read_excel(y_path, sheet_name="2025秋季产量集")
    y["日期"] = parse_yyyymmdd(y["日期"])
    y["TRNO"] = pd.to_numeric(y["小区号"], errors="coerce").astype("Int64")
    y = y.dropna(subset=["TRNO", "日期"]).copy()
    y["TRNO"] = y["TRNO"].astype(int)
    # FileT DATE = yield-data-record date + 1 day = FileX harvest date + 1.
    # 25FA yield workbook uses harvest-day dates (e.g., 20251121 = FileX 25325).
    # DSSAT writes FreshWt.OUT CHPDT increment on day N+1 after the FileX event,
    # so FileT DATE must be shifted to N+1 (25326, 25346, 26006) to align with
    # the FreshWt event day. (25SP and 26SP workbooks already use N+1 dates,
    # so the shift is applied uniformly across all three seasons.)
    y["日期"] = y["日期"] + pd.Timedelta(days=1)
    require_columns(y, ["TRNO", "日期", "重复", "行产量", "小区产量", "水处理", "氮处理"], "2025秋产量")

    yield_rows = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        vals = grp["小区产量"].dropna().values
        sd_vals = grp["行产量"].dropna().values
        sd, src, n = hybrid_sd(sd_vals)
        yield_rows.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": float(np.mean(vals)),
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    g_path = folder / "2025年秋季茄子生长指标集.xlsx"
    source_files[str(g_path)] = sha256_file(g_path)
    g = pd.read_excel(g_path, sheet_name="Sheet1")
    g = g.rename(columns={c: str(c).strip() for c in g.columns})
    require_columns(g, ["日期", "小区", "行号", "株高", "茎干重", "叶干重", "果干重", "果含水率", "LAI", "水处理", "氮处理"], "2025秋生长")
    # 25FA 生长指标集的"日期"列是 Excel 序列号（45932=2025-10-02, 45999=2025-12-08,
    # 46032=2026-01-10），不是 yyyy-mm-dd 字符串或整数。直接 pd.to_datetime 会把
    # 45932 当成"45932 年"导致全部 NaT，进而让 3 个生长测定日被压缩为单一日期，
    # 丢失 2/3 的过程观测。用 Excel serial 解析：
    raw_dates = pd.to_numeric(g["日期"], errors="coerce")
    if raw_dates.between(40000, 60000).all():  # plausible Excel serial range
        g["日期"] = pd.to_datetime(raw_dates, unit="D", origin="1899-12-30").dt.normalize()
    else:
        g["日期"] = pd.to_datetime(g["日期"], errors="coerce").dt.normalize()
    g["TRNO"] = pd.to_numeric(g["小区"], errors="coerce").astype("Int64")
    g = g.dropna(subset=["TRNO", "日期"]).copy()
    g["TRNO"] = g["TRNO"].astype(int)

    # DMFR from 果含水率 (DMFR = 1 - moisture, units 0-1)
    candidates = g[g["果含水率"].notna()].copy()
    if candidates["果含水率"].max() > 1.5:
        raise ValueError("2025秋 果含水率 单位异常")
    candidates["DMFR"] = 1.0 - candidates["果含水率"]
    # Outlier filtering: manual + low-weight + date-specific IQR
    manual_mask = (
        ((candidates["日期"] == pd.Timestamp("2025-12-08")) & (candidates["TRNO"] == 2) & (candidates["行号"] == 1))
        | ((candidates["日期"] == pd.Timestamp("2026-01-10")) & (candidates["TRNO"] == 11) & (candidates["行号"] == 1))
    )
    low_weight_mask = ~manual_mask & (candidates["果干重"] < min_fruit_dry_weight)
    reliable_mask = ~manual_mask & ~low_weight_mask
    iqr_mask = pd.Series(False, index=candidates.index)
    for date, dg in candidates.loc[reliable_mask].groupby("日期"):
        q1, q3 = dg["DMFR"].quantile([0.25, 0.75])
        spread = q3 - q1
        iqr_mask.loc[dg.index] = ~dg["DMFR"].between(q1 - 1.5 * spread, q3 + 1.5 * spread)
    kept_mask = reliable_mask & ~iqr_mask
    kept = candidates.loc[kept_mask].copy()

    dm_rows = []
    for (trno, date), grp in kept.groupby(["TRNO", "日期"]):
        if dm_method == "mean":
            dmfr = float(grp["DMFR"].mean())
        elif dm_method == "median":
            dmfr = float(grp["DMFR"].median())
        else:
            dmfr = float(grp["果干重"].sum() / grp["果鲜重"].sum())
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_rows.append({"TRNO": int(trno), "GROWTH_DATE": date, "DMFR": dmfr,
                        "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_by_plot = pd.DataFrame(dm_rows)

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
                       "chfpw_sd", "chfpw_sd_source",
                       "chpdt_sd", "chpdt_sd_source",
                       "DMFR", "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep",
                       "GROWTH_DATE", "MATCH_DAYS", "match_status",
                       "HFPOW", "HPODW", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE", "GROWTH_DATE": "QUALITY_DATE"})

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

    pdat_code, adat_code, podd_code = phenology_filea_values("25FA", "XXQL2502")
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
        filea_rows.append({
            "TRNO": int(trno), "PDAT": pdat_code, "ADAT": adat_code, "MDAT": podd_code,
            "HDAT": final["DATE"], "HWAM": np.nan, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "CNAM": np.nan,
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth",
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth",
        })
    filea = pd.DataFrame(filea_rows)

    observation_uncertainty = build_observation_uncertainty(
        "25FA", "XXQL2502", filea, growth, harvest,
        source_workbook="2025秋季产量集.xlsx;2025年秋季茄子生长指标集.xlsx")

    audit = matched[["TRNO", "HARVEST_DATE", "GROWTH_DATE", "MATCH_DAYS",
                     "HARVEST_FRESH", "fresh_sd",
                     "DMFR", "DMFR_sd",
                     "HARVEST_DRY", "dry_sd",
                     "CHPDT", "chpdt_sd", "match_status"]].copy()
    audit = audit.rename(columns={
        "HARVEST_DATE": "harvest_date", "GROWTH_DATE": "quality_date", "MATCH_DAYS": "match_days",
        "HARVEST_FRESH": "fresh_yield", "fresh_sd": "fresh_sd",
        "DMFR": "dmfr", "DMFR_sd": "dmfr_sd",
        "HARVEST_DRY": "dry_increment", "dry_sd": "dry_increment_sd",
        "CHPDT": "chpdt", "chpdt_sd": "chpdt_sd",
    })

    return SeasonResult(
        season_id="25FA", excode="XXQL2502",
        output_base="2025FALL",
        title="2025 FALL EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield = mean of 小区产量; SD = independent replicate 行产量.",
            "Fruit DM fraction = 1 - measured fruit moisture fraction (生长指标集.果含水率).",
            "DMFR filtering: manual outliers + low-weight (<10g) + date-specific Tukey 1.5*IQR.",
            "Each harvest uses the nearest plot-level moisture measurement date (no max interval).",
            "Strict FileA/FileT fill rule per docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md.",
        ],
        growth=growth, harvest=harvest, filea=filea,
        observation_uncertainty=observation_uncertainty,
        fruit_quality_match_audit=audit,
        treatment_exclusion_audit=pd.DataFrame(),
        source_files=source_files,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "total_observations": int(len(observation_uncertainty)),
            "density": DENSITY,
        },
    )


# ----------------------------------------------------------------------------
# 2026 春季
# ----------------------------------------------------------------------------

def load_2026_spring(root: Path) -> SeasonResult:
    folder = root / "2026春"
    source_files = {}

    y_path = folder / "2026春产量集.xlsx"
    source_files[str(y_path)] = sha256_file(y_path)
    y = pd.read_excel(y_path, sheet_name="Sheet1")
    y["日期"] = parse_yyyymmdd(y["日期"])
    y["TRNO"] = pd.to_numeric(y["小区号"], errors="coerce").astype("Int64")
    y = y.dropna(subset=["TRNO", "日期"]).copy()
    y["TRNO"] = y["TRNO"].astype(int)
    # FileT stores the original observation date from the workbook.
    # No shift — FileX is the sole authority for harvest event dates.
    require_columns(y, ["TRNO", "日期", "重复", "产量", "小区产量", "水处理", "氮处理"], "2026春产量")

    yield_rows = []
    for (trno, date), grp in y.groupby(["TRNO", "日期"]):
        vals = grp["小区产量"].dropna().values
        sd_vals = grp["产量"].dropna().values
        sd, src, n = hybrid_sd(sd_vals)
        yield_rows.append({
            "TRNO": int(trno), "DATE": date,
            "HARVEST_FRESH": float(np.mean(vals)),
            "fresh_sd": sd, "fresh_sd_source": src, "fresh_n_rep": n,
        })
    yield_df = pd.DataFrame(yield_rows).sort_values(["TRNO", "DATE"]).reset_index(drop=True)

    # --- Growth data: 26SP has 4 sheets with INCONSISTENT columns ---
    # Sheets and their plot/date columns:
    #   '0502': date col='取样日期',  plot col='小区',  date stored in column
    #   '0629': NO date col (sheet name='MMDD'), plot col='处理 (Treatment)'
    #   '0717': date col='日期',      plot col='处理', date stored in column
    #   '0602': NO date col (sheet name='MMDD'), plot col='处理'
    # Fruit moisture ('半果含水率') is NOT in growth data; loaded below from quality workbook.
    g_path = folder / "2026春生长指标集.xlsx"
    source_files[str(g_path)] = sha256_file(g_path)
    SHEET_YEAR = 2026
    PLOT_ALIASES = ("小区", "处理", "处理 (Treatment)")
    DATE_ALIASES = ("取样日期", "日期")
    HEIGHT_ALIASES = ("株高", "株高 (Plant Height / cm)", "株高 (cm)")
    xls_g = pd.ExcelFile(g_path)
    g_frames = []
    for sheet in xls_g.sheet_names:
        if str(sheet).strip() == "QA说明":
            continue
        df_s = pd.read_excel(xls_g, sheet_name=sheet)
        df_s = df_s.rename(columns={c: str(c).strip() for c in df_s.columns})
        height_col = next((c for c in HEIGHT_ALIASES if c in df_s.columns), None)
        if height_col is None:
            raise ValueError(f"2026春生长/{sheet}: 未找到株高列")
        df_s["CHTD_RAW"] = pd.to_numeric(df_s[height_col], errors="coerce")
        # Resolve plot column -> 'TRNO_SRC'
        plot_col = next((c for c in PLOT_ALIASES if c in df_s.columns), None)
        if plot_col is None:
            raise ValueError(f"2026春生长/{sheet}: 找不到小区/处理列，已知列: {list(df_s.columns)}")
        df_s["TRNO_SRC"] = pd.to_numeric(df_s[plot_col], errors="coerce")
        # Resolve date column -> fallback to sheet name MMDD -> YYYY-MM-DD
        date_col = next((c for c in DATE_ALIASES if c in df_s.columns), None)
        if date_col is not None:
            df_s["日期"] = parse_yyyymmdd(df_s[date_col])
        else:
            try:
                mmdd = int(sheet)
                month, day = divmod(mmdd, 100)
                if 1 <= month <= 12 and 1 <= day <= 31:
                    df_s["日期"] = pd.Timestamp(year=SHEET_YEAR, month=month, day=day)
                else:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError(f"2026春生长/{sheet}: 无日期列且 sheet 名 '{sheet}' 不是 MMDD 格式")
        df_s["__source_sheet"] = sheet
        g_frames.append(df_s)
    g = pd.concat(g_frames, ignore_index=True, sort=False)
    # Strip whitespace from remaining columns (already done per-sheet, but be safe)
    g = g.rename(columns={c: str(c).strip() for c in g.columns})
    require_columns(g, ["TRNO_SRC", "日期", "CHTD_RAW", "茎干重", "叶干重", "LAI", "水处理", "氮处理"], "2026春生长 (after merge)")
    g["TRNO"] = g["TRNO_SRC"].astype("Int64")
    g = g.dropna(subset=["TRNO", "日期"]).copy()
    g["TRNO"] = g["TRNO"].astype(int)

    # --- Fruit moisture -> DMFR (loaded from quality workbook, NOT growth) ---
    q_path = folder / "2026春品质指标集.xlsx"
    source_files[str(q_path)] = sha256_file(q_path)
    q = pd.read_excel(q_path, sheet_name="Sheet1")
    q = q.rename(columns={c: str(c).strip() for c in q.columns})
    require_columns(q, ["日期", "小区号", "半果含水率", "重复", "水处理", "氮处理"], "2026春品质 (for 半果含水率)")
    q["日期"] = parse_yyyymmdd(q["日期"])
    q["TRNO"] = pd.to_numeric(q["小区号"], errors="coerce").astype("Int64")
    q = q.dropna(subset=["TRNO", "日期", "半果含水率"]).copy()
    q["TRNO"] = q["TRNO"].astype(int)
    # Verify moisture is fraction [0,1] not percent [0,100]
    if q["半果含水率"].max() > 1.5:
        raise ValueError("2026春 半果含水率 单位异常（应 0-1，实测 >1.5）")
    q["DMFR"] = 1.0 - q["半果含水率"]
    dm_by_plot = (q.groupby(["TRNO", "日期"], as_index=False)
                  .agg(DMFR=("DMFR", "mean"), N_REP=("重复", "nunique"))
                  .rename(columns={"日期": "GROWTH_DATE"}))
    dm_sd_rows = []
    for (trno, date), grp in q.groupby(["TRNO", "日期"]):
        sd, src, n = hybrid_sd(grp["DMFR"].values)
        dm_sd_rows.append({"TRNO": int(trno), "GROWTH_DATE": date, "DMFR_sd": sd, "DMFR_sd_source": src, "DMFR_n_rep": n})
    dm_sd = pd.DataFrame(dm_sd_rows)
    dm_by_plot = dm_by_plot.merge(dm_sd, on=["TRNO", "GROWTH_DATE"], how="left")

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
                       "chfpw_sd", "chfpw_sd_source",
                       "chpdt_sd", "chpdt_sd_source",
                       "DMFR", "DMFR_sd", "DMFR_sd_source", "DMFR_n_rep",
                       "GROWTH_DATE", "MATCH_DAYS", "match_status",
                       "HFPOW", "HPODW", "PDMCD"]].rename(
        columns={"HARVEST_DATE": "DATE", "GROWTH_DATE": "QUALITY_DATE"})

    growth_rows = []
    growth_raw = g[g["LAI"].notna() | g["茎干重"].notna() | g["叶干重"].notna() | g["CHTD_RAW"].notna()].copy()
    for (trno, date), grp in growth_raw.groupby(["TRNO", "日期"]):
        lai_vals = grp["LAI"].dropna().values
        stem_vals = grp["茎干重"].dropna().values
        leaf_vals = grp["叶干重"].dropna().values
        height_vals = grp["CHTD_RAW"].dropna().values
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

    pdat_code, adat_code, podd_code = phenology_filea_values("26SP", "XXQL2601")
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
        filea_rows.append({
            "TRNO": int(trno), "PDAT": pdat_code, "ADAT": adat_code, "MDAT": podd_code,
            "HDAT": final["DATE"], "HWAM": np.nan, "LWAM": lwam, "SWAM": swam,
            "LAIX": laix, "HIAM": np.nan, "CNAM": np.nan,
            "LAIX_sd": laix_sd, "LAIX_sd_source": laix_src, "LAIX_n_rep": laix_n,
            "LWAM_sd": lwam_sd, "LWAM_sd_source": "last_obs_growth",
            "SWAM_sd": swam_sd, "SWAM_sd_source": "last_obs_growth",
        })
    filea = pd.DataFrame(filea_rows)

    observation_uncertainty = build_observation_uncertainty(
        "26SP", "XXQL2601", filea, growth, harvest,
        source_workbook="2026春产量集.xlsx;2026春生长指标集.xlsx;2026春品质指标集.xlsx")

    audit = matched[["TRNO", "HARVEST_DATE", "GROWTH_DATE", "MATCH_DAYS",
                     "HARVEST_FRESH", "fresh_sd",
                     "DMFR", "DMFR_sd",
                     "HARVEST_DRY", "dry_sd",
                     "CHPDT", "chpdt_sd", "match_status"]].copy()
    audit = audit.rename(columns={
        "HARVEST_DATE": "harvest_date", "GROWTH_DATE": "quality_date", "MATCH_DAYS": "match_days",
        "HARVEST_FRESH": "fresh_yield", "fresh_sd": "fresh_sd",
        "DMFR": "dmfr", "DMFR_sd": "dmfr_sd",
        "HARVEST_DRY": "dry_increment", "dry_sd": "dry_increment_sd",
        "CHPDT": "chpdt", "chpdt_sd": "chpdt_sd",
    })

    return SeasonResult(
        season_id="26SP", excode="XXQL2601",
        output_base="2026SPR",
        title="2026 SPRING EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield = mean of 小区产量; SD = independent replicate 产量.",
            "Growth data merged from 4 sheets (0502/0629/0717/0602); sheet name used as fallback date for 0629/0602.",
            "Fruit DM fraction = 1 - measured fruit moisture fraction (2026春品质指标集.半果含水率).",
            "Each harvest uses the nearest plot-level moisture measurement date (no max interval).",
            "Strict FileA/FileT fill rule per docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md.",
        ],
        growth=growth, harvest=harvest, filea=filea,
        observation_uncertainty=observation_uncertainty,
        fruit_quality_match_audit=audit,
        treatment_exclusion_audit=pd.DataFrame(),
        source_files=source_files,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "total_observations": int(len(observation_uncertainty)),
            "density": DENSITY,
        },
    )


# ----------------------------------------------------------------------------
# Output writer
# ----------------------------------------------------------------------------

def write_season_outputs(result: SeasonResult, out_dir: Path, generator_sha: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # DSSAT FileT/PlantGro defines CHTD in metres, while the source workbooks
    # record plant height in centimetres.  Keep the source-side calculations
    # in their native unit, then convert both the observation mean and its
    # replicate SD together at the adapter boundary.  The previous v2 bundle
    # wrote centimetres into FileT, so PEST compared ~100--180 against DSSAT
    # simulations of ~1--4 m.
    growth_out = result.growth.copy()
    if "CHTD" in growth_out.columns:
        growth_out["CHTD"] = pd.to_numeric(
            growth_out["CHTD"], errors="coerce"
        ) / 100.0
    if "CHTD_sd" in growth_out.columns:
        growth_out["CHTD_sd"] = pd.to_numeric(
            growth_out["CHTD_sd"], errors="coerce"
        ) / 100.0

    uncertainty_out = result.observation_uncertainty.copy()
    chtd_mask = uncertainty_out["variable"].astype(str).str.upper().eq("CHTD")
    for column in ("value", "raw_sd"):
        uncertainty_out.loc[chtd_mask, column] = (
            pd.to_numeric(uncertainty_out.loc[chtd_mask, column], errors="coerce")
            / 100.0
        )
    uncertainty_out.loc[chtd_mask, "source_row_rule"] = (
        uncertainty_out.loc[chtd_mask, "source_row_rule"].astype(str)
        + "; converted_cm_to_m_for_DSSAT"
    )

    # FileA (strict fill)
    filea_out = result.filea[TMA_COLUMNS].copy()
    write_dssat_file(out_dir / f"{result.excode}.TMA", "A", result.title,
                     result.source_notes, filea_out)

    # FileT (strict fill): merge growth + harvest rows by (TRNO, DATE).
    # Only process states from growth; only direct cumulative harvest states
    # from harvest.  CHTD is written in DSSAT's metre unit; all deprecated
    # columns remain -99.
    growth_tmt = growth_out[["TRNO", "DATE", "LAID", "LWAD", "SWAD", "CHTD"]].copy()
    harvest_tmt = result.harvest[["TRNO", "DATE", "CHFPW", "HPODW", "CHPDT"]].copy()
    # Outer union by (TRNO, DATE) — some dates have growth only, some have harvest only
    tmt = growth_tmt.merge(harvest_tmt, on=["TRNO", "DATE"], how="outer").sort_values(["TRNO", "DATE"])
    # Fill TMT_COLUMNS order
    for col in TMT_COLUMNS:
        if col not in tmt.columns:
            tmt[col] = np.nan
    tmt = tmt[TMT_COLUMNS].reset_index(drop=True)
    write_dssat_file(out_dir / f"{result.excode}.TMT", "T", result.title,
                     result.source_notes, tmt)

    # observation_uncertainty.csv
    uncertainty_out.to_csv(out_dir / "observation_uncertainty.csv", index=False)

    # fruit_quality_match_audit.csv
    result.fruit_quality_match_audit.to_csv(out_dir / "fruit_quality_match_audit.csv", index=False)

    # treatment_exclusion_audit.csv (only 25SP; empty file for other seasons is acceptable)
    if not result.treatment_exclusion_audit.empty:
        result.treatment_exclusion_audit.to_csv(out_dir / "treatment_exclusion_audit.csv", index=False)

    # Human-readable copies
    result.filea.to_csv(out_dir / "FileA_values.csv", index=False)
    tmt_full = tmt.copy()
    # Annotate FileT_values with SD columns from growth/harvest for human reading
    tmt_full.to_csv(out_dir / "FileT_values.csv", index=False)

    # generator_log.json (provenance)
    log = {
        "season_id": result.season_id,
        "excode": result.excode,
        "generator": "tools/experiments/build_trial_observations_v2_20260726.py",
        "generator_sha256": generator_sha,
        "spec_compliance": "docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md",
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


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build DSSAT FileA/FileT + uncertainty tables (v2).")
    parser.add_argument("--root", type=Path, default=Path(r"D:\Tomato_Cal\data\user\ref\DSSAT文件"),
                        help="Root directory containing 2025春/2025秋/2026春 subfolders")
    parser.add_argument("--seasons", nargs="+", default=["25SP", "25FA", "26SP"],
                        choices=["25SP", "25FA", "26SP"], help="Seasons to build")
    args = parser.parse_args()

    # Compute generator SHA-256 for provenance
    generator_path = Path(__file__).resolve()
    generator_sha = sha256_file(generator_path)

    loaders = {"25SP": load_2025_spring, "25FA": load_2025_fall, "26SP": load_2026_spring}
    folder_map = {"25SP": "2025春", "25FA": "2025秋", "26SP": "2026春"}

    for season in args.seasons:
        print(f"\n=== Building {season} ===")
        result = loaders[season](args.root)
        out_dir = args.root / folder_map[season] / "DSSAT输出_v2"
        write_season_outputs(result, out_dir, generator_sha)
        print(f"  output_dir: {out_dir}")
        print(f"  plots: {result.qa_metrics.get('plots', 0)}")
        print(f"  growth_dates: {result.qa_metrics.get('growth_dates', 0)}")
        print(f"  harvest_dates: {result.qa_metrics.get('harvest_dates', 0)}")
        print(f"  total_observations: {result.qa_metrics.get('total_observations', 0)}")
        if not result.treatment_exclusion_audit.empty:
            print(f"  excluded_tn: {result.qa_metrics.get('excluded_tn', [])}")
        print(f"  files: {sorted(p.name for p in out_dir.iterdir())}")


if __name__ == "__main__":
    main()
