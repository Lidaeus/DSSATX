"""Scan fruit moisture (半果含水率/果含水率) outliers across all three seasons.

Outlier rule (per (season, TRNO, date) group with n_reps >= 3):
  - Compute mean and sample SD (ddof=1) excluding any single rep
    ("leave-one-out" approach).
  - A rep is flagged if its absolute deviation from the leave-one-out mean
    exceeds max(3 * leave_one_out_SD, 0.05).
  - The 0.05 floor catches cases where 2 reps are nearly identical and the
    third is off by ~10-20% (like the 0.968/0.968/0.785 pattern).

Also flags groups where the within-group SD > 0.03 (3% absolute moisture),
which is a strong indicator of an outlier even if n_reps < 3.

Output: per-season table of suspicious raw rows + suggested corrections
(impute from the remaining reps' mean).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REF_DIR = PROJECT_ROOT / "data" / "user" / "ref" / "DSSAT文件"


def load_moisture_25sp() -> pd.DataFrame:
    """25SP: moisture is in 2025春作物生长指标集.xlsx, col 果含水率."""
    path = REF_DIR / "2025春" / "2025春作物生长指标集.xlsx"
    df = pd.read_excel(path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.normalize()
    df["TRNO"] = pd.to_numeric(df["小区号"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO", "日期"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["season_id"] = "25SP"
    df["source_file"] = path.name
    df["moisture"] = pd.to_numeric(df.get("果含水率"), errors="coerce")
    df["replicate"] = pd.to_numeric(df.get("重复"), errors="coerce").astype("Int64")
    return df[["season_id", "TRNO", "日期", "replicate", "moisture", "source_file"]].dropna(subset=["moisture"])


def load_moisture_25fa() -> pd.DataFrame:
    """25FA: moisture is in 25年秋季2号棚品质指标集.xlsx."""
    path = REF_DIR / "2025秋" / "25年秋季2号棚品质指标集.xlsx"
    df = pd.read_excel(path, sheet_name=None)
    # find sheet with moisture column
    target = None
    for name, frame in df.items():
        cols = [str(c).strip() for c in frame.columns]
        if any("含水率" in c for c in cols):
            target = (name, frame)
            break
    if target is None:
        return pd.DataFrame()
    sheet_name, frame = target
    frame = frame.rename(columns={c: str(c).strip() for c in frame.columns})
    moisture_col = next(c for c in frame.columns if "含水率" in c)
    frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce").dt.normalize() if "日期" in frame.columns else pd.NaT
    plot_col = next((c for c in ("小区号", "小区") if c in frame.columns), None)
    if plot_col is None:
        return pd.DataFrame()
    frame["TRNO"] = pd.to_numeric(frame[plot_col], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["TRNO", "日期"]).copy()
    frame["TRNO"] = frame["TRNO"].astype(int)
    frame["season_id"] = "25FA"
    frame["source_file"] = f"{path.name}/{sheet_name}"
    frame["moisture"] = pd.to_numeric(frame[moisture_col], errors="coerce")
    frame["replicate"] = pd.to_numeric(frame.get("重复"), errors="coerce").astype("Int64")
    return frame[["season_id", "TRNO", "日期", "replicate", "moisture", "source_file"]].dropna(subset=["moisture"])


def load_moisture_26sp() -> pd.DataFrame:
    """26SP: moisture is in 2026春品质指标集.xlsx, col 半果含水率."""
    path = REF_DIR / "2026春" / "2026春品质指标集.xlsx"
    df = pd.read_excel(path, sheet_name="Sheet1")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.normalize() if "日期" in df.columns else pd.NaT
    if "日期" not in df.columns or df["日期"].isna().all():
        # Try parsing as yyyymmdd int
        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
    plot_col = next((c for c in ("小区号", "小区") if c in df.columns), None)
    if plot_col is None:
        return pd.DataFrame()
    df["TRNO"] = pd.to_numeric(df[plot_col], errors="coerce").astype("Int64")
    df = df.dropna(subset=["TRNO", "日期"]).copy()
    df["TRNO"] = df["TRNO"].astype(int)
    df["season_id"] = "26SP"
    df["source_file"] = path.name
    moisture_col = next((c for c in df.columns if "含水率" in c), None)
    if moisture_col is None:
        return pd.DataFrame()
    df["moisture"] = pd.to_numeric(df[moisture_col], errors="coerce")
    df["replicate"] = pd.to_numeric(df.get("重复"), errors="coerce").astype("Int64")
    return df[["season_id", "TRNO", "日期", "replicate", "moisture", "source_file"]].dropna(subset=["moisture"])


def scan_outliers(df: pd.DataFrame, season_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (suspicious_rows, group_summary) for one season.

    suspicious_rows: every individual raw measurement flagged as an outlier.
    group_summary: per (TRNO, date) summary with flag_high_sd if SD > 0.03.
    """
    df = df[df["season_id"] == season_id].copy()
    df = df[(df["moisture"] > 0.5) & (df["moisture"] < 1.1)].copy()  # basic sanity

    suspicious = []
    summaries = []
    for (trno, date), grp in df.groupby(["TRNO", "日期"]):
        m = grp["moisture"].values
        n = len(m)
        if n == 0:
            continue
        mean_all = float(np.mean(m))
        sd_all = float(np.std(m, ddof=1)) if n >= 2 else 0.0
        dstr = pd.Timestamp(date).strftime("%Y-%m-%d")

        # Flag if SD > 0.03 (clear sign of an outlier even with n<3 logic)
        high_sd = sd_all > 0.03

        # Leave-one-out outlier detection (requires n >= 3)
        loo_flags = []
        if n >= 3:
            for i in range(n):
                others = np.delete(m, i)
                loo_mean = float(np.mean(others))
                loo_sd = float(np.std(others, ddof=1))
                threshold = max(3 * loo_sd, 0.05)
                deviation = abs(m[i] - loo_mean)
                if deviation > threshold:
                    loo_flags.append((i, m[i], loo_mean, loo_sd, deviation, threshold))

        for idx, row in grp.iterrows():
            row_out = {
                "season_id": season_id,
                "TRNO": int(trno),
                "date": dstr,
                "replicate": int(row["replicate"]) if pd.notna(row["replicate"]) else -1,
                "moisture_raw": float(row["moisture"]),
                "n_reps_in_group": n,
                "group_mean": mean_all,
                "group_sd": sd_all,
                "high_sd_flag": high_sd,
                "loo_outlier": False,
                "loo_mean_excluding_self": None,
                "loo_sd_excluding_self": None,
                "loo_deviation": None,
                "loo_threshold": None,
                "source_file": row["source_file"],
            }
            # Match against LOO flags by value (could be ambiguous but values rarely tie)
            for flag in loo_flags:
                _, val, lm, ls, dev, thr = flag
                if abs(val - row["moisture"]) < 1e-9:
                    row_out.update({
                        "loo_outlier": True,
                        "loo_mean_excluding_self": lm,
                        "loo_sd_excluding_self": ls,
                        "loo_deviation": dev,
                        "loo_threshold": thr,
                    })
                    break
            # Mark suspicious if either criterion triggers
            row_out["suspicious"] = bool(row_out["loo_outlier"] or row_out["high_sd_flag"])
            suspicious.append(row_out)

        summaries.append({
            "season_id": season_id,
            "TRNO": int(trno),
            "date": dstr,
            "n_reps": n,
            "mean": mean_all,
            "sd": sd_all,
            "min": float(np.min(m)),
            "max": float(np.max(m)),
            "implied_DMFR": 1.0 - mean_all,
            "high_sd_flag": high_sd,
            "has_loo_outlier": len(loo_flags) > 0,
        })

    return pd.DataFrame(suspicious), pd.DataFrame(summaries)


def main() -> None:
    print("=" * 100)
    print("Fruit moisture outlier scan (25SP / 25FA / 26SP)")
    print("=" * 100)

    all_suspicious = []
    all_summaries = []

    loaders = {
        "25SP": load_moisture_25sp,
        "25FA": load_moisture_25fa,
        "26SP": load_moisture_26sp,
    }

    for sid, loader in loaders.items():
        print(f"\n### {sid} ###")
        df = loader()
        if df.empty:
            print(f"  No moisture data loaded for {sid}")
            continue
        print(f"  Loaded {len(df)} raw moisture rows")
        # Sanity: report any out-of-[0.5, 1.0] range
        bad_range = df[(df["moisture"] < 0.5) | (df["moisture"] > 1.0)]
        if not bad_range.empty:
            print(f"  WARNING: {len(bad_range)} rows outside [0.5, 1.0]:")
            print(bad_range[["TRNO", "日期", "replicate", "moisture"]].to_string(index=False))

        suspicious, summary = scan_outliers(df, sid)
        n_groups = len(summary)
        n_high_sd = int(summary["high_sd_flag"].sum()) if not summary.empty else 0
        n_loo = int(summary["has_loo_outlier"].sum()) if not summary.empty else 0
        n_susp_rows = int(suspicious["suspicious"].sum()) if not suspicious.empty else 0
        print(f"  Groups: {n_groups}, high_SD(>0.03) groups: {n_high_sd}, "
              f"LOO-outlier groups: {n_loo}, suspicious raw rows: {n_susp_rows}")

        all_suspicious.append(suspicious)
        all_summaries.append(summary)

    # Combined suspicious raw rows
    print("\n" + "=" * 100)
    print("SUSPICIOUS RAW ROWS (LOO outlier OR group SD > 0.03)")
    print("=" * 100)
    if all_suspicious:
        combined = pd.concat([s for s in all_suspicious if not s.empty], ignore_index=True)
        flagged = combined[combined["suspicious"]].copy()
        if flagged.empty:
            print("  No suspicious rows detected.")
        else:
            cols = ["season_id", "TRNO", "date", "replicate", "moisture_raw",
                    "n_reps_in_group", "group_mean", "group_sd",
                    "loo_outlier", "loo_mean_excluding_self", "loo_sd_excluding_self",
                    "loo_deviation", "loo_threshold", "source_file"]
            cols = [c for c in cols if c in flagged.columns]
            # Round numeric
            for c in ["moisture_raw", "group_mean", "group_sd",
                      "loo_mean_excluding_self", "loo_sd_excluding_self",
                      "loo_deviation", "loo_threshold"]:
                if c in flagged.columns:
                    flagged[c] = flagged[c].astype(float).round(4)
            print(flagged[cols].to_string(index=False))
            print(f"\n  Total flagged: {len(flagged)}")
            # Suggested correction: impute with loo_mean_excluding_self
            print("\n  Suggested corrections (impute with leave-one-out mean):")
            for _, r in flagged.iterrows():
                if r["loo_outlier"] and pd.notna(r["loo_mean_excluding_self"]):
                    implied_old = 1 - r["group_mean"]
                    implied_new = 1 - r["loo_mean_excluding_self"]
                    print(f"    {r['season_id']} TRNO={r['TRNO']} {r['date']} rep{r['replicate']}: "
                          f"{r['moisture_raw']:.4f} -> {r['loo_mean_excluding_self']:.4f}  "
                          f"(DMFR: {implied_old:.4f} -> {implied_new:.4f})  "
                          f"source={r['source_file']}")

    # Combined group summaries with high SD
    print("\n" + "=" * 100)
    print("GROUPS WITH HIGH SD (> 0.03 absolute)")
    print("=" * 100)
    if all_summaries:
        combined_sum = pd.concat([s for s in all_summaries if not s.empty], ignore_index=True)
        high = combined_sum[combined_sum["high_sd_flag"]].sort_values(["season_id", "TRNO", "date"])
        if high.empty:
            print("  No high-SD groups.")
        else:
            for c in ["mean", "sd", "min", "max", "implied_DMFR"]:
                if c in high.columns:
                    high[c] = high[c].astype(float).round(4)
            print(high[["season_id", "TRNO", "date", "n_reps", "min", "max",
                        "mean", "sd", "implied_DMFR"]].to_string(index=False))


if __name__ == "__main__":
    main()
