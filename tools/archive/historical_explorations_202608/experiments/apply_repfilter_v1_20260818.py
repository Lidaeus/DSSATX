"""Build corrected replicate-filtered spring bundles.

The canonical trial-observation generator owns moisture matching, uncertainty
rules and six-character FileA/FileT formatting.  This script applies only the
approved replicate exclusions to its in-memory results, then writes two new
versioned bundles without modifying their parent bundles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.experiments.build_trial_observations_v2_20260726 as generator

REF_ROOT = ROOT / "data/user/ref/DSSAT文件"
X25 = REF_ROOT / "2025春/2025春作物生长指标集.xlsx"
X26 = REF_ROOT / "2026春/2026春生长指标集.xlsx"
BASE25 = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"
BASE26 = ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"
NEW25 = ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v2_20260819"
NEW26 = ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v2_20260819"

# (season, plot, source date/sheet, variable scope, replicate id, channel)
REMOVALS = [
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
    ("26SP", 5, "0629", "叶干重", "rep3", 2),
    ("26SP", 4, "0629", "叶干重", "rep3", 2),
    ("26SP", 7, "0629", "叶干重", "rep1", 2),
]
INCLUDED25 = set(generator.SPRING25_INCLUDED_TN)
SHEET26 = {"0502": "26122", "0602": "26153", "0629": "26180", "0717": "26198"}
VAR_MAP = {"株高": "CHTD", "茎干重": "SWAD", "叶干重": "LWAD", "LAI": "LAID"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_25() -> pd.DataFrame:
    frame = pd.read_excel(X25, sheet_name="Sheet1")
    frame["_date"] = pd.to_datetime(frame["日期"]).dt.strftime("%y%j")
    frame["_rep"] = frame["行位置"].astype(str)
    return frame


def _raw_26(sheet: str) -> pd.DataFrame:
    frame = pd.read_excel(X26, sheet_name=sheet)
    trcol = "小区" if sheet == "0502" else ("处理 (Treatment)" if sheet == "0629" else "处理")
    frame = frame.rename(columns={trcol: "_plot"})
    frame["_rep"] = "rep" + pd.to_numeric(frame["重复"], errors="raise").astype(int).astype(str)
    return frame


def _variables(target: str) -> list[str]:
    return ["株高", "茎干重", "叶干重", "LAI"] if target == "plant" else [target]


def _source_column(season: str, date: str, variable: str) -> str:
    if season == "25SP" or variable != "株高":
        return variable
    return {
        "0502": "株高",
        "0602": "株高 (cm)",
        "0629": "株高 (Plant Height / cm)",
        "0717": "株高 (cm)",
    }[date]


def _set_growth_value(result, plot: int, date_code: str, variable: str, values: pd.Series) -> dict:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    sd, method, n_rep = generator.hybrid_sd(clean, min_cv=0.05)
    mean = float(np.mean(clean))
    target = pd.to_datetime(date_code, format="%y%j")
    mask = result.growth["TRNO"].eq(plot) & pd.to_datetime(result.growth["DATE"]).eq(target)
    if int(mask.sum()) != 1:
        raise AssertionError((result.season_id, plot, date_code, variable, int(mask.sum())))
    token = VAR_MAP[variable]
    factor = generator.FACTOR if token in {"LWAD", "SWAD"} else 1.0
    result.growth.loc[mask, token] = mean * factor
    result.growth.loc[mask, f"{token}_sd"] = sd * factor
    result.growth.loc[mask, f"{token}_sd_source"] = method
    result.growth.loc[mask, f"{token}_n_rep"] = n_rep
    return {
        "season": result.season_id,
        "plot": plot,
        "date": date_code,
        "variable": token,
        "value": mean * factor,
        "raw_sd": sd * factor,
        "sd_method": method,
        "n_rep": n_rep,
    }


def _refresh_filea(result) -> None:
    for index, row in result.filea.iterrows():
        plot = int(row["TRNO"])
        growth = result.growth.loc[result.growth["TRNO"].eq(plot)].sort_values("DATE")
        lai = growth.loc[growth["LAID"].notna()]
        leaf = growth.loc[growth["LWAD"].notna()]
        stem = growth.loc[growth["SWAD"].notna()]
        if not lai.empty:
            max_row = lai.loc[lai["LAID"].idxmax()]
            result.filea.loc[index, ["LAIX", "LAIX_sd", "LAIX_sd_source", "LAIX_n_rep"]] = [
                max_row["LAID"], max_row["LAID_sd"], max_row["LAID_sd_source"], max_row["LAID_n_rep"]
            ]
        if not leaf.empty:
            last = leaf.iloc[-1]
            result.filea.loc[index, ["LWAM", "LWAM_sd", "LWAM_sd_source", "LWAM_n_rep"]] = [
                last["LWAD"], last["LWAD_sd"], last["LWAD_sd_source"], last["LWAD_n_rep"]
            ]
        if not stem.empty:
            last = stem.iloc[-1]
            result.filea.loc[index, ["SWAM", "SWAM_sd", "SWAM_sd_source", "SWAM_n_rep"]] = [
                last["SWAD"], last["SWAD_sd"], last["SWAD_sd_source"], last["SWAD_n_rep"]
            ]


def _apply_removals(result) -> list[dict]:
    raw25 = _raw_25() if result.season_id == "25SP" else None
    audits: list[dict] = []
    for season, plot, source_date, target, rep_id, channel in REMOVALS:
        if season != result.season_id:
            continue
        if season == "25SP" and plot not in INCLUDED25:
            continue
        if season == "25SP":
            group = raw25.loc[raw25["小区号"].eq(plot) & raw25["_date"].eq(source_date)].copy()
            date_code = source_date
        else:
            group = _raw_26(source_date)
            group = group.loc[group["_plot"].eq(plot)].copy()
            date_code = SHEET26[source_date]
        keep = group["_rep"].ne(rep_id)
        if int((~keep).sum()) != 1:
            raise AssertionError((season, plot, source_date, rep_id, int((~keep).sum())))
        variables = _variables(target)
        if target == "plant":
            variables = [
                variable for variable in variables
                if _source_column(season, source_date, variable) in group.columns
            ]
        for variable in variables:
            column = _source_column(season, source_date, variable)
            audit = _set_growth_value(result, plot, date_code, variable, group.loc[keep, column])
            audit.update({"source_date": source_date, "excluded_rep": rep_id, "channel": channel})
            audits.append(audit)
    _refresh_filea(result)
    source_workbook = (
        "2025春产量数据集.xlsx;2025春作物生长指标集.xlsx"
        if result.season_id == "25SP"
        else "2026春产量集.xlsx;2026春生长指标集.xlsx;2026春品质指标集.xlsx"
    )
    result.observation_uncertainty = generator.build_observation_uncertainty(
        result.season_id, result.excode, result.filea, result.growth, result.harvest,
        source_workbook=source_workbook,
    )
    changed = {(row["plot"], row["date"], row["variable"]): row for row in audits}
    for key, audit in changed.items():
        plot, date_code, variable = key
        mask = (
            result.observation_uncertainty["trno"].eq(plot)
            & result.observation_uncertainty["date"].astype(str).eq(date_code)
            & result.observation_uncertainty["variable"].eq(variable)
        )
        if int(mask.sum()) != 1:
            raise AssertionError((key, int(mask.sum())))
        result.observation_uncertainty.loc[mask, "quality_flag"] = "repfilter_v2_20260819"
    return audits


def _refresh_manifest(bundle: Path, parent: Path, result, audit_count: int) -> None:
    manifest_path = bundle / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_id"] = bundle.name
    manifest["derived_from_bundle"] = parent.name
    manifest["derived_from_manifest_sha256"] = sha256(parent / "input_manifest.json")
    manifest["source_workbooks"] = manifest.get("source_workbooks", {})
    manifest["source_workbooks"]["trial_observations"] = {
        str(Path(path).resolve().relative_to(ROOT.resolve())): digest
        for path, digest in result.source_files.items()
    }
    common = {
        f"{result.excode}.TMA", f"{result.excode}.TMT",
        "observation_uncertainty.csv", "fruit_quality_match_audit.csv",
        "FileA_values.csv", "FileT_values.csv", "generator_log.json",
        "trial_generator_log.json", "SOIL.SOL",
    }
    if (bundle / "treatment_exclusion_audit.csv").is_file():
        common.add("treatment_exclusion_audit.csv")

    def update_records(value):
        if isinstance(value, dict):
            name = value.get("name")
            if name in common and (bundle / name).is_file():
                value["sha256"] = sha256(bundle / name)
                value["bytes"] = (bundle / name).stat().st_size
                value["generated_by"] = "tools/experiments/apply_repfilter_v1_20260818.py"
                value["generator_sha256"] = sha256(Path(__file__))
            for child in value.values():
                update_records(child)
        elif isinstance(value, list):
            for child in value:
                update_records(child)

    update_records(manifest)
    manifest["data_corrections"] = {
        "correction_id": "repfilter_measuredmoisture_v2_20260819",
        "repfilter_cells": audit_count,
        "uncertainty_rule": "remaining replicates with minimum CV 5%",
        "fruit_moisture": "nearest plot-level measured moisture by harvest date",
        "filea_filet_sync": "terminal FileA regenerated from corrected FileT states",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build(parent: Path, target: Path, result) -> dict:
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(parent, target)
    audits = _apply_removals(result)
    result.qa_metrics.update({
        "fruit_moisture_contract": "measured_nearest_by_plot_date",
        "dmfr_min": float(result.fruit_quality_match_audit["dmfr"].min()),
        "dmfr_max": float(result.fruit_quality_match_audit["dmfr"].max()),
        "repfilter_cells": len(audits),
        "repfilter_min_cv": 0.05,
    })
    generator.write_season_outputs(result, target, sha256(Path(generator.__file__)))
    log_path = target / "generator_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    log["repfilter_v2_20260819"] = {
        "approved_exclusions": len([row for row in REMOVALS if row[0] == result.season_id]),
        "updated_cells": len(audits),
        "audit": audits,
        "uncertainty_rule": "hybrid_sd(min_cv=0.05)",
    }
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(log_path, target / "trial_generator_log.json")
    _refresh_manifest(target, parent, result, len(audits))
    return {
        "bundle": target.name,
        "updated_cells": len(audits),
        "dmfr_min": result.qa_metrics["dmfr_min"],
        "dmfr_max": result.qa_metrics["dmfr_max"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run == args.apply:
        parser.error("choose exactly one of --dry-run or --apply")
    results = [
        (BASE25, NEW25, generator.load_2025_spring(REF_ROOT)),
        (BASE26, NEW26, generator.load_2026_spring(REF_ROOT)),
    ]
    if args.dry_run:
        for _, target, result in results:
            audits = _apply_removals(result)
            print(json.dumps({
                "bundle": target.name,
                "updated_cells": len(audits),
                "dmfr_min": float(result.fruit_quality_match_audit["dmfr"].min()),
                "dmfr_max": float(result.fruit_quality_match_audit["dmfr"].max()),
            }, ensure_ascii=True))
        return 0
    receipts = [_build(parent, target, result) for parent, target, result in results]
    print(json.dumps(receipts, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
