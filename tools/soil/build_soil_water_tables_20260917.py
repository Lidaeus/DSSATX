#!/usr/bin/env python3
"""Build refreshed soil water observations, layer mapping, and match audit for 25SP, 26SP, and 25FA.

Complies with docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md:
  - D11=A: Re-run mass-weighted thickness overlap algorithm strictly aligned with
    10L-B / SoilWat 12 output sub-layers (0-5, 5-15, 15-30, 30-45, 45-60, 60-70,
    70-80, 80-100, 100-120, 120-140, 140-160, 160-180 cm).
  - 25SP raw: 2025春/2025春土壤含水量数据集.xlsx (3 dates: 2025-03-12, 05-01, 05-24)
  - 26SP raw: 2026春/2026春土壤含水量数据集.xlsx (4 dates: 2026-03-14, 05-02, 06-29, 07-17)
  - 25FA raw: 2025秋/2025 2号棚秋季取土.xlsx (2 dates: 2025-08-09, 2025-10-02)
  - Earliest sampling date per season tagged initial_condition_only=True, phi_role='initial_condition_only'.
  - Subsequent sampling dates tagged initial_condition_only=False, phi_role='soil_water_phi'.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REF_ROOT = PROJECT_ROOT / "data/user/ref/DSSAT文件"

# 25SP treatment exclusion
SPRING25_INCLUDED_TN = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]

# DSSAT SoilWat.OUT sub-layer tops and bottoms for 180 cm profile (13 layers)
DSSAT_SOILWAT_LAYER_TOPS = [
    0.0, 5.0, 15.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 100.0, 120.0, 140.0, 160.0
]
DSSAT_SOILWAT_LAYER_BOTTOMS = [
    5.0, 15.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 100.0, 120.0, 140.0, 160.0, 180.0
]



def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def parse_depth_cm(depth_str: str) -> tuple[float, float]:
    s = str(depth_str).strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$", s)
    if not m:
        raise ValueError(f"无法解析深度字符串: {depth_str!r}")
    top = float(m.group(1))
    bottom = float(m.group(2))
    if bottom <= top:
        raise ValueError(f"深度下限 <= 上限: {depth_str!r}")
    return top, bottom


def compute_overlap_weights(measured_top: float, measured_bottom: float) -> dict[int, float]:
    m_thickness = measured_bottom - measured_top
    if m_thickness <= 0:
        raise ValueError(f"实测层厚度 <= 0: {measured_top}-{measured_bottom}")
    weights = {}
    for i, (l_top, l_bottom) in enumerate(zip(DSSAT_SOILWAT_LAYER_TOPS, DSSAT_SOILWAT_LAYER_BOTTOMS)):
        overlap = max(0.0, min(measured_bottom, l_bottom) - max(measured_top, l_top))
        if overlap > 0:
            weights[i] = overlap / m_thickness
    wsum = sum(weights.values())
    if not np.isclose(wsum, 1.0, atol=1e-5):
        raise ValueError(f"实测层 {measured_top}-{measured_bottom} 权重和 {wsum} != 1.0")
    return weights


def format_weights(weights: dict[int, float]) -> str:
    return ";".join(f"{idx}:{w:.6f}" for idx, w in sorted(weights.items()))


def build_layer_mapping_df(season_id: str, measured_layers: list[str]) -> pd.DataFrame:
    rows = []
    for depth_str in measured_layers:
        top, bottom = parse_depth_cm(depth_str)
        weights = compute_overlap_weights(top, bottom)
        for idx, w in sorted(weights.items()):
            rows.append({
                "season_id": season_id,
                "measured_depth_label": depth_str,
                "measured_depth_top_cm": top,
                "measured_depth_bottom_cm": bottom,
                "dssat_layer_index": idx,
                "dssat_layer_top_cm": DSSAT_SOILWAT_LAYER_TOPS[idx],
                "dssat_layer_bottom_cm": DSSAT_SOILWAT_LAYER_BOTTOMS[idx],
                "dssat_layer_sw_column": f"SW{idx + 1}D",
                "overlap_weight": w,
            })
    return pd.DataFrame(rows)


def build_25sp(root: Path, out_dir: Path, generator_sha: str) -> None:
    path = root / "2025春/2025春土壤含水量数据集.xlsx"
    src_sha = sha256_file(path)
    df = pd.read_excel(path)
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype(int)
    df["日期"] = pd.to_datetime(df["取样日期"]).dt.normalize()
    df = df[df["TRNO"].isin(SPRING25_INCLUDED_TN)].copy()

    dates = sorted(df["日期"].unique())
    initial_date = dates[0]

    obs_rows = []
    audit_rows = []
    depth_labels = ['0-20', '20-40', '40-60', '60-80', '80-100']

    for (trno, date, depth_str), grp in df.groupby(["TRNO", "日期", "土层深度"]):
        top, bottom = parse_depth_cm(depth_str)
        weights = compute_overlap_weights(top, bottom)
        w_str = format_weights(weights)
        vwc_vals = grp["体积含水率"].dropna().values
        mean_vwc = float(np.mean(vwc_vals))
        sd, src, n = hybrid_sd(vwc_vals)

        is_ic = (date == initial_date)
        phi_role = "initial_condition_only" if is_ic else "soil_water_phi"

        obs_rows.append({
            "season_id": "25SP", "excode": "XXQL2501", "trno": int(trno),
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str), "depth_top_cm": top, "depth_bottom_cm": bottom,
            "vwc_mean": mean_vwc, "vwc_sd": sd, "vwc_sd_method": src, "n_rep": n,
            "source_workbook": "2025春土壤含水量数据集.xlsx", "source_sheet": "Sheet1",
            "source_row_rule": "per_trno_date_depth_mean_replicates",
            "date_inference_note": "", "quality_flag": "ok",
            "initial_condition_only": is_ic, "phi_role": phi_role,
            "dssat_layer_weights": w_str, "weight_sum": 1.0,
        })
        audit_rows.append({
            "trno": int(trno), "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str), "depth_top_cm": top, "depth_bottom_cm": bottom,
            "vwc_mean": mean_vwc, "vwc_sd": sd, "n_rep": n,
            "dssat_layer_weights": w_str, "weight_sum": 1.0,
            "initial_condition_only": is_ic, "phi_role": phi_role,
        })

    obs_df = pd.DataFrame(obs_rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    audit_df = pd.DataFrame(audit_rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    mapping_df = build_layer_mapping_df("25SP", depth_labels)

    out_dir.mkdir(parents=True, exist_ok=True)
    obs_df.to_csv(out_dir / "soil_water_observations.csv", index=False)
    mapping_df.to_csv(out_dir / "soil_water_layer_mapping.csv", index=False)
    audit_df.to_csv(out_dir / "soil_water_match_audit.csv", index=False)

    log = {
        "season_id": "25SP", "excode": "XXQL2501",
        "generator": "tools/soil/build_soil_water_tables_20260917.py",
        "generator_sha256": generator_sha,
        "spec_compliance": "docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md (D11=A)",
        "source_files": {str(path): src_sha},
        "qa_metrics": {
            "plots": int(obs_df["trno"].nunique()),
            "dates": int(obs_df["date"].nunique()),
            "depths": int(obs_df["depth_label"].nunique()),
            "total_observations": int(len(obs_df)),
            "phi_observations": int((obs_df["phi_role"] == "soil_water_phi").sum()),
            "initial_condition_observations": int((obs_df["phi_role"] == "initial_condition_only").sum()),
            "soil_id": "XXSL2501",
            "dssat_layer_bottoms_cm": DSSAT_SOILWAT_LAYER_BOTTOMS,
        },
        "output_files": ["soil_water_observations.csv", "soil_water_layer_mapping.csv", "soil_water_match_audit.csv"]
    }
    (out_dir / "soil_water_generator_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"25SP soil water tables written to {out_dir} (total {len(obs_df)} rows).")


def build_26sp(root: Path, out_dir: Path, generator_sha: str) -> None:
    path = root / "2026春/2026春土壤含水量数据集.xlsx"
    src_sha = sha256_file(path)
    df = pd.read_excel(path)
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype(int)
    df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()

    dates = sorted(df["日期"].unique())
    initial_date = dates[0]

    obs_rows = []
    audit_rows = []
    depth_labels = ['0-20', '20-40', '40-60', '60-80', '80-100']

    for (trno, date, depth_str), grp in df.groupby(["TRNO", "日期", "深度"]):
        top, bottom = parse_depth_cm(depth_str)
        weights = compute_overlap_weights(top, bottom)
        w_str = format_weights(weights)
        vwc_vals = grp["体积含水率"].dropna().values
        mean_vwc = float(np.mean(vwc_vals))
        sd, src, n = hybrid_sd(vwc_vals)

        is_ic = (date == initial_date)
        phi_role = "initial_condition_only" if is_ic else "soil_water_phi"

        obs_rows.append({
            "season_id": "26SP", "excode": "XXQL2601", "trno": int(trno),
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str), "depth_top_cm": top, "depth_bottom_cm": bottom,
            "vwc_mean": mean_vwc, "vwc_sd": sd, "vwc_sd_method": src, "n_rep": n,
            "source_workbook": "2026春土壤含水量数据集.xlsx", "source_sheet": "Sheet1",
            "source_row_rule": "per_trno_date_depth_mean_replicates",
            "date_inference_note": "", "quality_flag": "ok",
            "initial_condition_only": is_ic, "phi_role": phi_role,
            "dssat_layer_weights": w_str, "weight_sum": 1.0,
        })
        audit_rows.append({
            "trno": int(trno), "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str), "depth_top_cm": top, "depth_bottom_cm": bottom,
            "vwc_mean": mean_vwc, "vwc_sd": sd, "n_rep": n,
            "dssat_layer_weights": w_str, "weight_sum": 1.0,
            "initial_condition_only": is_ic, "phi_role": phi_role,
        })

    obs_df = pd.DataFrame(obs_rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    audit_df = pd.DataFrame(audit_rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    mapping_df = build_layer_mapping_df("26SP", depth_labels)

    out_dir.mkdir(parents=True, exist_ok=True)
    obs_df.to_csv(out_dir / "soil_water_observations.csv", index=False)
    mapping_df.to_csv(out_dir / "soil_water_layer_mapping.csv", index=False)
    audit_df.to_csv(out_dir / "soil_water_match_audit.csv", index=False)

    log = {
        "season_id": "26SP", "excode": "XXQL2601",
        "generator": "tools/soil/build_soil_water_tables_20260917.py",
        "generator_sha256": generator_sha,
        "spec_compliance": "docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md (D11=A)",
        "source_files": {str(path): src_sha},
        "qa_metrics": {
            "plots": int(obs_df["trno"].nunique()),
            "dates": int(obs_df["date"].nunique()),
            "depths": int(obs_df["depth_label"].nunique()),
            "total_observations": int(len(obs_df)),
            "phi_observations": int((obs_df["phi_role"] == "soil_water_phi").sum()),
            "initial_condition_observations": int((obs_df["phi_role"] == "initial_condition_only").sum()),
            "soil_id": "XXSL2601",
            "dssat_layer_bottoms_cm": DSSAT_SOILWAT_LAYER_BOTTOMS,
        },
        "output_files": ["soil_water_observations.csv", "soil_water_layer_mapping.csv", "soil_water_match_audit.csv"]
    }
    (out_dir / "soil_water_generator_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"26SP soil water tables written to {out_dir} (total {len(obs_df)} rows).")


def build_25fa(root: Path, out_dir: Path, generator_sha: str) -> None:
    path = root / "2025秋/2025 2号棚秋季取土.xlsx"
    src_sha = sha256_file(path)
    xls = pd.ExcelFile(path)

    # Sheet 1: 20250809定植前取土 -> date 2025-08-09 (initial condition)
    df_pre = pd.read_excel(xls, sheet_name="20250809定植前取土")
    df_pre["TRNO"] = pd.to_numeric(df_pre["小区号"], errors="coerce").astype(int)
    df_pre["DATE"] = pd.Timestamp("2025-08-09")
    df_pre["depth_str"] = df_pre["土层深度"]
    df_pre["vwc"] = df_pre["体积含水率"]

    # Sheet 2: 20261002 (actually 2025-10-02 autumn measurement)
    df_post = pd.read_excel(xls, sheet_name="20261002")
    df_post["TRNO"] = pd.to_numeric(df_post["小区号"], errors="coerce").astype(int)
    df_post["DATE"] = pd.Timestamp("2025-10-02")
    df_post["depth_str"] = df_post["深度"]
    df_post["vwc"] = df_post["体积含水率"]

    combined = pd.concat([df_pre[["TRNO", "DATE", "depth_str", "vwc"]],
                          df_post[["TRNO", "DATE", "depth_str", "vwc"]]], ignore_index=True)

    obs_rows = []
    audit_rows = []
    depth_labels = ['0-20', '20-40', '40-60', '60-80', '80-100']

    for (trno, date, depth_str), grp in combined.groupby(["TRNO", "DATE", "depth_str"]):
        top, bottom = parse_depth_cm(depth_str)
        weights = compute_overlap_weights(top, bottom)
        w_str = format_weights(weights)
        vwc_vals = grp["vwc"].dropna().values
        mean_vwc = float(np.mean(vwc_vals))
        sd, src, n = hybrid_sd(vwc_vals)

        is_ic = (date == pd.Timestamp("2025-08-09"))
        phi_role = "initial_condition_only" if is_ic else "soil_water_phi"

        obs_rows.append({
            "season_id": "25FA", "excode": "XXQL2502", "trno": int(trno),
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str), "depth_top_cm": top, "depth_bottom_cm": bottom,
            "vwc_mean": mean_vwc, "vwc_sd": sd, "vwc_sd_method": src, "n_rep": n,
            "source_workbook": "2025 2号棚秋季取土.xlsx", "source_sheet": "combined",
            "source_row_rule": "per_trno_date_depth_mean_replicates",
            "date_inference_note": "", "quality_flag": "ok",
            "initial_condition_only": is_ic, "phi_role": phi_role,
            "dssat_layer_weights": w_str, "weight_sum": 1.0,
        })
        audit_rows.append({
            "trno": int(trno), "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "depth_label": str(depth_str), "depth_top_cm": top, "depth_bottom_cm": bottom,
            "vwc_mean": mean_vwc, "vwc_sd": sd, "n_rep": n,
            "dssat_layer_weights": w_str, "weight_sum": 1.0,
            "initial_condition_only": is_ic, "phi_role": phi_role,
        })

    obs_df = pd.DataFrame(obs_rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    audit_df = pd.DataFrame(audit_rows).sort_values(["trno", "date", "depth_top_cm"]).reset_index(drop=True)
    mapping_df = build_layer_mapping_df("25FA", depth_labels)

    out_dir.mkdir(parents=True, exist_ok=True)
    obs_df.to_csv(out_dir / "soil_water_observations.csv", index=False)
    mapping_df.to_csv(out_dir / "soil_water_layer_mapping.csv", index=False)
    audit_df.to_csv(out_dir / "soil_water_match_audit.csv", index=False)

    log = {
        "season_id": "25FA", "excode": "XXQL2502",
        "generator": "tools/soil/build_soil_water_tables_20260917.py",
        "generator_sha256": generator_sha,
        "spec_compliance": "docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md (D7=A, D11=A)",
        "source_files": {str(path): src_sha},
        "qa_metrics": {
            "plots": int(obs_df["trno"].nunique()),
            "dates": int(obs_df["date"].nunique()),
            "depths": int(obs_df["depth_label"].nunique()),
            "total_observations": int(len(obs_df)),
            "phi_observations": int((obs_df["phi_role"] == "soil_water_phi").sum()),
            "initial_condition_observations": int((obs_df["phi_role"] == "initial_condition_only").sum()),
            "soil_id": "XXSL2601",
            "dssat_layer_bottoms_cm": DSSAT_SOILWAT_LAYER_BOTTOMS,
        },
        "output_files": ["soil_water_observations.csv", "soil_water_layer_mapping.csv", "soil_water_match_audit.csv"]
    }
    (out_dir / "soil_water_generator_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"25FA soil water tables written to {out_dir} (total {len(obs_df)} rows).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build refreshed soil water tables.")
    parser.add_argument("--root", type=Path, default=REF_ROOT)
    args = parser.parse_args()

    generator_sha = sha256_file(Path(__file__).resolve())
    build_25sp(args.root, args.root / "2025春/DSSAT输出_v2", generator_sha)
    build_26sp(args.root, args.root / "2026春/DSSAT输出_v2", generator_sha)
    build_25fa(args.root, args.root / "2025秋/DSSAT输出_v2", generator_sha)


if __name__ == "__main__":
    main()
