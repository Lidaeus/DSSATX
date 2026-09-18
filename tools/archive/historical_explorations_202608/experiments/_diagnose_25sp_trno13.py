"""Diagnose CHPDT anomaly for 25SP TRNO=13.

User observation: TRNO=13 25198 -> 25203 has fresh weight increase of 7197
(61069 -> 68266) but dry weight increase of only 670 (5685 -> 6355), which
is implausibly low ratio (670/7197 = 9.3%) compared to other harvests.

This script dumps:
  1. The yield workbook rows for TRNO=13 (per-replicate fresh weights)
  2. The fruit quality (moisture) rows matched to each TRNO=13 harvest date
  3. The fruit_quality_match_audit.csv for TRNO=13
  4. A side-by-side comparison of fresh / dry / DMFR for all TRNO=13 harvests
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REF_DIR = PROJECT_ROOT / "data" / "user" / "ref" / "DSSAT文件"
YIELD_XLSX = REF_DIR / "2025春" / "2025春产量数据集.xlsx"
QUALITY_XLSX = REF_DIR / "2025春" / "2025春作物生长指标集.xlsx"
AUDIT_CSV = REF_DIR / "2025春" / "DSSAT输出_v2" / "fruit_quality_match_audit.csv"


def main() -> None:
    TRNO = 13

    # --- 1. Yield workbook raw rows ---
    print("=" * 100)
    print(f"[1] Yield workbook raw rows for TRNO={TRNO}")
    print("=" * 100)
    y = pd.read_excel(YIELD_XLSX, sheet_name="Sheet1")
    y["日期"] = pd.to_datetime(y["日期"], errors="coerce").dt.normalize()
    y["TRNO"] = pd.to_numeric(y["小区号"], errors="coerce").astype("Int64")
    y_trno = y[y["TRNO"] == TRNO].copy()
    if y_trno.empty:
        print(f"  No rows for TRNO={TRNO}")
    else:
        cols = ["日期", "TRNO", "重复", "水处理", "氮处理", "果实总重", "果实个数",
                "产量", "加权小区产量", "行位置"]
        cols = [c for c in cols if c in y_trno.columns]
        print(y_trno[cols].to_string(index=False))

    # Group by date to see mean/SD
    print(f"\n  Per-date yield summary:")
    for date, grp in y_trno.groupby("日期"):
        weighted = grp["加权小区产量"].iloc[0] if "加权小区产量" in grp.columns else None
        rows = grp["产量"].dropna().values
        print(f"    {date.strftime('%Y-%m-%d')} (yyddd={(date.year % 100)*1000 + date.timetuple().tm_yday}): "
              f"n_reps={len(rows)}, mean={rows.mean():.1f}, sd={rows.std(ddof=1) if len(rows) > 1 else 0:.1f}, "
              f"weighted_plot_yield={weighted}")

    # --- 2. Fruit quality (moisture) raw rows ---
    print("\n" + "=" * 100)
    print(f"[2] Fruit quality (半果含水率) raw rows for TRNO={TRNO}")
    print("=" * 100)
    q = pd.read_excel(QUALITY_XLSX, sheet_name="Sheet1")
    q = q.rename(columns={c: str(c).strip() for c in q.columns})
    if "果含水率" in q.columns and "半果含水率" not in q.columns:
        moisture_col = "果含水率"
    else:
        moisture_col = "半果含水率"
    q["日期"] = pd.to_datetime(q["日期"], errors="coerce").dt.normalize()
    q["TRNO"] = pd.to_numeric(q["小区号"], errors="coerce").astype("Int64")
    q_trno = q[q["TRNO"] == TRNO].copy()
    if q_trno.empty:
        print(f"  No rows for TRNO={TRNO}")
    else:
        cols = ["日期", "TRNO", "重复", "水处理", "氮处理", moisture_col]
        cols = [c for c in cols if c in q_trno.columns]
        print(q_trno[cols].to_string(index=False))

    print(f"\n  Per-date moisture summary:")
    for date, grp in q_trno.groupby("日期"):
        m = grp[moisture_col].dropna().values
        if len(m):
            print(f"    {date.strftime('%Y-%m-%d')} (yyddd={(date.year % 100)*1000 + date.timetuple().tm_yday}): "
                  f"n_reps={len(m)}, mean={m.mean():.4f}, sd={m.std(ddof=1) if len(m) > 1 else 0:.4f}, "
                  f"implied_DMFR={1 - m.mean():.4f}")

    # --- 3. Audit CSV (what the adapter matched) ---
    print("\n" + "=" * 100)
    print(f"[3] fruit_quality_match_audit.csv for TRNO={TRNO}")
    print("=" * 100)
    if not AUDIT_CSV.is_file():
        print(f"  {AUDIT_CSV} not found")
    else:
        a = pd.read_csv(AUDIT_CSV)
        a_trno = a[a["trno"] == TRNO].copy()
        if a_trno.empty:
            print(f"  No audit rows for TRNO={TRNO}")
        else:
            cols = ["trno", "harvest_date", "quality_date", "match_days",
                    "fresh_yield", "fresh_sd",
                    "dmfr", "dmfr_sd",
                    "dry_increment", "dry_increment_sd",
                    "chpdt", "chpdt_sd", "match_status"]
            cols = [c for c in cols if c in a_trno.columns]
            print(a_trno[cols].to_string(index=False))

    # --- 4. Side-by-side diagnostic ---
    print("\n" + "=" * 100)
    print(f"[4] Side-by-side: per-harvest fresh / dry / DMFR / ratio")
    print("=" * 100)
    print(f"  {'harvest_date':>12} {'fresh_yield':>12} {'dry_increment':>14} "
          f"{'DMFR':>8} {'dry/fresh':>10} {'expected_dry':>12}")
    if AUDIT_CSV.is_file():
        a = pd.read_csv(AUDIT_CSV)
        a_trno = a[a["trno"] == TRNO].sort_values("harvest_date")
        for _, r in a_trno.iterrows():
            fresh = float(r["fresh_yield"])
            dry_inc = float(r["dry_increment"])
            dmfr = float(r["dmfr"])
            ratio = dry_inc / fresh if fresh else 0
            expected = fresh * dmfr
            print(f"  {str(r['harvest_date']):>12} {fresh:>12.1f} {dry_inc:>14.1f} "
                  f"{dmfr:>8.4f} {ratio:>10.4f} {expected:>12.1f}"
                  f"  {'<<ANOMALY' if ratio < 0.5 * dmfr else ''}")


if __name__ == "__main__":
    main()
