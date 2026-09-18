"""Comprehensive cross-season audit: yield, moisture, DMFR, dry weight.

Goals (per user request):
  1. Cross-check 25FA and 26SP raw data (yield, moisture, DMFR) like 25SP.
  2. For each (season, date), compare treatment-to-treatment relative trends
     in FRESH yield vs DRY weight. If the trends disagree, it indicates
     moisture/DMFR issues distorting the dry-weight signal.

Diagnostic outputs per (season, date):
  - Per-TRNO: mean fresh yield, mean moisture, implied DMFR, expected dry
    = fresh * DMFR.
  - Rank correlation (Spearman) between fresh and dry across TRNOs. A low
    or negative Spearman indicates that DMFR noise is overriding the fresh-
    yield signal.
  - TRNOs whose dry rank differs from fresh rank by >= 3 positions.

Output directory: workspace/runs/data_audit_20260726/
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REF_DIR = PROJECT_ROOT / "data" / "user" / "ref" / "DSSAT文件"
OUT_DIR = PROJECT_ROOT / "workspace" / "runs" / "data_audit_20260726"


# ----------------------------------------------------------------------------
# Loaders
# ----------------------------------------------------------------------------

def load_yield_25sp() -> pd.DataFrame:
    path = REF_DIR / "2025春" / "2025春产量数据集.xlsx"
    df = pd.read_excel(path, sheet_name="Sheet1")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.normalize()
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO", "日期", "产量"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["season_id"] = "25SP"
    df["fresh"] = pd.to_numeric(df["加权小区产量"], errors="coerce")
    return df[["season_id", "TRNO", "日期", "fresh"]].dropna(subset=["fresh"])


def load_yield_25fa() -> pd.DataFrame:
    path = REF_DIR / "2025秋" / "2025秋季产量集.xlsx"
    df = pd.read_excel(path, sheet_name="2025秋季产量集")
    df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO", "日期", "小区产量"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["season_id"] = "25FA"
    df["fresh"] = pd.to_numeric(df["小区产量"], errors="coerce")
    return df[["season_id", "TRNO", "日期", "fresh"]].dropna(subset=["fresh"])


def load_yield_26sp() -> pd.DataFrame:
    path = REF_DIR / "2026春" / "2026春产量集.xlsx"
    df = pd.read_excel(path, sheet_name="Sheet1")
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
    df = df.dropna(subset=["日期", "小区产量"]).copy()
    df["season_id"] = "26SP"
    df["fresh"] = pd.to_numeric(df["小区产量"], errors="coerce")
    return df[["season_id", "TRNO", "日期", "fresh"]].dropna(subset=["fresh"])


def load_moisture_25sp() -> pd.DataFrame:
    path = REF_DIR / "2025春" / "2025春作物生长指标集.xlsx"
    df = pd.read_excel(path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.normalize()
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO", "日期"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["season_id"] = "25SP"
    df["moisture"] = pd.to_numeric(df.get("果含水率"), errors="coerce")
    return df[["season_id", "TRNO", "日期", "moisture"]].dropna(subset=["moisture"])


def load_moisture_25fa() -> pd.DataFrame:
    path = REF_DIR / "2025秋" / "25年秋季2号棚品质指标集.xlsx"
    xl = pd.read_excel(path, sheet_name=None)
    target = None
    for name, frame in xl.items():
        cols = [str(c).strip() for c in frame.columns]
        if any("含水率" in c for c in cols):
            target = (name, frame)
            break
    if target is None:
        return pd.DataFrame()
    sheet, frame = target
    frame = frame.rename(columns={c: str(c).strip() for c in frame.columns})
    m_col = next(c for c in frame.columns if "含水率" in c)
    frame["日期"] = pd.to_datetime(frame["日期"].astype(str), format="%Y%m%d",
                                    errors="coerce").dt.normalize() if "日期" in frame.columns else pd.NaT
    plot_col = next((c for c in ("小区号", "小区") if c in frame.columns), None)
    if plot_col is None or "日期" not in frame.columns:
        return pd.DataFrame()
    frame["TRNO"] = pd.to_numeric(frame[plot_col], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["TRNO", "日期"]).copy()
    frame["TRNO"] = frame["TRNO"].astype(int)
    frame["season_id"] = "25FA"
    frame["moisture"] = pd.to_numeric(frame[m_col], errors="coerce")
    return frame[["season_id", "TRNO", "日期", "moisture"]].dropna(subset=["moisture"])


def load_moisture_26sp() -> pd.DataFrame:
    path = REF_DIR / "2026春" / "2026春品质指标集.xlsx"
    df = pd.read_excel(path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    m_col = next((c for c in df.columns if "含水率" in c), None)
    if m_col is None:
        return pd.DataFrame()
    df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d",
                                 errors="coerce").dt.normalize() if "日期" in df.columns else pd.NaT
    plot_col = next((c for c in ("小区号", "小区") if c in df.columns), None)
    if plot_col is None:
        return pd.DataFrame()
    df["TRNO"] = pd.to_numeric(df[plot_col], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO", "日期"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["season_id"] = "26SP"
    df["moisture"] = pd.to_numeric(df[m_col], errors="coerce")
    return df[["season_id", "TRNO", "日期", "moisture"]].dropna(subset=["moisture"])


# ----------------------------------------------------------------------------
# LOO outlier scan (per (season, TRNO, date))
# ----------------------------------------------------------------------------

def loo_outlier_scan(moisture_df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per raw moisture measurement with LOO flags."""
    rows = []
    for (sid, trno, date), grp in moisture_df.groupby(["season_id", "TRNO", "日期"]):
        m = grp["moisture"].values
        n = len(m)
        if n == 0:
            continue
        mean_all = float(np.mean(m))
        sd_all = float(np.std(m, ddof=1)) if n >= 2 else 0.0
        for i in range(n):
            row = grp.iloc[i]
            flag = False
            loo_mean = loo_sd = dev = thr = None
            if n >= 3:
                others = np.delete(m, i)
                loo_mean = float(np.mean(others))
                loo_sd = float(np.std(others, ddof=1))
                thr = max(3 * loo_sd, 0.05)
                dev = abs(m[i] - loo_mean)
                if dev > thr:
                    flag = True
            rows.append({
                "season_id": sid, "TRNO": int(trno),
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "moisture_raw": float(m[i]),
                "n_reps": n,
                "group_mean": mean_all, "group_sd": sd_all,
                "loo_outlier": flag, "loo_mean": loo_mean,
                "loo_sd": loo_sd, "loo_dev": dev, "loo_threshold": thr,
                "high_group_sd": sd_all > 0.03,
                "suspicious": bool(flag or sd_all > 0.03),
            })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Trend comparison: fresh vs dry per (season, date)
# ----------------------------------------------------------------------------

def trend_comparison(yield_df: pd.DataFrame, moisture_df: pd.DataFrame,
                     sid: str, max_match_days: int = 14) -> pd.DataFrame:
    """For each (season, date) in yield_df, compute per-TRNO fresh mean and
    nearest-date moisture -> implied DMFR -> expected dry weight. Then compute
    Spearman rank correlation between fresh and dry across TRNOs.
    """
    y = yield_df[yield_df["season_id"] == sid].copy()
    m = moisture_df[moisture_df["season_id"] == sid].copy() if not moisture_df.empty else pd.DataFrame()
    if y.empty:
        return pd.DataFrame()

    # Aggregate fresh yield per (TRNO, date)
    y_agg = (y.groupby(["TRNO", "日期"], as_index=False)
              .agg(fresh_mean=("fresh", "mean"), fresh_sd=("fresh", "std"), n_reps=("fresh", "count")))
    y_agg["fresh_sd"] = y_agg["fresh_sd"].fillna(0)

    # Aggregate moisture per (TRNO, date)
    if m.empty:
        m_agg = pd.DataFrame(columns=["TRNO", "日期", "moisture_mean"])
    else:
        m_agg = (m.groupby(["TRNO", "日期"], as_index=False)
                  .agg(moisture_mean=("moisture", "mean"),
                       moisture_sd=("moisture", "std"),
                       m_n_reps=("moisture", "count")))

    # For each (TRNO, ydate), find nearest moisture measurement date for that TRNO
    merged_rows = []
    trnos = sorted(y_agg["TRNO"].unique())
    for trno in trnos:
        y_trno = y_agg[y_agg["TRNO"] == trno].sort_values("日期")
        m_trno = m_agg[m_agg["TRNO"] == trno].sort_values("日期") if not m_agg.empty else pd.DataFrame()
        for _, yr in y_trno.iterrows():
            ydate = yr["日期"]
            if m_trno.empty:
                moisture = np.nan
                match_days = None
            else:
                deltas = (m_trno["日期"] - ydate).abs()
                idx = deltas.idxmin()
                moisture = m_trno.loc[idx, "moisture_mean"]
                match_days = int(deltas.loc[idx].days)
            dmfr = 1.0 - moisture if pd.notna(moisture) else np.nan
            merged_rows.append({
                "season_id": sid,
                "TRNO": int(trno),
                "yield_date": ydate,
                "fresh": float(yr["fresh_mean"]),
                "fresh_sd": float(yr["fresh_sd"]) if pd.notna(yr["fresh_sd"]) else 0.0,
                "n_reps_fresh": int(yr["n_reps"]),
                "matched_moisture": moisture,
                "match_days": match_days,
                "dmfr": dmfr,
                "dry_expected": float(yr["fresh_mean"]) * dmfr if pd.notna(dmfr) else np.nan,
            })
    merged = pd.DataFrame(merged_rows)
    return merged


def per_date_spearman(merged: pd.DataFrame) -> pd.DataFrame:
    """Per (season, yield_date), Spearman(fresh, dry_expected) across TRNOs."""
    rows = []
    for (sid, ydate), grp in merged.groupby(["season_id", "yield_date"]):
        grp_ok = grp.dropna(subset=["fresh", "dry_expected"])
        n = len(grp_ok)
        if n < 3:
            continue
        rho, pval = spearmanr(grp_ok["fresh"], grp_ok["dry_expected"])
        # Rank mismatch analysis
        grp_ok = grp_ok.copy()
        grp_ok["fresh_rank"] = grp_ok["fresh"].rank(ascending=False).astype(int)
        grp_ok["dry_rank"] = grp_ok["dry_expected"].rank(ascending=False).astype(int)
        grp_ok["rank_diff"] = (grp_ok["dry_rank"] - grp_ok["fresh_rank"]).abs()
        worst = grp_ok.loc[grp_ok["rank_diff"].idxmax()]
        n_mismatch_ge3 = int((grp_ok["rank_diff"] >= 3).sum())
        rows.append({
            "season_id": sid,
            "yield_date": pd.Timestamp(ydate).strftime("%Y-%m-%d"),
            "n_trno": n,
            "spearman_rho": float(rho),
            "spearman_p": float(pval),
            "n_rank_mismatch_ge3": n_mismatch_ge3,
            "worst_trno": int(worst["TRNO"]),
            "worst_rank_diff": int(worst["rank_diff"]),
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

def print_section(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print_section("Step 1: Load raw yield + moisture")
    yields = pd.concat([load_yield_25sp(), load_yield_25fa(), load_yield_26sp()], ignore_index=True)
    moistures = pd.concat([load_moisture_25sp(), load_moisture_25fa(), load_moisture_26sp()], ignore_index=True)
    print(f"  Yield rows: {len(yields)}")
    print(yields.groupby("season_id").size().to_string())
    print(f"\n  Moisture rows: {len(moistures)}")
    print(moistures.groupby("season_id").size().to_string() if not moistures.empty else "  (empty)")

    print_section("Step 2: Moisture LOO outlier scan")
    outliers = loo_outlier_scan(moistures)
    flagged = outliers[outliers["suspicious"]].copy()
    for c in ["moisture_raw", "group_mean", "group_sd", "loo_mean", "loo_sd", "loo_dev", "loo_threshold"]:
        if c in flagged.columns:
            flagged[c] = flagged[c].astype(float).round(4)
    print(f"  Flagged raw rows: {len(flagged)} / {len(outliers)}")
    if not flagged.empty:
        cols = ["season_id", "TRNO", "date", "moisture_raw", "n_reps",
                "group_mean", "group_sd", "loo_outlier", "loo_mean",
                "loo_dev", "loo_threshold"]
        print(flagged[cols].to_string(index=False))
    flagged.to_csv(OUT_DIR / "moisture_outliers.csv", index=False)

    print_section("Step 3: Per-(season, date) fresh vs dry trend comparison")
    all_merged = []
    all_spearman = []
    for sid in ["25SP", "25FA", "26SP"]:
        merged = trend_comparison(yields, moistures, sid)
        if merged.empty:
            print(f"\n  {sid}: no yield data")
            continue
        all_merged.append(merged)
        sp = per_date_spearman(merged)
        all_spearman.append(sp)
        print(f"\n  --- {sid} ({len(merged)} TRNO-date rows) ---")
        if sp.empty:
            print("    No dates with >=3 TRNOs matched to moisture.")
        else:
            for c in ["spearman_rho", "spearman_p"]:
                sp[c] = sp[c].astype(float).round(4)
            print(sp[["yield_date", "n_trno", "spearman_rho", "spearman_p",
                     "n_rank_mismatch_ge3", "worst_trno", "worst_rank_diff"]].to_string(index=False))

    if all_merged:
        merged_all = pd.concat(all_merged, ignore_index=True)
        merged_all.to_csv(OUT_DIR / "fresh_vs_dry_per_trno_date.csv", index=False)
    if all_spearman:
        spearman_all = pd.concat(all_spearman, ignore_index=True)
        spearman_all.to_csv(OUT_DIR / "fresh_vs_dry_spearman.csv", index=False)

    print_section("Step 4: Verdict")
    if all_spearman:
        sp_all = pd.concat(all_spearman, ignore_index=True)
        n_low = int((sp_all["spearman_rho"] < 0.7).sum())
        n_neg = int((sp_all["spearman_rho"] < 0).sum())
        n_total = len(sp_all)
        print(f"  Per-date Spearman(fresh, dry):")
        print(f"    Total (season, date) groups: {n_total}")
        print(f"    Groups with rho < 0.7 (weak): {n_low}")
        print(f"    Groups with rho < 0  (inverted trend): {n_neg}")
        if n_low == 0:
            print("  >> Fresh and dry weight trends are consistent across all groups.")
        else:
            print(f"  >> {n_low} groups show weak fresh-dry trend consistency.")
            weak = sp_all[sp_all["spearman_rho"] < 0.7].sort_values("spearman_rho")
            for _, r in weak.iterrows():
                print(f"    {r['season_id']} {r['yield_date']}: rho={r['spearman_rho']:.3f}, "
                      f"worst_trno={r['worst_trno']} (rank_diff={r['worst_rank_diff']})")

    print(f"\n  Output written to: {OUT_DIR}")
    print(f"    - moisture_outliers.csv")
    print(f"    - fresh_vs_dry_per_trno_date.csv")
    print(f"    - fresh_vs_dry_spearman.csv")


if __name__ == "__main__":
    main()
