#!/usr/bin/env python3
"""Build soil water observations + layer mapping + match audit for 25SP/25FA/26SP.

Complies with docs/土壤水分进入Phi与土壤参数预筛方案_v1_20260726.md:

Section 1 (frozen observation rules):
  1. Soil VWC is NOT written to FileA/FileT; DSSAT output is SoilWat.OUT SW1D..SWnD.
  2. Per (season_id x trno x depth_interval), sort by date; earliest date is tagged
     initial_condition_only and does NOT generate a PEST observation.
  3. Remaining dates enter Phi as an independent SOIL_WATER group.
  4. 25SP: only TN 2,3,4,5,9,10,11,12,13,14; TN 1,6,7,8 excluded.
  5. 25FA: 2025-10-02 is a post-start field measurement because the TMX already
     supplies the initial condition; it therefore enters SOIL_WATER Phi.

Section 2.1 (depth layer mapping):
  Measured layers and DSSAT layers are NOT silently nearest-matched. For each
  measured layer m and DSSAT layer l, compute thickness-overlap weight:
    w_ml = overlap(m, l) / thickness(m)
    theta_m_sim = sum_l w_ml * theta_l_sim
  If weight sum != 1 or measured layer exceeds SOIL.SOL profile, abort with audit.

SD method:
  Same hybrid SD as trial observations (replicate SD with min CV=5%, fallback CV=10%).

Output directory layout (per season):
  {season_folder}/DSSAT输出_v2/
    soil_water_observations.csv         (mean, SD, n_rep, depth, weights, exclusion flags)
    soil_water_layer_mapping.csv        (measured_layer -> DSSAT layer overlap weights)
    soil_water_match_audit.csv          (per-row mapping audit + initial_condition flag)

Soil profile (IBTM910017, shared by all three seasons, parsed from SOIL.SOL):
  SLB:  20, 40, 60, 80, 100, 145, 175, 203
  Layer bottoms (cm), top of first layer = 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


# 25SP treatment exclusion (same as trial observations adapter)
SPRING25_INCLUDED_TN = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
SPRING25_EXCLUDED_TN = [1, 6, 7, 8]
SPRING25_EXCLUSION_REASON = "缺少实际 FileX 管理/初始条件定义"

# ACTUAL DSSAT SoilWat.OUT sub-layer boundaries (cm), updated 2026-07-26.
#
# The previous mapping used the 8 SLB layers from SOIL.SOL (20/40/60/80/100/
# 145/175/203). However, DSSAT v4.8 SoilWat.OUT subdivides the profile into
# 14 output sub-layers (SW1D..SW14D) that split several SLB layers (e.g.,
# the 0-20 layer is split into 0-5, 5-15, 15-20). Verified from actual
# SoilWat.OUT header comments in workspace/runs/E01_v2_soil_smoke_20260726.
#
# This is the GROUND TRUTH for layer mapping; the prior 8-SLB mapping
# silently dropped sub-layer variance for measured layers like 0-20 (which
# actually spans SW1D+SW2D+SW3D with weights 0.25/0.50/0.25).
DSSAT_SOILWAT_LAYER_TOPS = [
    0.0,   5.0,  15.0,  20.0,  30.0,  40.0,  50.0,
    60.0,  70.0,  80.0, 100.0, 122.0, 145.0, 175.0,
]
DSSAT_SOILWAT_LAYER_BOTTOMS = [
    5.0,  15.0,  20.0,  30.0,  40.0,  50.0,  60.0,
    70.0,  80.0, 100.0, 122.0, 145.0, 175.0, 203.0,
]
N_DSSAT_SOILWAT_LAYERS = len(DSSAT_SOILWAT_LAYER_BOTTOMS)  # 14

# Default DSSAT soil profile layer bottoms (IBTM910017) -- DEPRECATED for
# mapping; kept for backward compatibility / SOIL.SOL audit only.
DEFAULT_SOIL_LAYER_BOTTOMS = DSSAT_SOILWAT_LAYER_BOTTOMS
DEFAULT_SOIL_ID = "IBTM910017"

# Season -> excode mapping
SEASON_EXCODE = {"25SP": "XXQL2501", "25FA": "XXQL2502", "26SP": "XXQL2601"}
SEASON_FOLDER = {"25SP": "2025春", "25FA": "2025秋", "26SP": "2026春"}


# ----------------------------------------------------------------------------
# Utilities (shared logic with trial observations adapter, intentionally
# duplicated to keep this adapter self-contained and single-file per spec)
# ----------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hybrid_sd(values, min_cv: float = 0.05, fallback_cv: float = 0.10):
    """Compute hybrid SD. Returns (sd, sd_method, n_rep)."""
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


def parse_yyyymmdd(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return pd.to_datetime(numeric.astype("Int64").astype(str), format="%Y%m%d", errors="coerce").dt.normalize()


def parse_depth_cm(depth_str: str) -> tuple[float, float]:
    """Parse '0-20' -> (0.0, 20.0). Returns (top_cm, bottom_cm)."""
    s = str(depth_str).strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$", s)
    if not m:
        raise ValueError(f"无法解析深度字符串: {depth_str!r}")
    top = float(m.group(1))
    bottom = float(m.group(2))
    if bottom <= top:
        raise ValueError(f"深度下限 <= 上限: {depth_str!r}")
    return top, bottom


# ----------------------------------------------------------------------------
# SOIL.SOL parser (minimal: extract SLB for a given soil_id)
# ----------------------------------------------------------------------------

def parse_soil_layer_bottoms(soil_sol_path: Path, soil_id: str) -> list[float]:
    """Parse SOIL.SOL and return SLB values for the given soil_id.

    Raises if soil_id not found or layer header missing.
    """
    text = soil_sol_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    in_target = False
    slb_header_idx = None
    slb_values: list[float] = []
    for i, line in enumerate(lines):
        if line.startswith(f"*{soil_id}"):
            in_target = True
            slb_header_idx = None
            slb_values = []
            continue
        if not in_target:
            continue
        # Stop at next soil profile
        if line.startswith("*") and not line.startswith("*SOILS"):
            break
        if line.strip().startswith("@") and "SLB" in line:
            # Find SLB column position
            header = line
            slb_pos = header.find("SLB")
            # Determine column width: SLB values are right-aligned in 5-char fields
            # following the @ header. We'll parse by fixed width.
            # DSSAT SOIL.SOL @SLB line format: "@  SLB  SLMH ..." with 5-char fields.
            slb_header_idx = i
            continue
        if slb_header_idx is not None and line.strip() and not line.startswith("!"):
            # Parse SLB from the line. SLB is the first numeric field after @.
            # The @ header has columns starting at fixed positions; SLB is col 1.
            # Use simple split on whitespace for robustness.
            parts = line.split()
            if not parts:
                continue
            try:
                slb = float(parts[0])
                slb_values.append(slb)
            except ValueError:
                # Non-numeric first field -> end of layer block
                break
    if not slb_values:
        raise ValueError(f"SOIL.SOL 中未找到 soil_id={soil_id} 的 SLB 层")
    return slb_values


# ----------------------------------------------------------------------------
# Layer overlap weights (Section 2.1)
# ----------------------------------------------------------------------------

def compute_overlap_weights(
    measured_top: float,
    measured_bottom: float,
    dssat_layer_bottoms: list[float],
) -> dict[int, float]:
    """Compute thickness-overlap weights for one measured layer.

    w_ml = overlap(m, l) / thickness(m)
    Returns {layer_index (0-based): weight}.
    """
    m_thickness = measured_bottom - measured_top
    if m_thickness <= 0:
        raise ValueError(f"实测层厚度 <= 0: top={measured_top}, bottom={measured_bottom}")
    weights: dict[int, float] = {}
    prev_bottom = 0.0
    for i, layer_bottom in enumerate(dssat_layer_bottoms):
        layer_top = prev_bottom
        # Overlap = max(0, min(m_bottom, l_bottom) - max(m_top, l_top))
        overlap = max(0.0, min(measured_bottom, layer_bottom) - max(measured_top, layer_top))
        if overlap > 0:
            weights[i] = overlap / m_thickness
        prev_bottom = layer_bottom
    # Validation: weights must sum to 1.0 if measured layer is within profile
    total_profile_depth = dssat_layer_bottoms[-1]
    if measured_bottom > total_profile_depth + 1e-6:
        raise ValueError(
            f"实测层 ({measured_bottom} cm) 超出 SOIL.SOL 轮廓 ({total_profile_depth} cm)")
    wsum = sum(weights.values())
    if not np.isclose(wsum, 1.0, atol=1e-6):
        raise ValueError(
            f"实测层 {measured_top}-{measured_bottom} 权重和 {wsum} != 1.0; "
            f"DSSAT layers={dssat_layer_bottoms}")
    return weights


# ----------------------------------------------------------------------------
# Season loaders
# ----------------------------------------------------------------------------

@dataclass
class SeasonSoilResult:
    season_id: str
    excode: str
    observations: pd.DataFrame      # raw obs: season_id, trno, date, depth_top, depth_bottom, vwc_mean, vwc_sd, ...
    layer_mapping: pd.DataFrame     # measured layer -> DSSAT layer weights
    match_audit: pd.DataFrame       # per-obs audit: trno, date, depth, initial_condition_only flag, weight_sum
    source_files: dict[str, str] = field(default_factory=dict)
    qa_metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _build_observations(
    season_id: str,
    excode: str,
    df: pd.DataFrame,
    *,
    plot_col: str,
    depth_col: str,
    vwc_col: str,
    rep_col: str | None,
    date_series: pd.Series,
    included_tn: list[int] | None,
    source_workbook: str,
    source_sheet: str,
    date_inference_note: str = "",
) -> pd.DataFrame:
    """Common observation builder: groupby (trno, date, depth) -> mean, SD, n_rep."""
    df = df.copy()
    df["TRNO"] = pd.to_numeric(df[plot_col], errors="coerce").astype("Int64")
    df["日期"] = date_series
    df = df.dropna(subset=["TRNO", "日期", vwc_col, depth_col]).copy()
    df["TRNO"] = df["TRNO"].astype(int)

    if included_tn is not None:
        df = df[df["TRNO"].isin(included_tn)].copy()

    rows = []
    for (trno, date, depth_str), grp in df.groupby(["TRNO", "日期", depth_col]):
        try:
            top, bottom = parse_depth_cm(depth_str)
        except ValueError as e:
            raise ValueError(f"{season_id} TRNO={trno} date={date}: {e}")
        vwc_vals = grp[vwc_col].dropna().values
        if len(vwc_vals) == 0:
            continue
        sd, src, n = hybrid_sd(vwc_vals)
        rows.append({
            "season_id": season_id,
            "excode": excode,
            "trno": int(trno),
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str),
            "depth_top_cm": top,
            "depth_bottom_cm": bottom,
            "vwc_mean": float(np.mean(vwc_vals)),
            "vwc_sd": sd,
            "vwc_sd_method": src,
            "n_rep": n,
            "source_workbook": source_workbook,
            "source_sheet": source_sheet,
            "source_row_rule": f"per_trno_date_depth_mean_replicates",
            "date_inference_note": date_inference_note,
            "quality_flag": "ok",
        })
    obs = pd.DataFrame(rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    return obs


def load_25sp_soil(root: Path, soil_layer_bottoms: list[float]) -> SeasonSoilResult:
    folder = root / "2025春"
    wb_path = folder / "2025春土壤数据集.xlsx"
    source_files = {str(wb_path): sha256_file(wb_path)}
    df = pd.read_excel(wb_path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    if "体积含水率" not in df.columns:
        raise ValueError("2025春土壤数据集 缺少 体积含水率 列")
    if "取样日期" not in df.columns:
        raise ValueError("2025春土壤数据集 缺少 取样日期 列")
    dates = pd.to_datetime(df["取样日期"], errors="coerce").dt.normalize()
    obs = _build_observations(
        "25SP", "XXQL2501", df,
        plot_col="小区号",
        depth_col="土层深度",
        vwc_col="体积含水率",
        rep_col="重复",
        date_series=dates,
        included_tn=SPRING25_INCLUDED_TN,
        source_workbook="2025春土壤数据集.xlsx",
        source_sheet="Sheet1",
    )
    return _finalize_season("25SP", "XXQL2501", obs, soil_layer_bottoms, source_files)


def load_25fa_soil(root: Path, soil_layer_bottoms: list[float]) -> SeasonSoilResult:
    """25FA soil: NO date column. Date inferred from filename '20251002_2号棚取土.xlsx'."""
    folder = root / "2025秋"
    wb_path = folder / "20251002_2号棚取土.xlsx"
    source_files = {str(wb_path): sha256_file(wb_path)}
    df = pd.read_excel(wb_path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    if "体积含水率" not in df.columns:
        raise ValueError("2025秋土壤数据集 缺少 体积含水率 列")
    if "深度" not in df.columns:
        raise ValueError("2025秋土壤数据集 缺少 深度 列")
    # Infer date from filename: 20251002 -> 2025-10-02
    m = re.search(r"(\d{8})", wb_path.stem)
    if not m:
        raise ValueError(f"无法从文件名 {wb_path.name} 推断日期")
    date_str = m.group(1)
    inferred_date = pd.Timestamp(year=int(date_str[:4]), month=int(date_str[4:6]), day=int(date_str[6:8]))
    dates = pd.Series([inferred_date] * len(df))
    obs = _build_observations(
        "25FA", "XXQL2502", df,
        plot_col="小区号",
        depth_col="深度",
        vwc_col="体积含水率",
        rep_col="重复",
        date_series=dates,
        included_tn=None,  # 25FA: all 12 plots
        source_workbook="20251002_2号棚取土.xlsx",
        source_sheet="Sheet1",
        date_inference_note="single_soil_sample_date_inferred_from_filename_20251002",
    )
    return _finalize_season("25FA", "XXQL2502", obs, soil_layer_bottoms, source_files)


def load_26sp_soil(root: Path, soil_layer_bottoms: list[float]) -> SeasonSoilResult:
    folder = root / "2026春"
    wb_path = folder / "2026春土壤数据集.xlsx"
    source_files = {str(wb_path): sha256_file(wb_path)}
    df = pd.read_excel(wb_path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    if "体积含水率" not in df.columns:
        raise ValueError("2026春土壤数据集 缺少 体积含水率 列")
    if "深度" not in df.columns:
        raise ValueError("2026春土壤数据集 缺少 深度 列")
    if "日期" not in df.columns:
        raise ValueError("2026春土壤数据集 缺少 日期 列")
    dates = parse_yyyymmdd(df["日期"])
    obs = _build_observations(
        "26SP", "XXQL2601", df,
        plot_col="小区号",
        depth_col="深度",
        vwc_col="体积含水率",
        rep_col="重复",
        date_series=dates,
        included_tn=None,  # 26SP: all 12 plots
        source_workbook="2026春土壤数据集.xlsx",
        source_sheet="Sheet1",
    )
    return _finalize_season("26SP", "XXQL2601", obs, soil_layer_bottoms, source_files)


def _finalize_season(
    season_id: str,
    excode: str,
    obs: pd.DataFrame,
    soil_layer_bottoms: list[float],
    source_files: dict[str, str],
) -> SeasonSoilResult:
    """Apply first-date exclusion + build layer mapping + match audit."""
    if obs.empty:
        raise ValueError(f"{season_id}: 无土壤水分观测")

    # Build layer mapping for each unique measured depth
    unique_depths = obs[["depth_label", "depth_top_cm", "depth_bottom_cm"]].drop_duplicates().sort_values("depth_top_cm")
    mapping_rows = []
    depth_to_weights: dict[str, dict[int, float]] = {}
    for _, r in unique_depths.iterrows():
        weights = compute_overlap_weights(r["depth_top_cm"], r["depth_bottom_cm"], soil_layer_bottoms)
        depth_to_weights[r["depth_label"]] = weights
        for layer_idx, w in weights.items():
            mapping_rows.append({
                "season_id": season_id,
                "measured_depth_label": r["depth_label"],
                "measured_depth_top_cm": r["depth_top_cm"],
                "measured_depth_bottom_cm": r["depth_bottom_cm"],
                "dssat_layer_index": layer_idx,
                # Use the canonical DSSAT SoilWat.OUT sub-layer tops/bottoms.
                # soil_layer_bottoms now carries the 14 SoilWat.OUT sub-layer
                # boundaries; layer tops are derived from the same source to
                # avoid mismatch when the underlying array changes.
                "dssat_layer_top_cm": DSSAT_SOILWAT_LAYER_TOPS[layer_idx],
                "dssat_layer_bottom_cm": DSSAT_SOILWAT_LAYER_BOTTOMS[layer_idx],
                "dssat_layer_sw_column": f"SW{layer_idx + 1}D",
                "overlap_weight": w,
            })
    layer_mapping = pd.DataFrame(mapping_rows)

    # Mark first date per (trno, depth) as initial_condition_only.  For 25FA,
    # 2025-10-02 is explicitly a post-start measurement; the TMX supplies the
    # initial condition, so do not silently discard this valid observation.
    obs["date_ts"] = pd.to_datetime(obs["date"])
    obs = obs.sort_values(["trno", "depth_label", "date_ts"]).reset_index(drop=True)
    if season_id == "25FA":
        obs["initial_condition_only"] = False
    else:
        obs["initial_condition_only"] = obs.groupby(["trno", "depth_label"])["date_ts"].transform("min") == obs["date_ts"]
    obs["phi_role"] = obs["initial_condition_only"].map({True: "initial_condition_only", False: "soil_water_phi"})
    obs = obs.drop(columns=["date_ts"])

    # Serialize DSSAT layer weights into the observations table as a JSON-like string
    obs["dssat_layer_weights"] = obs["depth_label"].map(
        lambda lbl: ";".join(f"{k}:{v:.6f}" for k, v in sorted(depth_to_weights[lbl].items()))
    )
    obs["weight_sum"] = obs["depth_label"].map(
        lambda lbl: sum(depth_to_weights[lbl].values())
    )

    # Match audit (per row)
    audit = obs[["trno", "date", "depth_label", "depth_top_cm", "depth_bottom_cm",
                 "vwc_mean", "vwc_sd", "n_rep",
                 "dssat_layer_weights", "weight_sum",
                 "initial_condition_only", "phi_role"]].copy()

    phi_count = int((obs["phi_role"] == "soil_water_phi").sum())
    ic_count = int((obs["phi_role"] == "initial_condition_only").sum())

    return SeasonSoilResult(
        season_id=season_id,
        excode=excode,
        observations=obs,
        layer_mapping=layer_mapping,
        match_audit=audit,
        source_files=source_files,
        qa_metrics={
            "plots": int(obs["trno"].nunique()),
            "dates": int(obs["date"].nunique()),
            "depths": int(obs["depth_label"].nunique()),
            "total_observations": int(len(obs)),
            "phi_observations": phi_count,
            "initial_condition_observations": ic_count,
            "soil_id": DEFAULT_SOIL_ID,
            "dssat_layer_bottoms_cm": soil_layer_bottoms,
        },
        warnings=[] if phi_count > 0 else [
            f"{season_id}: 该季只有一次土壤测量，全部观测为 initial_condition_only；SOIL_WATER Phi 观测数为 0"
        ],
    )


# ----------------------------------------------------------------------------
# Output writer
# ----------------------------------------------------------------------------

def write_soil_outputs(result: SeasonSoilResult, out_dir: Path, generator_sha: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    result.observations.to_csv(out_dir / "soil_water_observations.csv", index=False)
    result.layer_mapping.to_csv(out_dir / "soil_water_layer_mapping.csv", index=False)
    result.match_audit.to_csv(out_dir / "soil_water_match_audit.csv", index=False)

    log = {
        "season_id": result.season_id,
        "excode": result.excode,
        "generator": "tools/experiments/build_soil_water_observations.py",
        "generator_sha256": generator_sha,
        "spec_compliance": "docs/土壤水分进入Phi与土壤参数预筛方案_v1_20260726.md",
        "source_files": result.source_files,
        "qa_metrics": result.qa_metrics,
        "warnings": result.warnings,
        "output_files": [
            "soil_water_observations.csv",
            "soil_water_layer_mapping.csv",
            "soil_water_match_audit.csv",
        ],
    }
    (out_dir / "soil_water_generator_log.json").write_text(
        json.dumps(log, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build soil water observations + layer mapping + audit.")
    parser.add_argument("--root", type=Path, default=Path(r"D:\Tomato_Cal\data\user\ref\DSSAT文件"),
                        help="Root directory containing 2025春/2025秋/2026春 subfolders")
    parser.add_argument("--seasons", nargs="+", default=["25SP", "25FA", "26SP"],
                        choices=["25SP", "25FA", "26SP"], help="Seasons to build")
    args = parser.parse_args()

    # Use the canonical 14 SoilWat.OUT sub-layer boundaries (no SOIL.SOL parse).
    # SoilWat.OUT subdivides the 8 SLB layers; using SLB directly would silently
    # drop sub-layer variance for measured depths that span multiple SWnD columns.
    soil_layer_bottoms = list(DSSAT_SOILWAT_LAYER_BOTTOMS)
    print(f"Using DSSAT SoilWat.OUT sub-layer boundaries (cm): {soil_layer_bottoms}")
    print(f"  n_layers={len(soil_layer_bottoms)}, SW columns: "
          f"{', '.join(f'SW{i+1}D' for i in range(len(soil_layer_bottoms)))}")

    generator_path = Path(__file__).resolve()
    generator_sha = sha256_file(generator_path)

    loaders = {"25SP": load_25sp_soil, "25FA": load_25fa_soil, "26SP": load_26sp_soil}
    for season in args.seasons:
        print(f"\n=== Building {season} soil water ===")
        result = loaders[season](args.root, soil_layer_bottoms)
        out_dir = args.root / SEASON_FOLDER[season] / "DSSAT输出_v2"
        write_soil_outputs(result, out_dir, generator_sha)
        print(f"  output_dir: {out_dir}")
        print(f"  plots: {result.qa_metrics['plots']}")
        print(f"  dates: {result.qa_metrics['dates']}")
        print(f"  depths: {result.qa_metrics['depths']}")
        print(f"  total_observations: {result.qa_metrics['total_observations']}")
        print(f"  phi_observations: {result.qa_metrics['phi_observations']}")
        print(f"  initial_condition_observations: {result.qa_metrics['initial_condition_observations']}")
        if result.warnings:
            for w in result.warnings:
                print(f"  WARNING: {w}")


if __name__ == "__main__":
    main()
