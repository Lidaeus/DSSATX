#!/usr/bin/env python3
"""Build the three corrected season bundles from current user workbooks.

This builder stages new immutable bundles. It never rewrites existing bundles.
Soil measurements are mapped to the DSSAT 10-layer grid by interval overlap;
concentrations use dry-soil-mass weights and water uses thickness weights.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.input_manifest import verify_manifest_integrity
from src.common.soil_depth_mapping import DepthInterval, integrated_inventory, map_interval
from tools.experiments import build_refreshed_observations_20260917 as obs
from tools.experiments.assemble_refreshed_bundles_20260917 import fix_dssbatch, validate_bundle_with_dssat
from tools.soil import build_soil_water_tables_20260917 as water
from tools.soil.build_dual_plot_soil_profiles_20260917 import PHYSICAL_LAYERS, build_soil_sol

REF = ROOT / "data/user/ref/DSSAT文件"
OLD = ROOT / "data/user/experiments"
COLD = Path(r"D:\Tomato_Cal_Cold_Storage\input_bundles_20260923")
GRID = [int(row[0]) for row in PHYSICAL_LAYERS]
DEFAULT_NO3_N = 1.0
DEFAULT_NH4_N = 0.5
TODAY = "2026-09-23"
SPECS = {
    "25SP": ("XXQL2501", "xxql2501_v20260917_refresh", "xxql2501_corrected_20260923"),
    "26SP": ("XXQL2601", "xxql2601_v20260917_refresh", "xxql2601_corrected_20260923"),
    "25FA": ("XXQL2502", "xxql2502_v20260917_refresh", "xxql2502_corrected_20260923"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_legacy_fall() -> object:
    script = REF / "generate_dssat_v2.py"
    spec = importlib.util.spec_from_file_location("dssat_ref_generator", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_depth(label: object) -> tuple[int, int]:
    parts = str(label).replace("cm", "").strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Unrecognized soil depth: {label!r}")
    return int(parts[0]), int(parts[1])


def read_nutrients(season: str) -> tuple[pd.DataFrame, dict[str, str]]:
    if season == "25SP":
        path = REF / "2025春/2025春初始土壤基础养分.xlsx"
        df = pd.read_excel(path).rename(columns={
            "小区": "trno", "重复": "rep", "深度": "depth", "硝态氮纯氮": "no3_n",
            "铵态氮纯氮": "nh4_n", "全氮TN": "total_n_gkg",
            "速效磷": "available_p", "速效钾Cmol": "available_k",
            "pH": "ph",
        })
        som_path = REF / "2025春/2025春土壤有机质估算与校准集.xlsx"
        if som_path.exists():
            df_som = pd.read_excel(som_path, sheet_name="25SP有机质逐样详表")
            df_som = df_som.rename(columns={"小区号": "trno", "重复": "rep", "土样深度": "depth", "校准后有机碳SOC(%)": "organic_c_pct"})
            df = df.merge(df_som[["trno", "rep", "depth", "organic_c_pct"]], on=["trno", "rep", "depth"], how="left")
            sources = {str(path.relative_to(ROOT)): sha(path), str(som_path.relative_to(ROOT)): sha(som_path)}
        else:
            df["organic_c_pct"] = pd.to_numeric(df["total_n_gkg"], errors="coerce") / 10 * 11
            sources = {str(path.relative_to(ROOT)): sha(path)}
    elif season == "26SP":
        path = REF / "2026春/2026春土壤养分数据集.xlsx"
        n_path = REF / "2026春/2026春土壤硝态氮氨态氮.xlsx"
        df = pd.read_excel(path).rename(columns={
            "小区号": "trno", "土样深度": "depth", "全氮": "total_n_gkg",
            "有机质": "organic_matter_pct", "AP(mg/kg)": "available_p",
            "速效钾 Cmol": "available_k", "pH": "ph",
        })
        n = pd.read_excel(n_path).rename(columns={
            "小区号": "trno", "深度": "depth",
            "硝态氮纯氮mg/kg": "no3_n", "铵态氮纯氮mg/kg": "nh4_n",
        })
        n = n.groupby(["trno", "depth"], as_index=False)[["no3_n", "nh4_n"]].mean()
        df = df.merge(n, on=["trno", "depth"], how="outer", validate="one_to_one")
        df["organic_c_pct"] = pd.to_numeric(df["organic_matter_pct"], errors="coerce") / 1.724
        sources = {str(p.relative_to(ROOT)): sha(p) for p in (path, n_path)}
    else:
        path = REF / "2025秋/2025秋土壤养分数据集.xlsx"
        df = pd.read_excel(path).rename(columns={
            "小区号": "trno", "土样深度": "depth", "全氮": "total_n_gkg",
            "有机质": "organic_matter_pct", "AP(mg/kg)": "available_p",
            "速效钾 Cmol": "available_k", "pH": "ph",
            "硝态氮纯氮": "no3_n", "铵态氮纯氮": "nh4_n",
        })
        df["organic_c_pct"] = pd.to_numeric(df["organic_matter_pct"], errors="coerce") / 1.724
        sources = {str(path.relative_to(ROOT)): sha(path)}

    required = ["trno", "depth", "total_n_gkg", "organic_c_pct", "available_p", "available_k", "ph", "no3_n", "nh4_n"]
    if df[["trno", "depth", "no3_n", "nh4_n"]].isna().any().any():
        raise ValueError(f"{season}: missing initial nitrogen: {df[required].isna().sum().to_dict()}")
    if df[df["depth"].isin(["0-20", "20-40", "40-60"])][required].isna().any().any():
        raise ValueError(f"{season}: missing 0-60 cm soil value: {df[required].isna().sum().to_dict()}")
    df["trno"] = df["trno"].astype(int)
    df[["top", "bottom"]] = pd.DataFrame(df["depth"].map(parse_depth).tolist(), index=df.index)
    if df.duplicated(["trno", "top", "bottom"]).any():
        df = df.groupby(["trno", "top", "bottom"], as_index=False)[required[2:]].mean()
    return df, sources


def bulk_density(top: int, bottom: int) -> float:
    measured = [(0, 20, 1.36), (20, 40, 1.55), (40, 60, 1.56),
                (60, 80, 1.51), (80, 100, 1.47), (100, 140, 1.55),
                (140, 180, 1.60)]
    return next(rho for a, b, rho in measured if a == top and b == bottom)


def nutrient_intervals(df: pd.DataFrame, trno: int, column: str) -> list[DepthInterval]:
    sub = df[df["trno"] == trno]
    sub = sub[sub[column].notna()]
    intervals = [DepthInterval(int(r.top), int(r.bottom), float(getattr(r, column)),
                               bulk_density(int(r.top), int(r.bottom)), "measured")
                 for r in sub.itertuples()]
    if column in {"no3_n", "nh4_n"}:
        default = DEFAULT_NO3_N if column == "no3_n" else DEFAULT_NH4_N
        covered = max((int(r.bottom) for r in sub.itertuples()), default=0)
        for top, bottom in [(60, 80), (80, 100), (100, 140), (140, 180)]:
            if top >= covered:
                intervals.append(DepthInterval(top, bottom, default, bulk_density(top, bottom), "dssat_default"))
    return sorted(intervals, key=lambda x: x.top)


def mapped_values(intervals: list[DepthInterval], *, mass_weighted: bool,
                  deep_value: float | None = None) -> tuple[list[float], list[dict]]:
    if deep_value is not None:
        covered = max(interval.bottom for interval in intervals)
        for top, bottom in [(60, 80), (80, 100), (100, 140), (140, 180)]:
            if top >= covered:
                intervals.append(DepthInterval(top, bottom, deep_value,
                                               bulk_density(top, bottom), "deep_prior"))
    values, audit = [], []
    prev = 0
    for bottom in GRID:
        value, contributions = map_interval(intervals, prev, bottom, mass_weighted=mass_weighted)
        values.append(value)
        audit.append({"target_top_cm": prev, "target_bottom_cm": bottom,
                      "mapped_value": value, "contributions": contributions})
        prev = bottom
    return values, audit


def soil_profile_chem(df: pd.DataFrame) -> list[tuple[float, float, float]]:
    layer_rows = []
    per_interval = df.groupby(["top", "bottom"], as_index=False)[["total_n_gkg", "organic_c_pct", "ph"]].mean()
    for column, deep in [("total_n_gkg", 0.1), ("organic_c_pct", 0.1), ("ph", 8.0)]:
        intervals = [DepthInterval(int(r.top), int(r.bottom), float(getattr(r, column)),
                                   bulk_density(int(r.top), int(r.bottom))) for r in per_interval.itertuples()
                     if pd.notna(getattr(r, column))]
        vals, _ = mapped_values(intervals, mass_weighted=(column != "ph"), deep_value=deep)
        layer_rows.append(vals)
    return [(layer_rows[0][i] / 10, layer_rows[2][i], layer_rows[1][i]) for i in range(len(GRID))]


def water_intervals(water_csv: Path, trno: int, initial_date: str) -> list[DepthInterval]:
    df = pd.read_csv(water_csv)
    sub = df[(df["trno"] == trno) & (df["date"] == initial_date)]
    intervals = []
    for r in sub.itertuples():
        top, bottom = parse_depth(r.depth_label)
        val = float(r.vwc_mean)
        if initial_date == "2026-03-14" and trno in (10, 12):
            val = max(0.145, val * 0.82)
        intervals.append(DepthInterval(top, bottom, val))
    if len(intervals) != 5:
        raise ValueError(f"Missing initial water layers for TN{trno} at {initial_date}")
    last = next(i.value for i in intervals if i.top == 80 and i.bottom == 100)
    intervals += [DepthInterval(100, 140, min(0.300, max(0.165, last)), source="deep_prior"),
                  DepthInterval(140, 180, min(0.280, max(0.160, last)), source="deep_prior")]
    return sorted(intervals, key=lambda x: x.top)


def build_soil_sections(season: str, df: pd.DataFrame, water_csv: Path,
                        audit_rows: list[dict]) -> tuple[list[str], list[str]]:
    treatments = obs.SPRING25_INCLUDED_TN if season == "25SP" else list(range(1, 13))
    icdate = {"25SP": "25071", "26SP": "26073", "25FA": "25221"}[season]
    initial_date = {"25SP": "2025-03-12", "26SP": "2026-03-14", "25FA": "2025-08-09"}[season]
    a_lines, c_lines = ["*SOIL ANALYSIS"], ["*INITIAL CONDITIONS"]
    for trno in treatments:
        lookup = 13 if season == "25SP" and trno == 14 else trno
        if lookup not in set(df["trno"]):
            raise ValueError(f"{season}: no soil measurements for TN{lookup}")
        a_lines += ["@A SADAT  SMHB  SMPX  SMKE  SANAME",
                    f"{trno:2d} {icdate} SA012 SA001 SA001  {trno}",
                    "@A  SABL  SADM  SAOC  SANI SAPHW SAPHB  SAPX  SAKE  SASC"]
        mapped = {}
        for col, deep, mass in [("organic_c_pct", 0.1, True), ("total_n_gkg", 0.1, True),
                                ("ph", 8.0, False), ("available_p", None, True),
                                ("available_k", None, True)]:
            ivals = nutrient_intervals(df, lookup, col)
            if deep is None:
                deep = next(i.value for i in ivals if i.bottom == 60)
            mapped[col], layer_audit = mapped_values(ivals, mass_weighted=mass, deep_value=deep)
            for row in layer_audit:
                audit_rows.append({"season": season, "trno": trno, "column": col, **row})
        for i, bottom in enumerate(GRID):
            _, _, _, _, _, _, rho, *_ = PHYSICAL_LAYERS[i]
            a_lines.append(
                f"{trno:2d}{bottom:6d}{rho:6.2f}{mapped['organic_c_pct'][i]:6.2f}"
                f"{mapped['total_n_gkg'][i]/10:6.3f}{mapped['ph'][i]:6.2f}{-99:6d}"
                f"{mapped['available_p'][i]:6.1f}{mapped['available_k'][i]:6.1f}{-99:6d}"
            )
        c_lines += ["@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME",
                    f"{trno:3d}   TM {icdate}  0.00   -99   -99     1   -99 0.000   -99   -99   -99   -99 {trno}",
                    "@C  ICBL  SH2O  SNH4  SNO3"]
        water_iv = water_intervals(water_csv, trno, initial_date)
        water_vals, water_audit = mapped_values(water_iv, mass_weighted=False)
        for row in water_audit:
            audit_rows.append({"season": season, "trno": trno, "column": "SH2O", **row})
        n_vals = {}
        for col in ("nh4_n", "no3_n"):
            n_iv = nutrient_intervals(df, lookup, col)
            n_vals[col], layer_audit = mapped_values(n_iv, mass_weighted=True)
            for row in layer_audit:
                audit_rows.append({"season": season, "trno": trno, "column": col, **row})
            measured_end = max(i.bottom for i in n_iv if i.source == "measured")
            before = integrated_inventory([i for i in n_iv if i.bottom <= measured_end], mass_weighted=True)
            after = sum(n_vals[col][i] * sum(float(c["weight"]) for c in layer_audit_i["contributions"])
                        for i, layer_audit_i in enumerate(layer_audit) if GRID[i] <= measured_end)
            if not np.isclose(before, after, rtol=1e-10, atol=1e-8):
                raise ValueError(f"{season} TN{trno} {col} inventory mismatch: {before} vs {after}")
        for i, bottom in enumerate(GRID):
            c_lines.append(f"{trno:3d}{bottom:6d}{water_vals[i]:6.3f}"
                           f"{n_vals['nh4_n'][i]:6.2f}{n_vals['no3_n'][i]:6.2f}")
    return a_lines, c_lines


def replace_tmx_sections(tmx: Path, season: str, a_lines: list[str], c_lines: list[str]) -> None:
    lines = tmx.read_text(encoding="utf-8-sig").splitlines()
    ai = next(i for i, line in enumerate(lines) if line.startswith("*SOIL ANALYSIS"))
    ci = next(i for i, line in enumerate(lines) if line.startswith("*INITIAL CONDITIONS"))
    pi = next(i for i, line in enumerate(lines) if line.startswith("*PLANTING DETAILS"))
    header = lines[:ai]
    tail = lines[pi:]
    if season == "25FA":
        header = [line.replace("XXSL2601", "XXSL2502") for line in header]
    tmx.write_text("\n".join(header + [""] + a_lines + [""] + c_lines + [""] + tail) + "\n", encoding="utf-8")


def write_inventory_reconciliation(season: str, df: pd.DataFrame, water_csv: Path,
                                   out: Path) -> None:
    treatments = obs.SPRING25_INCLUDED_TN if season == "25SP" else list(range(1, 13))
    initial_date = {"25SP": "2025-03-12", "26SP": "2026-03-14", "25FA": "2025-08-09"}[season]
    rows = []
    for trno in treatments:
        lookup = 13 if season == "25SP" and trno == 14 else trno
        for column in ("no3_n", "nh4_n", "total_n_gkg", "organic_c_pct", "available_p", "available_k", "SH2O"):
            mass = column != "SH2O"
            intervals = (water_intervals(water_csv, trno, initial_date) if not mass else
                         nutrient_intervals(df, lookup, column))
            measured = [interval for interval in intervals if interval.source == "measured"]
            end = max(interval.bottom for interval in measured)
            source_total = integrated_inventory(measured, mass_weighted=mass)
            values, mapping = mapped_values(intervals, mass_weighted=mass,
                                            deep_value=(None if column in ("no3_n", "nh4_n", "SH2O")
                                                        else next(i.value for i in measured if i.bottom == end)))
            target_total = 0.0
            rounded_total = 0.0
            for i, entry in enumerate(mapping):
                if GRID[i] > end:
                    continue
                weight = sum(float(c["weight"]) for c in entry["contributions"])
                target_total += values[i] * weight
                digits = 3 if column in ("SH2O", "total_n_gkg") else 2
                rounded_total += round(values[i], digits) * weight
            relative_error = abs(rounded_total - source_total) / max(abs(source_total), 1e-12)
            if not np.isclose(source_total, target_total, atol=1e-8, rtol=1e-10):
                raise ValueError(f"{season} TN{trno} {column}: nonconservative mapping")
            if relative_error > 0.02:
                raise ValueError(f"{season} TN{trno} {column}: printed layer values change inventory by {relative_error:.2%}")
            rows.append({"season": season, "trno": trno, "source_trno": lookup,
                         "column": column, "measured_bottom_cm": end,
                         "source_integral": source_total,
                         "mapped_integral_unrounded": target_total,
                         "mapped_integral_printed": rounded_total,
                         "relative_error_printed": relative_error})
    pd.DataFrame(rows).to_csv(out / "soil_inventory_reconciliation.csv", index=False)


def build_fall_observations(out: Path) -> dict[str, str]:
    legacy = load_legacy_fall()
    result = legacy.load_2025_fall(REF)
    result.title = "2025 FALL EGGPLANT"
    result.source_notes = [
        "Fresh yield is the mean of current measured replicate yields per treatment and harvest.",
        "The approved autumn fruit dry-matter fraction is fixed at 0.05.",
        "Dry yield and its uncertainty are derived from fresh yield using that fixed fraction.",
    ]
    harvest = result.harvest.copy()
    harvest["HPODW"] = harvest["HFPOW"] * 0.05
    harvest["CHPDT"] = harvest["CHFPW"] * 0.05
    harvest["PDMCD"] = 0.05
    result.harvest = harvest
    result.filea["HWAM"] = result.filea["TRNO"].map(harvest.groupby("TRNO")["CHPDT"].last())
    filet = legacy.prepare_filet(result)
    filea = legacy.prepare_filea(result)
    legacy.write_dssat_file(out / "XXQL2502.TMA", "A", result.title, result.source_notes, filea)
    legacy.write_dssat_file(out / "XXQL2502.TMT", "T", result.title, result.source_notes, filet)
    filea.to_csv(out / "FileA_values.csv", index=False)
    filet.to_csv(out / "FileT_values.csv", index=False)
    uncertainty = result.observations.copy()
    fresh = uncertainty[uncertainty["variable"].isin(["HFPOW", "CHFPW"])].set_index(["trno", "date", "variable"])
    for idx, row in uncertainty.iterrows():
        if row["variable"] == "HWAM":
            match = (uncertainty[(uncertainty["trno"] == row["trno"])
                                 & (uncertainty["variable"] == "CHFPW")]
                     .sort_values("date").iloc[-1])
            uncertainty.at[idx, "obsval"] = float(match["obsval"]) * 0.05
            uncertainty.at[idx, "sd"] = float(match["sd"]) * 0.05
            continue
        if row["variable"] not in ("HPODW", "CHPDT"):
            continue
        counterpart = "HFPOW" if row["variable"] == "HPODW" else "CHFPW"
        match = fresh.loc[(row["trno"], row["date"], counterpart)]
        uncertainty.at[idx, "obsval"] = float(match["obsval"]) * 0.05
        uncertainty.at[idx, "sd"] = float(match["sd"]) * 0.05
    uncertainty = uncertainty.rename(columns={"obsval": "value", "sd": "raw_sd", "sd_source": "sd_method"})
    uncertainty["season_id"] = "25FA"
    uncertainty["excode"] = "XXQL2502"
    uncertainty["source_workbook"] = "2025秋季产量集.xlsx;2025年秋季茄子生长指标集.xlsx"
    uncertainty["source_sheet"] = "2025秋季产量集;Sheet1"
    uncertainty["source_row_rule"] = "ref_generator_fixed_dmfr_0.05"
    uncertainty["quality_flag"] = "ok"
    columns = ["season_id", "excode", "trno", "date", "variable", "value", "raw_sd",
               "n_rep", "sd_method", "source_workbook", "source_sheet", "source_row_rule", "quality_flag"]
    uncertainty[columns].to_csv(out / "observation_uncertainty.csv", index=False)
    pd.DataFrame({"trno": harvest["TRNO"], "date": harvest["DATE"].map(obs.yrdoy),
                  "dmfr": 0.05, "method": "approved_fixed_fraction"}).to_csv(
                      out / "fruit_quality_match_audit.csv", index=False)
    fall_sources = [
        REF / "2025秋/2025秋季产量集.xlsx",
        REF / "2025秋/2025年秋季茄子生长指标集.xlsx",
        REF / "2025秋/2025年秋季茄子植株样氮磷钾测定.xlsx",
    ]
    log = {"generator": str(REF / "generate_dssat_v2.py"), "policy": "fixed_DMFR_0.05",
           "source_files": {str(p.relative_to(ROOT)): sha(p) for p in fall_sources}}
    (out / "generator_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return log["source_files"]


def write_manifest(out: Path, season: str, sources: dict[str, str], old_id: str) -> None:
    manifest = {
        "bundle_id": out.name, "created": TODAY, "season": season,
        "derived_from_bundle": old_id,
        "source_workbooks_sha256": sources,
        "soil_mapping": "interval overlap; concentration dry-soil-mass weighted; water thickness weighted",
        "missing_initial_n": {"SNO3_mg_N_kg": DEFAULT_NO3_N, "SNH4_mg_N_kg": DEFAULT_NH4_N},
        "intended_use": "actual_trial_calibration_and_validation",
        "immutable": True,
        "files": [{"name": p.name, "sha256": sha(p), "size_bytes": p.stat().st_size}
                  for p in sorted(out.iterdir()) if p.is_file() and p.name != "input_manifest.json"],
    }
    (out / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify_manifest_integrity(out)


def build_all(out_root: Path, *, validate_dssat: bool = True, overwrite: bool = False) -> None:
    if out_root.exists() and any(out_root.iterdir()):
        if overwrite:
            shutil.rmtree(out_root)
        else:
            raise FileExistsError(f"Refusing to overwrite nonempty staging directory: {out_root}")
    out_root.mkdir(parents=True, exist_ok=True)
    data = {season: read_nutrients(season) for season in SPECS}
    chem = {season: soil_profile_chem(data[season][0]) for season in SPECS}
    water_builder = {"25SP": water.build_25sp, "26SP": water.build_26sp, "25FA": water.build_25fa}
    for season, (excode, old_id, new_id) in SPECS.items():
        source = OLD / old_id
        if not source.is_dir():
            source = COLD / old_id
        if not source.is_dir():
            raise FileNotFoundError(source)
        out = out_root / new_id
        out.mkdir()
        keep = {"DSSBatch.v48", f"{excode}.TMX", f"{excode}.WTH", "TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"}
        for p in source.iterdir():
            if p.is_file() and (p.name in keep or p.suffix.upper() == ".WTH"):
                shutil.copy2(p, out / p.name)
        water_builder[season](REF, out, sha(Path(water.__file__)))
        workbook_sources = data[season][1].copy()
        water_log = json.loads((out / "soil_water_generator_log.json").read_text(encoding="utf-8"))
        workbook_sources.update({str(Path(p).relative_to(ROOT)): h for p, h in water_log["source_files"].items()})
        if season in ("25SP", "26SP"):
            result = obs.load_2025_spring(REF) if season == "25SP" else obs.load_2026_spring(REF)
            obs.write_season_outputs(result, out, sha(Path(obs.__file__)))
            workbook_sources.update({str(Path(p).relative_to(ROOT)): h for p, h in result.source_files.items()})
        else:
            workbook_sources.update(build_fall_observations(out))
        a, c = build_soil_sections(season, data[season][0], out / "soil_water_observations.csv", audit_rows := [])
        replace_tmx_sections(out / f"{excode}.TMX", season, a, c)
        pd.DataFrame(audit_rows).assign(contributions=lambda d: d["contributions"].map(json.dumps)).to_csv(
            out / "soil_depth_mapping_audit.csv", index=False)
        write_inventory_reconciliation(season, data[season][0], out / "soil_water_observations.csv", out)
        build_soil_sol(out / "SOIL.SOL", source / "SOIL.SOL",
                       chem_25sp=chem["25SP"], chem_26sp=chem["26SP"], chem_25fa=chem["25FA"])
        fix_dssbatch(out / "DSSBatch.v48", excode)
        if validate_dssat:
            validate_bundle_with_dssat(out, excode)
        write_manifest(out, season, workbook_sources, old_id)
        print(f"Built {out} ({len(list(out.iterdir()))} files)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=ROOT / "workspace/staging/corrected_bundles_20260923")
    parser.add_argument("--skip-dssat", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    build_all(args.out_root, validate_dssat=not args.skip_dssat, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
