#!/usr/bin/env python3
"""Generate DSSAT File A/File T for 2025 spring, 2025 fall, and 2026 spring.

Rules used in every season:
* TRNO is the plot number and within-plot plant/row replicates are averaged.
* File T harvest variables are CHFPW (cumulative fresh fruit yield) and CHPDT
  (cumulative dry fruit yield). They are populated only on measured harvest dates.
* Standing-fruit indicators are intentionally omitted because their sampling
  error is too large.  File T therefore retains stem/leaf status variables only.
* HWAD, FWAD, CWAD, FRNAD, CNAD, CWAM, CNAM, and FRNAM are not produced.
* Missing DSSAT values are written as -99 and dates as YYDDD.

The script never edits source workbooks/CSV files. Generated files are written to
each season's ``DSSAT输出`` directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


MISSING = -99.0
T_COLUMNS = [
    "TRNO",
    "DATE",
    "LAID",
    "SWAD",
    "LWAD",
    "CHFPW",
    "CHPDT",
    "SNAD",
    "LNAD",
]
A_COLUMNS = ["TRNO", "HWAH", "HWAHF", "LAIX", "LWAM", "SNAM", "HDAT"]


@dataclass
class SeasonResult:
    key: str
    output_base: str
    title: str
    source_notes: list[str]
    growth: pd.DataFrame
    nitrogen: pd.DataFrame
    harvest: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    qa_metrics: dict[str, object] = field(default_factory=dict)
    dm_filter_audit: pd.DataFrame | None = None


def require_columns(df: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{label} 缺少必需列: {missing}")


def parse_yyyymmdd(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return pd.to_datetime(numeric.astype("Int64").astype(str), format="%Y%m%d", errors="coerce").dt.normalize()


def verify_treatment_mapping(frames: list[tuple[pd.DataFrame, str]], label: str) -> None:
    mappings: list[pd.DataFrame] = []
    for df, plot_col in frames:
        mapping = (
            df[[plot_col, "水处理", "氮处理"]]
            .dropna(subset=[plot_col])
            .drop_duplicates()
            .rename(columns={plot_col: "TRNO"})
            .sort_values("TRNO")
            .reset_index(drop=True)
        )
        if mapping["TRNO"].duplicated().any():
            raise ValueError(f"{label}: 同一小区对应多个水氮处理")
        mappings.append(mapping)
    first = mappings[0]
    for other in mappings[1:]:
        if not first.equals(other):
            raise ValueError(f"{label}: 数据源之间的小区—处理映射不一致")


def nearest_by_plot(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_date: str,
    right_date: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
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


def aggregate_fall_dm_fraction(growth: pd.DataFrame, method: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    fruit = growth[growth["果鲜重"] > 0].copy()
    fruit["DMFR"] = fruit["果干重"] / fruit["果鲜重"]
    grouped = fruit.groupby(["小区", "日期"], as_index=False)
    if method == "mean":
        dm = grouped["DMFR"].mean()
    elif method == "median":
        dm = grouped["DMFR"].median()
    else:
        dm = grouped[["果干重", "果鲜重"]].sum()
        dm["DMFR"] = dm["果干重"] / dm["果鲜重"]
        dm = dm[["小区", "日期", "DMFR"]]
    return dm.rename(columns={"小区": "TRNO", "日期": "GROWTH_DATE"}), fruit


def load_2025_spring(root: Path, density: float) -> SeasonResult:
    path = root / "2025春" / "2025年春茄子DSSAT数据集_累积数据_含完整生物量含氮量和DSSAT格式.csv"
    raw = pd.read_csv(path)
    require_columns(
        raw,
        [
            "日期",
            "小区号",
            "重复",
            "公顷产量",
            "公顷成熟果干重",
            "SWAD",
            "LWAD",
            "LAI",
            "公顷茎含氮量",
            "公顷叶含氮量",
        ],
        "2025春 CSV",
    )
    raw["日期"] = pd.to_datetime(raw["日期"]).dt.normalize()
    if raw.duplicated(["日期", "小区号", "行位置"]).any():
        raise ValueError("2025春: 日期/小区/行位置键重复")

    growth_raw = raw[raw[["SWAD", "LWAD", "LAI"]].notna().any(axis=1)].copy()

    growth = (
        growth_raw.groupby(["小区号", "日期"], as_index=False)
        .agg(
            LAID=("LAI", "mean"),
            SWAD=("SWAD", "mean"),
            LWAD=("LWAD", "mean"),
            SNAD=("公顷茎含氮量", "mean"),
            LNAD=("公顷叶含氮量", "mean"),
            N_REP=("重复", "nunique"),
        )
        .rename(columns={"小区号": "TRNO", "日期": "DATE"})
    )
    nitrogen = growth[["TRNO", "DATE", "SNAD", "LNAD"]].copy()

    harvest_raw = raw.dropna(subset=["公顷产量", "公顷成熟果干重"]).copy()
    harvest = (
        harvest_raw.groupby(["小区号", "日期"], as_index=False)
        .agg(CHFPW=("公顷产量", "mean"), CHPDT=("公顷成熟果干重", "mean"))
        .rename(columns={"小区号": "TRNO", "日期": "DATE"})
        .sort_values(["TRNO", "DATE"])
    )
    diffs = harvest.groupby("TRNO")[["CHFPW", "CHPDT"]].diff()
    if (diffs < -1e-9).any().any() or (diffs == 0).any().any():
        raise ValueError("2025春: 累计鲜/干产量存在不增或下降")

    return SeasonResult(
        key="2025spring",
        output_base="2025SPR",
        title="2025 SPRING EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Spring source already stores cumulative fresh and dry harvested fruit yields.",
            "Standing-fruit biomass and N indicators are omitted because of sampling error.",
        ],
        growth=growth,
        nitrogen=nitrogen,
        harvest=harvest,
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "density": density,
            "source_density_check": "SWAD/LWAD were already supplied in kg/ha",
        },
    )


def load_2025_fall(root: Path, density: float, dm_method: str, min_fruit_dry_weight: float) -> SeasonResult:
    folder = root / "2025秋"
    growth = pd.read_excel(folder / "2025年秋季茄子生长指标集.xlsx", sheet_name="Sheet1", usecols="A:U")
    nutrient = pd.read_excel(folder / "2025年秋季茄子植株样氮磷钾测定.xlsx", sheet_name="Sheet1", usecols="A:I")
    yield_data = pd.read_excel(folder / "2025秋季产量集.xlsx", sheet_name="2025秋季产量集", usecols="A:M")
    require_columns(growth, ["日期", "小区", "行号", "茎干重", "叶干重", "果鲜重", "果干重", "LAI"], "2025秋生长表")
    require_columns(nutrient, ["取样日期", "取样部位", "小区号", "重复", "全氮（mg/g)"], "2025秋养分表")
    require_columns(yield_data, ["日期", "小区号", "重复", "小区棵数", "行果实总重", "小区果实总重", "小区产量"], "2025秋产量表")

    growth["日期"] = pd.to_datetime(growth["日期"]).dt.normalize()
    nutrient["取样日期"] = pd.to_datetime(nutrient["取样日期"]).dt.normalize()
    yield_data["日期"] = parse_yyyymmdd(yield_data["日期"])
    paired_missing = growth["果鲜重"].isna() & growth["果干重"].isna()
    growth.loc[paired_missing, ["果鲜重", "果干重"]] = 0.0
    if (growth["果鲜重"].isna() ^ growth["果干重"].isna()).any():
        raise ValueError("2025秋: 果鲜重与果干重存在非成对缺失")
    verify_treatment_mapping([(growth, "小区"), (nutrient, "小区号"), (yield_data, "小区号")], "2025秋")

    inferred_density = yield_data["小区产量"] * 1000.0 / (yield_data["小区果实总重"] / yield_data["小区棵数"])
    if ((inferred_density - density).abs() / density > 0.001).any():
        raise ValueError("2025秋: 产量表反算种植密度与使用值不一致")
    sum_check = yield_data.groupby(["日期", "小区号"])["行果实总重"].sum() - yield_data.groupby(["日期", "小区号"])["小区果实总重"].first()
    if not np.allclose(sum_check, 0.0, atol=1e-6):
        raise ValueError("2025秋: 行果实总重之和不等于小区总重")

    candidates = growth[(growth["果鲜重"] > 0) & growth["果干重"].notna()].copy()
    candidates["DMFR"] = candidates["果干重"] / candidates["果鲜重"]
    manual_mask = (
        ((candidates["日期"] == pd.Timestamp("2025-12-08")) & (candidates["小区"] == 2) & (candidates["行号"] == 1))
        | ((candidates["日期"] == pd.Timestamp("2026-01-10")) & (candidates["小区"] == 11) & (candidates["行号"] == 1))
    )
    if int(manual_mask.sum()) != 2:
        raise ValueError("2025秋: 未能唯一定位用户指定的 2 条果实干物质率异常记录")
    low_weight_mask = ~manual_mask & (candidates["果干重"] < min_fruit_dry_weight)
    reliable_mask = ~manual_mask & ~low_weight_mask

    iqr_mask = pd.Series(False, index=candidates.index)
    iqr_low = pd.Series(np.nan, index=candidates.index, dtype=float)
    iqr_high = pd.Series(np.nan, index=candidates.index, dtype=float)
    for date, date_group in candidates.loc[reliable_mask].groupby("日期"):
        q1, q3 = date_group["DMFR"].quantile([0.25, 0.75])
        spread = q3 - q1
        lower = q1 - 1.5 * spread
        upper = q3 + 1.5 * spread
        iqr_low.loc[date_group.index] = lower
        iqr_high.loc[date_group.index] = upper
        iqr_mask.loc[date_group.index] = ~date_group["DMFR"].between(lower, upper)
    kept_mask = reliable_mask & ~iqr_mask

    required_dm_dates = [pd.Timestamp("2025-12-08"), pd.Timestamp("2026-01-10")]
    expected_plots = set(range(1, 13))
    for date in required_dm_dates:
        available = set(candidates.loc[kept_mask & (candidates["日期"] == date), "小区"].astype(int))
        if available != expected_plots:
            raise ValueError(f"2025秋: {date.date()} 筛选后小区覆盖不完整，缺少 {sorted(expected_plots - available)}")

    audit = candidates[["日期", "小区", "行号", "果鲜重", "果干重", "DMFR"]].copy()
    audit["IQR_LOW"] = iqr_low
    audit["IQR_HIGH"] = iqr_high
    audit["STATUS"] = "KEPT"
    audit["REASON"] = "kept"
    audit.loc[manual_mask, ["STATUS", "REASON"]] = ["EXCLUDED", "user_specified_outlier"]
    audit.loc[low_weight_mask, ["STATUS", "REASON"]] = ["EXCLUDED", f"fruit_dry_weight_below_{min_fruit_dry_weight:g}_g"]
    audit.loc[iqr_mask, ["STATUS", "REASON"]] = ["EXCLUDED", "date_specific_1.5_IQR_outlier"]
    audit = audit.rename(columns={"日期": "DATE", "小区": "TRNO", "行号": "REP", "果鲜重": "FRUIT_FRESH_G", "果干重": "FRUIT_DRY_G"})
    audit = audit.sort_values(["DATE", "TRNO", "REP"]).reset_index(drop=True)

    filtered_growth = candidates.loc[kept_mask].copy()
    dm, fruit_rows = aggregate_fall_dm_fraction(filtered_growth, dm_method)
    event = (
        yield_data.groupby(["日期", "小区号"], as_index=False)
        .agg(HARVEST_FRESH=("小区产量", "first"))
        .rename(columns={"日期": "HARVEST_DATE", "小区号": "TRNO"})
    )
    matched = nearest_by_plot(event, dm, "HARVEST_DATE", "GROWTH_DATE")
    matched["HARVEST_DRY"] = matched["HARVEST_FRESH"] * matched["DMFR"]
    matched = matched.sort_values(["TRNO", "HARVEST_DATE"])
    matched["CHFPW"] = matched.groupby("TRNO")["HARVEST_FRESH"].cumsum()
    matched["CHPDT"] = matched.groupby("TRNO")["HARVEST_DRY"].cumsum()
    harvest = matched[["TRNO", "HARVEST_DATE", "CHFPW", "CHPDT"]].rename(columns={"HARVEST_DATE": "DATE"})

    factor = density / 1000.0
    growth_summary = (
        growth.groupby(["小区", "日期"], as_index=False)
        .agg(LAID=("LAI", "mean"), STEM_G=("茎干重", "mean"), LEAF_G=("叶干重", "mean"), N_REP=("行号", "nunique"))
        .rename(columns={"小区": "TRNO", "日期": "DATE"})
    )
    growth_summary["SWAD"] = growth_summary["STEM_G"] * factor
    growth_summary["LWAD"] = growth_summary["LEAF_G"] * factor

    nutrient_wide = (
        nutrient.pivot(index=["取样日期", "小区号", "重复"], columns="取样部位", values="全氮（mg/g)")
        .reset_index()
        .rename(columns={"取样日期": "DATE", "小区号": "TRNO", "重复": "REP", "茎": "STEM_N", "叶": "LEAF_N", "果": "FRUIT_N"})
    )
    growth_reps = growth[["日期", "小区", "行号", "茎干重", "叶干重"]].rename(columns={"日期": "GROWTH_DATE", "小区": "TRNO", "行号": "REP"})
    date_match = nearest_by_plot(nutrient_wide[["TRNO", "DATE"]].drop_duplicates(), growth_reps[["TRNO", "GROWTH_DATE"]].drop_duplicates(), "DATE", "GROWTH_DATE")
    detail = nutrient_wide.merge(date_match[["TRNO", "DATE", "GROWTH_DATE", "MATCH_DAYS"]], on=["TRNO", "DATE"], validate="many_to_one")
    detail = detail.merge(growth_reps, on=["TRNO", "REP", "GROWTH_DATE"], validate="one_to_one")
    detail["SNAD"] = detail["茎干重"] * factor * detail["STEM_N"] / 1000.0
    detail["LNAD"] = detail["叶干重"] * factor * detail["LEAF_N"] / 1000.0
    nitrogen_summary = detail.groupby(["TRNO", "DATE"], as_index=False).agg(SNAD=("SNAD", "mean"), LNAD=("LNAD", "mean"), MATCH_DAYS=("MATCH_DAYS", "max"))

    return SeasonResult(
        key="2025fall",
        output_base="2025FALL",
        title="2025 FALL EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield is a per-harvest measurement and is cumulatively summed by plot.",
            f"Dry harvested yield uses the nearest measured plot fruit DM fraction ({dm_method}).",
            "Fruit DM samples below the dry-weight threshold are excluded before aggregation.",
            "Remaining DM fractions are screened within measurement date using Tukey 1.5*IQR fences.",
            "Two user-identified fruit DM outliers are always excluded.",
            "Standing-fruit biomass and N indicators are omitted because of sampling error.",
        ],
        growth=growth_summary,
        nitrogen=nitrogen_summary,
        harvest=harvest,
        warnings=[],
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth_summary["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "density": float(density),
            "inferred_density_min": float(inferred_density.min()),
            "inferred_density_max": float(inferred_density.max()),
            "harvest_dm_match_max_days": int(matched["MATCH_DAYS"].max()),
            "nitrogen_biomass_match_max_days": int(nitrogen_summary["MATCH_DAYS"].max()),
            "minimum_fruit_dry_weight_g": float(min_fruit_dry_weight),
            "candidate_fruit_dm_samples": int(len(candidates)),
            "excluded_user_specified": int(manual_mask.sum()),
            "excluded_low_dry_weight": int(low_weight_mask.sum()),
            "excluded_date_specific_iqr": int(iqr_mask.sum()),
            "retained_fruit_dm_samples": int(kept_mask.sum()),
            "retained_dm_fraction_min": float(fruit_rows["DMFR"].min()),
            "retained_dm_fraction_max": float(fruit_rows["DMFR"].max()),
            "retained_dm_by_date": "; ".join(
                f"{pd.Timestamp(date).date()} n={len(group)}, range={group['DMFR'].min():.2%}-{group['DMFR'].max():.2%}"
                for date, group in candidates.loc[kept_mask].groupby("日期")
            ),
        },
        dm_filter_audit=audit,
    )


def load_2026_spring(root: Path, density: float) -> SeasonResult:
    folder = root / "2026春"
    yield_raw = pd.read_excel(folder / "2026春产量集.xlsx", sheet_name="Sheet1", usecols="A:M")
    yield_raw["TRNO_NUM"] = pd.to_numeric(yield_raw["小区号"], errors="coerce")
    yield_raw = yield_raw[yield_raw["TRNO_NUM"].notna()].copy()
    yield_raw["小区号"] = yield_raw["TRNO_NUM"].astype(int)
    yield_raw["日期"] = parse_yyyymmdd(yield_raw["日期"])
    require_columns(yield_raw, ["小区号", "重复", "小区测产棵数", "小区产量", "小区果实总重"], "2026春产量表")

    inferred_density = yield_raw["小区产量"] * 1000.0 / (yield_raw["小区果实总重"] / yield_raw["小区测产棵数"])
    if ((inferred_density - density).abs() / density > 0.001).any():
        raise ValueError("2026春: 产量表反算种植密度与使用值不一致")

    # Each complete harvest block starts at plot 1 / replicate 1.  Require one
    # distinct date per block so an accidentally duplicated harvest date cannot
    # be silently merged again.
    block_start = (yield_raw["小区号"] == 1) & (yield_raw["重复"] == 1)
    yield_raw["EVENT_ID"] = block_start.cumsum()
    event_counts = yield_raw.groupby("EVENT_ID").agg(PLOTS=("小区号", "nunique"), ROWS=("重复", "size"))
    if not ((event_counts["PLOTS"] == 12) & (event_counts["ROWS"] == 60)).all():
        raise ValueError("2026春: 产量表的完整采收批次结构异常")
    if (yield_raw.groupby(["EVENT_ID", "小区号"])["小区产量"].nunique() != 1).any():
        raise ValueError("2026春: 同一采收批次/小区的小区产量不一致")
    event_dates = yield_raw.groupby("EVENT_ID")["日期"].agg(["nunique", "first"])
    if (event_dates["nunique"] != 1).any() or event_dates["first"].duplicated().any():
        raise ValueError("2026春: 每个采收批次必须对应一个不重复的日期")
    events = (
        yield_raw.groupby(["EVENT_ID", "日期", "小区号"], as_index=False)
        .agg(HARVEST_FRESH=("小区产量", "first"))
        .rename(columns={"日期": "HARVEST_DATE", "小区号": "TRNO"})
    )

    quality_path = folder / "2026春品质指标集.xlsx"
    quality_frames: list[pd.DataFrame] = []
    for sheet in pd.ExcelFile(quality_path).sheet_names:
        quality = pd.read_excel(quality_path, sheet_name=sheet)
        moisture_column = "半果含水率" if "半果含水率" in quality.columns else "含水率"
        require_columns(quality, ["日期", "小区号", "水处理", "氮处理", "重复", moisture_column], f"2026春品质表 {sheet}")
        quality["TRNO"] = pd.to_numeric(quality["小区号"], errors="raise").astype(int)
        quality["QUALITY_DATE"] = parse_yyyymmdd(quality["日期"])
        quality["DMFR"] = 1.0 - pd.to_numeric(quality[moisture_column], errors="raise")
        quality["SOURCE_SHEET"] = sheet
        quality_frames.append(quality[["TRNO", "QUALITY_DATE", "水处理", "氮处理", "重复", "DMFR", "SOURCE_SHEET"]])
    quality_raw = pd.concat(quality_frames, ignore_index=True)
    if quality_raw.duplicated(["TRNO", "QUALITY_DATE", "重复"]).any():
        raise ValueError("2026春: 品质表的小区/日期/重复键重复")
    if quality_raw[["TRNO", "QUALITY_DATE", "DMFR"]].isna().any().any() or not quality_raw["DMFR"].between(0.0, 1.0).all():
        raise ValueError("2026春: 半果含水率无法转换为有效果实干物质率")
    quality_dm = quality_raw.groupby(["TRNO", "QUALITY_DATE"], as_index=False).agg(DMFR=("DMFR", "mean"), N_REP=("重复", "nunique"))
    matched = nearest_by_plot(events, quality_dm, "HARVEST_DATE", "QUALITY_DATE")
    matched["HARVEST_DRY"] = matched["HARVEST_FRESH"] * matched["DMFR"]
    matched = matched.sort_values(["TRNO", "HARVEST_DATE"])
    matched["CHFPW"] = matched.groupby("TRNO")["HARVEST_FRESH"].cumsum()
    matched["CHPDT"] = matched.groupby("TRNO")["HARVEST_DRY"].cumsum()
    harvest = matched[["TRNO", "HARVEST_DATE", "CHFPW", "CHPDT"]].rename(columns={"HARVEST_DATE": "DATE"})

    g1 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0502")
    g2 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0602")
    g3 = pd.read_excel(folder / "2026春生长指标集.xlsx", sheet_name="0629")
    require_columns(g1, ["取样日期", "小区", "重复", "茎干重", "叶干重", "LAI"], "2026春 0502 生长表")
    require_columns(g2, ["取样日期", "处理", "重复", "茎干重", "叶干重", "LAI"], "2026春 0602 生长表")
    require_columns(g3, ["取样日期", "处理 (Treatment)", "重复", "茎干重", "叶干重"], "2026春 0629 生长表")
    verify_treatment_mapping(
        [(yield_raw, "小区号"), (g1, "小区"), (g2, "处理"), (g3, "处理 (Treatment)"), (quality_raw, "TRNO")],
        "2026春",
    )

    factor = density / 1000.0
    early = (
        g1.groupby(["小区", "取样日期"], as_index=False)
        .agg(LAID=("LAI", "mean"), STEM_G=("茎干重", "mean"), LEAF_G=("叶干重", "mean"), N_REP=("重复", "nunique"))
        .rename(columns={"小区": "TRNO", "取样日期": "DATE"})
    )
    early["DATE"] = parse_yyyymmdd(early["DATE"])
    early["SWAD"] = early["STEM_G"] * factor
    early["LWAD"] = early["LEAF_G"] * factor

    middle = (
        g2.groupby(["处理", "取样日期"], as_index=False)
        .agg(LAID=("LAI", "mean"), STEM_G=("茎干重", "mean"), LEAF_G=("叶干重", "mean"), N_REP=("重复", "nunique"))
        .rename(columns={"处理": "TRNO", "取样日期": "DATE"})
    )
    middle["DATE"] = parse_yyyymmdd(middle["DATE"])
    middle["SWAD"] = middle["STEM_G"] * factor
    middle["LWAD"] = middle["LEAF_G"] * factor

    late = (
        g3.groupby(["处理 (Treatment)", "取样日期"], as_index=False)
        .agg(STEM_G=("茎干重", "mean"), LEAF_G=("叶干重", "mean"), N_REP=("重复", "nunique"))
        .rename(columns={"处理 (Treatment)": "TRNO", "取样日期": "DATE"})
    )
    late["DATE"] = parse_yyyymmdd(late["DATE"])
    late["LAID"] = np.nan
    late["SWAD"] = late["STEM_G"] * factor
    late["LWAD"] = late["LEAF_G"] * factor
    growth = pd.concat([early, middle, late], ignore_index=True, sort=False)
    nitrogen = pd.DataFrame(columns=["TRNO", "DATE", "SNAD", "LNAD"])

    return SeasonResult(
        key="2026spring",
        output_base="2026SPR",
        title="2026 SPRING EGGPLANT; TRNO=PLOT NUMBER",
        source_notes=[
            "Fresh yield is a per-harvest measurement and is cumulatively summed by plot.",
            "Fruit DM fraction = 1 - measured half-fruit moisture fraction in the quality workbook.",
            "Each harvest uses the nearest plot-level quality measurement date.",
            "Standing-fruit biomass indicators are omitted because of sampling error.",
        ],
        growth=growth,
        nitrogen=nitrogen,
        harvest=harvest,
        warnings=[],
        qa_metrics={
            "plots": int(harvest["TRNO"].nunique()),
            "growth_dates": int(growth["DATE"].nunique()),
            "harvest_dates": int(harvest["DATE"].nunique()),
            "harvest_events": int(events["EVENT_ID"].nunique()),
            "harvest_event_dates": ", ".join(str(pd.Timestamp(value).date()) for value in sorted(events["HARVEST_DATE"].unique())),
            "quality_dates": ", ".join(str(pd.Timestamp(value).date()) for value in sorted(quality_dm["QUALITY_DATE"].unique())),
            "quality_dm_fraction_min": float(quality_raw["DMFR"].min()),
            "quality_dm_fraction_max": float(quality_raw["DMFR"].max()),
            "harvest_quality_match_max_days": int(matched["MATCH_DAYS"].max()),
            "density": float(density),
            "inferred_density_min": float(inferred_density.min()),
            "inferred_density_max": float(inferred_density.max()),
        },
    )


def first_nonnull(series: pd.Series) -> object:
    values = series.dropna()
    return np.nan if values.empty else values.iloc[0]


def prepare_filet(result: SeasonResult) -> pd.DataFrame:
    frames = []
    for frame in (result.growth, result.nitrogen, result.harvest):
        if not frame.empty:
            frames.append(frame[[c for c in T_COLUMNS if c in frame.columns]].copy())
    stacked = pd.concat(frames, ignore_index=True, sort=False)
    filet = stacked.groupby(["TRNO", "DATE"], as_index=False).agg(first_nonnull)
    for column in T_COLUMNS:
        if column not in filet:
            filet[column] = np.nan
    return filet[T_COLUMNS].sort_values(["TRNO", "DATE"]).reset_index(drop=True)


def prepare_filea(result: SeasonResult, filet: pd.DataFrame) -> pd.DataFrame:
    trnos = sorted(set(filet["TRNO"].dropna().astype(int)))
    filea = pd.DataFrame({"TRNO": trnos})

    final_harvest = result.harvest.sort_values("DATE").groupby("TRNO", as_index=False).tail(1)
    final_harvest = final_harvest[["TRNO", "CHPDT", "CHFPW", "DATE"]].rename(columns={"CHPDT": "HWAH", "CHFPW": "HWAHF", "DATE": "HDAT"})
    filea = filea.merge(final_harvest, on="TRNO", how="left", validate="one_to_one")

    max_lai = result.growth.groupby("TRNO", as_index=False)["LAID"].max().rename(columns={"LAID": "LAIX"})
    final_growth = result.growth.sort_values("DATE").groupby("TRNO", as_index=False).tail(1)[["TRNO", "LWAD"]].rename(columns={"LWAD": "LWAM"})
    filea = filea.merge(max_lai, on="TRNO", how="left", validate="one_to_one")
    filea = filea.merge(final_growth, on="TRNO", how="left", validate="one_to_one")

    n_rows = filet[filet["SNAD"].notna()].copy()
    if not n_rows.empty:
        final_n = n_rows.sort_values("DATE").groupby("TRNO", as_index=False).tail(1)[["TRNO", "SNAD"]].rename(columns={"SNAD": "SNAM"})
        filea = filea.merge(final_n, on="TRNO", how="left", validate="one_to_one")
    else:
        filea["SNAM"] = np.nan
    for column in A_COLUMNS:
        if column not in filea:
            filea[column] = np.nan
    return filea[A_COLUMNS].sort_values("TRNO").reset_index(drop=True)


def yrdoy(value: object) -> int:
    date = pd.Timestamp(value)
    return int(f"{date.year % 100:02d}{date.dayofyear:03d}")


DECIMALS = {
    "LAID": 3,
    "LAIX": 3,
    "SNAD": 1,
    "LNAD": 1,
    "SNAM": 1,
}


def format_field(column: str, value: object) -> str:
    if pd.isna(value):
        return f"{-99:>6d}"
    if column in {"TRNO", "DATE", "HDAT"}:
        number = yrdoy(value) if column in {"DATE", "HDAT"} else int(value)
        return f"{number:>6d}"
    rendered = f"{float(value):>6.{DECIMALS.get(column, 0)}f}"
    if len(rendered) > 6:
        raise ValueError(f"{column}={value} 无法放入 DSSAT 6 字符字段")
    return rendered


def write_dssat(path: Path, kind: str, result: SeasonResult, df: pd.DataFrame, extra_comment: str) -> None:
    columns = list(df.columns)
    header = "@TRNO" + "".join(f"{column:>6}" for column in columns[1:])
    comments = [
        "Generated only from measured data in the named season folder.",
        "TRNO = plot number; within-plot replicates were averaged.",
        "Missing numeric values = -99; dates = YYDDD.",
        extra_comment,
        *result.source_notes,
    ]
    lines = [f"*EXP. DATA ({kind}): {result.title}", "", *[f"! {c}" for c in comments], "", header]
    for row in df.itertuples(index=False, name=None):
        lines.append("".join(format_field(column, value) for column, value in zip(columns, row)))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def validate_outputs(result: SeasonResult, filea: pd.DataFrame, filet: pd.DataFrame) -> list[str]:
    prohibited = {"HWAD", "FWAD", "CWAD", "FRNAD", "CNAD", "CWAM", "CNAM", "FRNAM"}
    if prohibited.intersection(filea.columns) or prohibited.intersection(filet.columns):
        raise AssertionError("输出包含用户明确禁止的列")
    if filet.duplicated(["TRNO", "DATE"]).any() or filea["TRNO"].duplicated().any():
        raise AssertionError("输出键不唯一")

    harvest_keys = set(map(tuple, result.harvest[["TRNO", "DATE"]].itertuples(index=False, name=None)))
    for row in filet.itertuples(index=False):
        is_harvest = (row.TRNO, row.DATE) in harvest_keys
        if not is_harvest and (pd.notna(row.CHFPW) or pd.notna(row.CHPDT)):
            raise AssertionError("非采收日出现 CHFPW/CHPDT 数值")

    for trno, group in result.harvest.sort_values(["TRNO", "DATE"]).groupby("TRNO"):
        fresh_diff = group["CHFPW"].diff().dropna()
        if (fresh_diff <= 0).any():
            raise AssertionError(f"TRNO={trno} CHFPW 存在非正增量")
        dry_diff = group["CHPDT"].diff().dropna()
        if not dry_diff.empty and (dry_diff <= 0).any():
            raise AssertionError(f"TRNO={trno} CHPDT 存在非正增量")

    final_t = result.harvest.sort_values("DATE").groupby("TRNO", as_index=False).tail(1).set_index("TRNO").sort_index()
    final_a = filea.set_index("TRNO").sort_index()
    if not np.allclose(final_a["HWAHF"], final_t["CHFPW"], equal_nan=True):
        raise AssertionError("File A HWAHF 与 File T 最终 CHFPW 不一致")
    if not np.allclose(final_a["HWAH"], final_t["CHPDT"], equal_nan=True):
        raise AssertionError("File A HWAH 与 File T 最终 CHPDT 不一致")
    return [
        "非采收日 CHFPW/CHPDT 全部为缺失值。",
        "所有小区 CHFPW 的相邻采收日增量均为正。",
        "有干产量的季节，CHPDT 的相邻采收日增量均为正。",
        "File A HWAHF/HWAH 与最终 CHFPW/CHPDT 一致。",
        "输出不包含 HWAD、FWAD、CWAD、FRNAD、CNAD、CWAM、CNAM、FRNAM。",
    ]


def write_csv(path: Path, df: pd.DataFrame) -> None:
    export = df.copy()
    for date_column in ("DATE", "HDAT"):
        if date_column in export:
            export[date_column] = export[date_column].map(yrdoy)
    export = export.fillna(MISSING)
    export.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")


def write_qa(path: Path, result: SeasonResult, filea: pd.DataFrame, filet: pd.DataFrame, checks: list[str]) -> None:
    harvest_rows = filet[filet[["CHFPW", "CHPDT"]].notna().any(axis=1)]
    lines = [
        f"# {result.title.split(';')[0]} DSSAT File A / File T 质量检查",
        "",
        "## 输出摘要",
        "",
        f"- File A：{len(filea)} 行，TRNO {int(filea['TRNO'].min())}–{int(filea['TRNO'].max())}。",
        f"- File T：{len(filet)} 行，{filet['DATE'].nunique()} 个不同观测日。",
        f"- 含采收数据的 File T 行：{len(harvest_rows)}。",
        "- File T 产量列：`CHFPW`（累计鲜果重）、`CHPDT`（累计干果重）。",
        "",
        "## 自动校验",
        "",
        *[f"- {check}" for check in checks],
        "",
        "## 源数据与换算",
        "",
        *[f"- {note}" for note in result.source_notes],
    ]
    for key, value in result.qa_metrics.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## 需要人工关注", ""])
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- 未发现需要额外人工处理的问题。")
    lines.extend(
        [
            "",
            "## 统一口径",
            "",
            "- `CHFPW/CHPDT` 只在实际采收日填入截至当日的累计值；其他日在 DSSAT/CSV 中为 `-99`。",
            "- 由于留株果实取样误差过大，不输出 `FWAD/CWAD/FRNAD/CNAD/FRNAM`。",
            "- `SWAD/LWAD/SNAD/LNAD` 仅表示当日茎、叶的现存量。",
            "- 种植密度换算：`g/株 × 株/ha ÷ 1000 = kg/ha`。",
            "- 官方代码定义：DSSAT `DATA.CDE` 与 CROPGRO `FreshWt.for`。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def output_paths(root: Path, result: SeasonResult, crop_code: str, output_dir: Path | None, output_base: str | None) -> dict[str, Path]:
    season_folder = {"2025spring": "2025春", "2025fall": "2025秋", "2026spring": "2026春"}[result.key]
    folder = output_dir if output_dir is not None else root / season_folder / "DSSAT输出"
    folder.mkdir(parents=True, exist_ok=True)
    base = output_base or result.output_base
    paths = {
        "filea": folder / f"{base}.{crop_code}A",
        "filet": folder / f"{base}.{crop_code}T",
        "filea_csv": folder / f"{base}_FileA_values.csv",
        "filet_csv": folder / f"{base}_FileT_values.csv",
        "qa": folder / f"{base}_QA.md",
    }
    if result.dm_filter_audit is not None:
        paths["dm_filter_audit"] = folder / f"{base}_DM_filter_audit.csv"
    return paths


def build_one(result: SeasonResult, root: Path, crop_code: str, output_dir: Path | None = None, output_base: str | None = None) -> dict[str, Path]:
    filet = prepare_filet(result)
    filea = prepare_filea(result, filet)
    checks = validate_outputs(result, filea, filet)
    paths = output_paths(root, result, crop_code, output_dir, output_base)
    write_dssat(paths["filea"], "A", result, filea, "HWAHF/HWAH are final cumulative fresh/dry harvested fruit yields.")
    write_dssat(paths["filet"], "T", result, filet, "CHFPW/CHPDT appear only on actual harvest dates; standing-fruit status variables are omitted.")
    write_csv(paths["filea_csv"], filea)
    write_csv(paths["filet_csv"], filet)
    write_qa(paths["qa"], result, filea, filet, checks)
    if result.dm_filter_audit is not None:
        audit = result.dm_filter_audit.copy()
        audit["DATE"] = audit["DATE"].map(lambda value: str(pd.Timestamp(value).date()))
        audit.to_csv(paths["dm_filter_audit"], index=False, encoding="utf-8-sig", float_format="%.6f")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 2025春、2025秋、2026春 DSSAT File A / File T")
    parser.add_argument("--season", action="append", choices=("2025spring", "2025fall", "2026spring"), help="可重复指定；默认生成三季")
    parser.add_argument("--crop-code", default="TM", help="DSSAT 两字符作物代码，默认 TM")
    parser.add_argument("--plant-density", type=float, default=27000.0, help="株/ha，默认 27000")
    parser.add_argument("--fruit-dm-method", choices=("mean", "median", "pooled"), default="mean", help="2025秋小区果实干物质率聚合方法")
    parser.add_argument("--min-fruit-dry-weight", type=float, default=10.0, help="2025秋果实干物质率样本的最小果干重(g)，默认 10")
    parser.add_argument("--output-dir", type=Path, default=None, help="仅单季时可覆盖输出目录")
    parser.add_argument("--output-base", default=None, help="仅单季时可覆盖输出主名")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crop_code = args.crop_code.upper()
    if len(crop_code) != 2 or not crop_code.isalnum():
        raise ValueError("--crop-code 必须是两个字母或数字")
    if args.min_fruit_dry_weight <= 0:
        raise ValueError("--min-fruit-dry-weight 必须大于 0")
    seasons = args.season or ["2025spring", "2025fall", "2026spring"]
    if len(seasons) != 1 and (args.output_dir is not None or args.output_base is not None):
        raise ValueError("--output-dir/--output-base 只能与单个 --season 一起使用")
    root = Path(__file__).resolve().parent
    loaders = {
        "2025spring": lambda: load_2025_spring(root, args.plant_density),
        "2025fall": lambda: load_2025_fall(root, args.plant_density, args.fruit_dm_method, args.min_fruit_dry_weight),
        "2026spring": lambda: load_2026_spring(root, args.plant_density),
    }
    for key in seasons:
        result = loaders[key]()
        paths = build_one(result, root, crop_code, args.output_dir, args.output_base)
        print(f"{key}:")
        for path in paths.values():
            print(f"  {path}")


if __name__ == "__main__":
    main()
