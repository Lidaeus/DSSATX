#!/usr/bin/env python3
"""Apply user data adjustments for 25SP soil nitrate and 26SP harvest observations.

Adjustments:
1. 25SP Soil Nitrate in all XXQL2501.TMX files:
   - Trno3 IC data replaced by Trno5 IC data
   - Trno4 IC data replaced by Trno3 IC data
   - Trno5 IC data replaced by Trno4 IC data
   - Trno9 layer 40 cm SNO3: 23.4 -> 13.4
   - Trno12 layer 20 cm SNO3: 39.6 -> 29.6
   - Trno12 layer 40 cm SNO3: 33.2 -> 17.2
   - Trno13 layer 20 cm SNO3: 42.3 -> 33.3
2. 26SP Harvest Data in all XXQL2601 bundles:
   - Multiply harvest observation columns (HFPOW, CHFPW, HPODW, CHPDT) by 0.90 in FileT_values.csv and XXQL2601.TMT.
"""

from __future__ import annotations

import re
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Standard 25SP IC table layers (from user specification)
BASE_IC_DATA = {
    2: [
        ("20", ".216", "1.5", "24.9"),
        ("40", ".224", "1", "15.3"),
        ("60", ".239", "1.6", "8.7"),
        ("80", ".23", ".5", "1"),
        ("100", ".239", ".5", "1"),
    ],
    3: [
        # Trno3 becomes Trno5 data
        ("20", ".202", "1.4", "32.6"),
        ("40", ".26", ".7", "13.8"),
        ("60", ".281", ".5", "4.8"),
        ("80", ".299", ".5", "1"),
        ("100", ".255", ".5", "1"),
    ],
    4: [
        # Trno4 becomes old Trno3 data
        ("20", ".189", "2.4", "28.1"),
        ("40", ".269", "1.1", "14.9"),
        ("60", ".288", ".8", "8.7"),
        ("80", ".306", ".5", "1"),
        ("100", ".208", ".5", "1"),
    ],
    5: [
        # Trno5 becomes old Trno4 data
        ("20", ".17", "1.2", "18.4"),
        ("40", ".249", ".9", "7.9"),
        ("60", ".321", ".7", "6.3"),
        ("80", ".3", ".5", "1"),
        ("100", ".231", ".5", "1"),
    ],
    6: [
        ("20", ".197", "1.1", "35.2"),
        ("40", ".253", "1.1", "11.4"),
        ("60", ".27", ".6", "4.5"),
        ("80", ".261", ".5", "1"),
        ("100", ".242", ".5", "1"),
    ],
    7: [
        ("20", ".224", "1.8", "43.5"),
        ("40", ".288", "1.2", "36.6"),
        ("60", ".321", "1.2", "14.8"),
        ("80", ".324", ".5", "1"),
        ("100", ".293", ".5", "1"),
    ],
    8: [
        ("20", ".219", "1.3", "41.7"),
        ("40", ".27", "2.9", "21.2"),
        ("60", ".345", ".7", "10.5"),
        ("80", ".301", ".5", "1"),
        ("100", ".284", ".5", "1"),
    ],
    9: [
        ("20", ".216", "3.4", "30.4"),
        ("40", ".248", "1.2", "13.4"),  # modified 23.4 -> 13.4
        ("60", ".297", "1.5", "6.6"),
        ("80", ".304", ".5", "1"),
        ("100", ".314", ".5", "1"),
    ],
    10: [
        ("20", ".216", "1.7", "30.6"),
        ("40", ".254", ".6", "17.7"),
        ("60", ".298", "1.6", "1.6"),
        ("80", ".317", ".5", "1"),
        ("100", ".333", ".5", "1"),
    ],
    11: [
        ("20", ".241", "1.7", "45.1"),
        ("40", ".262", ".6", "17.4"),
        ("60", ".317", "1", "1.8"),
        ("80", ".326", ".5", "1"),
        ("100", ".369", ".5", "1"),
    ],
    12: [
        ("20", ".216", "2.6", "29.6"),  # modified 39.6 -> 29.6
        ("40", ".268", "1.5", "17.2"),  # modified 33.2 -> 17.2
        ("60", ".315", ".6", "4.2"),
        ("80", ".336", ".5", "1"),
        ("100", ".346", ".5", "1"),
    ],
    13: [
        ("20", ".238", "1.6", "33.3"),  # modified 42.3 -> 33.3
        ("40", ".296", ".8", "11.2"),
        ("60", ".305", ".5", "3.4"),
        ("80", ".365", ".5", "1"),
        ("100", ".356", ".5", "1"),
    ],
    14: [
        ("20", ".28", ".6", "38.3"),
        ("40", ".313", ".8", "10.7"),
        ("60", ".315", ".5", "1.8"),
        ("80", ".358", ".5", "1"),
        ("100", ".392", ".5", "1"),
    ],
}


def build_ic_block() -> str:
    lines = ["*INITIAL CONDITIONS"]
    for trno in sorted(BASE_IC_DATA.keys()):
        lines.append("@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME")
        lines.append(f"{trno:>2}   -99 25069     1     0     1     1   -99   -99   -99   -99   -99   -99 {trno}")
        lines.append("@C  ICBL  SH2O  SNH4  SNO3")
        for icbl, sh2o, snh4, sno3 in BASE_IC_DATA[trno]:
            lines.append(f"{trno:>2}  {icbl:>4}  {sh2o:>4} {snh4:>5} {sno3:>5}")
    return "\n".join(lines)


def update_25sp_tmx_file(tmx_path: Path) -> bool:
    content = tmx_path.read_text(encoding="utf-8")
    if "*INITIAL CONDITIONS" not in content or "*PLANTING DETAILS" not in content:
        return False

    prefix = content.split("*INITIAL CONDITIONS")[0]
    suffix = content.split("*PLANTING DETAILS")[1]

    new_ic = build_ic_block()
    new_content = prefix + new_ic + "\n*PLANTING DETAILS" + suffix
    tmx_path.write_text(new_content, encoding="utf-8")
    return True


def apply_25sp_updates() -> list[Path]:
    updated = []
    for p in PROJECT_ROOT.glob("**/XXQL2501.TMX"):
        if any(ign in str(p) for ign in ["_archive", "failed", "backup", "macOS"]):
            continue
        if update_25sp_tmx_file(p):
            updated.append(p)
    return updated


def update_26sp_file_t(csv_path: Path) -> bool:
    df = pd.read_csv(csv_path)
    harvest_cols = [c for c in ["HFPOW", "CHFPW", "HPODW", "CHPDT"] if c in df.columns]
    if not harvest_cols:
        return False
    for col in harvest_cols:
        df[col] = df[col].apply(lambda x: x * 0.90 if pd.notna(x) else x)
    df.to_csv(csv_path, index=False)
    return True


def update_26sp_tmt_file(tmt_path: Path, csv_path: Path) -> bool:
    # Regenerate TMT cleanly from the updated FileT_values.csv
    df = pd.read_csv(csv_path)
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

    for _, row in df.iterrows():
        trno = int(row["TRNO"])
        d_str = str(row["DATE"])  # YYYY-MM-DD
        # convert date to DSSAT YYDOY format: e.g. 2026-05-02 -> 26122
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

    tmt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def apply_26sp_updates() -> list[Path]:
    updated = []
    for bundle in PROJECT_ROOT.glob("data/user/experiments/*2601*"):
        if any(ign in str(bundle) for ign in ["_archive", "failed", "backup", "macOS"]):
            continue
        file_t = bundle / "FileT_values.csv"
        file_tmt = bundle / "XXQL2601.TMT"
        if file_t.is_file():
            update_26sp_file_t(file_t)
            if file_tmt.is_file():
                update_26sp_tmt_file(file_tmt, file_t)
            updated.append(bundle)

    # Also update _seasons/26SP and workspace if present
    s26_t = PROJECT_ROOT / "_seasons" / "26SP" / "XXQL2601.TMT"
    if s26_t.is_file():
        ref_csv = PROJECT_ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828/FileT_values.csv"
        if ref_csv.is_file():
            update_26sp_tmt_file(s26_t, ref_csv)
            updated.append(s26_t)

    ws_t = PROJECT_ROOT / "workspace" / "XXQL2601.TMT"
    if ws_t.is_file():
        ref_csv = PROJECT_ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828/FileT_values.csv"
        if ref_csv.is_file():
            update_26sp_tmt_file(ws_t, ref_csv)
            updated.append(ws_t)

    return updated


def main() -> None:
    print("Applying 25SP soil nitrate updates across all XXQL2501.TMX files...")
    updated_25sp = apply_25sp_updates()
    for p in updated_25sp:
        print("  Updated 25SP TMX:", p.relative_to(PROJECT_ROOT))

    print("\nApplying 26SP harvest observation 90% scaling across 26SP bundles...")
    updated_26sp = apply_26sp_updates()
    for p in updated_26sp:
        print("  Updated 26SP bundle:", p.relative_to(PROJECT_ROOT))

    print("\nAll data adjustments successfully executed!")


if __name__ == "__main__":
    main()
