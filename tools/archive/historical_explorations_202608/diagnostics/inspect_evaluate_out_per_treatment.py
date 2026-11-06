#!/usr/bin/env python3
"""Inspect per-treatment observed vs simulated for 25SP and 26SP in deterministic replay.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DET_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v34_nitrogen_smoothed_200x6_20260829/best_member_125_two_season_deterministic_20260829"

for season in ["25SP", "26SP"]:
    s_dir = DET_DIR / "_seasons" / season
    # Read evaluate file or plantgro/harvest
    # Read Evaluate.OUT
    ev_file = s_dir / "Evaluate.OUT"
    if ev_file.exists():
        lines = ev_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        header = None
        rows = []
        for l in lines:
            if "@" in l and header is None:
                header = l.replace("@", "").split()
            elif header and l.strip() and not l.startswith("*"):
                parts = l.split()
                if len(parts) >= len(header):
                    rows.append(parts[:len(header)])
        if header and rows:
            df = pd.DataFrame(rows, columns=header)
            df = df.apply(pd.to_numeric, errors="coerce")
            print(f"\n==================== Season {season} Evaluate.OUT Summary ====================")
            cols_to_show = ["RUN", "TRNO"]
            for c in ["CWAM", "CWAC", "HWAM", "HWAC", "HWAH", "LAIX", "LIXC", "SWAM", "SWAC", "LWAM", "LWAC"]:
                if c in df.columns:
                    cols_to_show.append(c)
            sub_df = df[cols_to_show].copy()
            if "HWAM" in sub_df.columns and "HWAC" in sub_df.columns:
                sub_df["HW_BIAS"] = sub_df["HWAC"] - sub_df["HWAM"]
                sub_df["HW_RRMSE%"] = (sub_df["HW_BIAS"].abs() / sub_df["HWAM"] * 100).round(1)
            if "LAIX" in sub_df.columns and "LIXC" in sub_df.columns:
                sub_df["LAI_BIAS"] = sub_df["LIXC"] - sub_df["LAIX"]
            if "SWAM" in sub_df.columns and "SWAC" in sub_df.columns:
                sub_df["SW_BIAS"] = sub_df["SWAC"] - sub_df["SWAM"]
            print(sub_df.to_string(index=False))

