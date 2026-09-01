#!/usr/bin/env python3
"""Scale 26SP harvest observations by 0.90 across FileT, TMT, and observation_uncertainty.csv consistently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Clean pristine reference
ARCHIVE_BUNDLE = PROJECT_ROOT / "data/user/experiments/_archive_20260808/xxql2601_actual_trial_calibration_v2_20260726"
BASE_FILE_T = ARCHIVE_BUNDLE / "FileT_values.csv"
BASE_UNC = ARCHIVE_BUNDLE / "observation_uncertainty.csv"


def update_bundle(bundle_dir: Path) -> None:
    file_t = bundle_dir / "FileT_values.csv"
    file_tmt = bundle_dir / "XXQL2601.TMT"
    file_unc = bundle_dir / "observation_uncertainty.csv"

    # 1. Update FileT_values.csv from pristine base
    df_t = pd.read_csv(BASE_FILE_T)
    harvest_cols = [c for c in ["HFPOW", "CHFPW", "HPODW", "CHPDT"] if c in df_t.columns]
    for col in harvest_cols:
        df_t[col] = df_t[col].apply(lambda x: x * 0.90 if pd.notna(x) else x)
    df_t.to_csv(file_t, index=False)

    # 2. Update XXQL2601.TMT
    lines = [
        "*EXP.DATA (T): 2026 SPRING EGGPLANT; TRNO=PLOT NUMBER",
        "",
        "! Fresh yield = mean of 小区产量; SD = independent replicate 产量.",
        "! Growth data merged from 4 sheets (0502/0629/0717/0602); sheet name used as fallback date for 0629/0602.",
        "! Fruit DM fraction = 1 - measured fruit moisture fraction (2026春品质指标集.半果含水率).",
        "! Each harvest uses the nearest plot-level moisture measurement date (no max interval).",
        "! Scaled by 0.90 per user directive on 2026-08-29.",
        "",
        "@TRNO   DATE  L#SD  LAID  L#PA  LWAD  RWAD  SWAD  M#AD  SLAD  CHTD  CWID  CNAM  SNAM  LNAM HFPOW CHFPW HPODW CHPDT PDMCD",
    ]

    for _, row in df_t.iterrows():
        trno = int(row["TRNO"])
        d_str = str(row["DATE"])
        dt = pd.to_datetime(d_str)
        yydoy = f"{dt.year % 100:02d}{dt.dayofyear:03d}"

        def f_str(val: Any, width: int, decimals: int = 0) -> str:
            if pd.isna(val):
                return f"{'-99':>{width}}"
            if decimals > 0:
                return f"{float(val):>{width}.{decimals}f}"
            return f"{round(float(val)):>{width}}"

        laid_str = f_str(row.get("LAID"), 5, 3)
        lwad_str = f_str(row.get("LWAD"), 5, 0)
        swad_str = f_str(row.get("SWAD"), 5, 0)
        chtd_str = f_str(row.get("CHTD"), 5, 3)

        hfpow_str = f_str(row.get("HFPOW"), 5, 0)
        chfpw_str = f_str(row.get("CHFPW"), 5, 0)
        hpodw_str = f_str(row.get("HPODW"), 5, 0)
        chpdt_str = f_str(row.get("CHPDT"), 5, 0)

        line = (
            f"{trno:>6} {yydoy}   -99 {laid_str}   -99 {lwad_str}   -99 {swad_str}   -99   -99 "
            f"{chtd_str}   -99   -99   -99   -99 {hfpow_str} {chfpw_str} {hpodw_str} {chpdt_str}   -99"
        )
        lines.append(line)

    file_tmt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 3. Update observation_uncertainty.csv
    if file_unc.is_file():
        df_u = pd.read_csv(file_unc)
        h_mask = df_u["variable"].isin(["CHFPW", "HFPOW", "CHPDT", "HPODW"])
        # Match with df_t values directly to ensure zero disagreement
        for idx, r in df_u[h_mask].iterrows():
            t = int(r["trno"])
            d_doy = int(r["date"])
            var = str(r["variable"])
            # Find in df_t
            sub = df_t[df_t["TRNO"] == t]
            for _, tr in sub.iterrows():
                dt = pd.to_datetime(tr["DATE"])
                if int(f"{dt.year % 100:02d}{dt.dayofyear:03d}") == d_doy:
                    if var in tr and pd.notna(tr[var]):
                        df_u.at[idx, "value"] = float(tr[var])
                        if pd.notna(df_u.at[idx, "raw_sd"]):
                            df_u.at[idx, "raw_sd"] = float(df_u.at[idx, "raw_sd"]) * 0.90
        df_u.to_csv(file_unc, index=False)
        print(f"Updated {file_t.name}, {file_tmt.name}, and {file_unc.name} in {bundle_dir.name}")


def main() -> None:
    for bundle in PROJECT_ROOT.glob("data/user/experiments/*2601*"):
        if any(ign in str(bundle) for ign in ["_archive", "failed", "backup", "macOS"]):
            continue
        update_bundle(bundle)

    # Clean update _seasons/26SP and workspace
    s26_t = PROJECT_ROOT / "_seasons" / "26SP" / "XXQL2601.TMT"
    if s26_t.is_file():
        update_bundle(PROJECT_ROOT / "_seasons" / "26SP")

    ws_t = PROJECT_ROOT / "workspace" / "XXQL2601.TMT"
    if ws_t.is_file():
        update_bundle(PROJECT_ROOT / "workspace")


if __name__ == "__main__":
    main()
