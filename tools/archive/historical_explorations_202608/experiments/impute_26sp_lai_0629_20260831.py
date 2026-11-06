"""Impute the missing 2026-06-29 (26180) LAI observations for 26SP.

The third destructive sampling of 2026 spring recorded leaf dry weight but no
LAI.  User-approved scheme (2026-08-31, option A): LAI = leaf_dw / R with the
global clean-sample SLA ratio R = 18.52 (leave-one-date-out cross-validation
against the 0602 measured LAI gives MAE 6.1% / RMSE 7.9%).  raw_sd carries the
ratio uncertainty: sqrt(sd_reps^2 + (0.079*mean)^2).

Design constraints
------------------
* Additive only: the derived bundle keeps every existing value of its parent
  (canonical ``XXQL2601``, including its harvest value system) byte-for-byte;
  only the 12 LAID fields at 26180 are filled.  The unresolved 26SP value-system
  adjudication is therefore NOT prejudged.
* Rows carrying approved exclusion flags (剔除标记, channel-2 leaf-dry/whole-plant
  removals) are excluded from both estimation and imputation.
* FileA is intentionally left untouched: LAIX stays measured-only, and the
  terminal LAI observation remains 0717 (26198).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REF_XLSX = ROOT / "data/user/ref/DSSAT文件/2026春/2026春生长指标集.xlsx"
PARENT = ROOT / "data/user/experiments/XXQL2601"
TARGET = ROOT / "data/user/experiments/xxql2601_lai0629_imputed_20260831"
R_SLA = 18.52          # user-approved global clean-sample mean of leaf_dw / LAI
RATIO_CV = 0.079       # leave-one-date-out RMSE of the scheme
TARGET_DATE_TMT = "26180"
TARGET_DATE_ISO = "2026-06-29"
IMPUTED_FLAG = "imputed_20260831"
SD_METHOD = "imputed_sla_ratio_20260831"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw_0629() -> pd.DataFrame:
    df = pd.read_excel(REF_XLSX, sheet_name="0629")
    out = pd.DataFrame({
        "plot": pd.to_numeric(df["处理 (Treatment)"], errors="coerce"),
        "rep": df["重复"],
        "leafdw": pd.to_numeric(df["叶干重"], errors="coerce"),
        "flag": df["剔除标记"].astype(str).str.strip() if "剔除标记" in df.columns else "",
    })
    out["excluded"] = out["flag"].str.contains("叶干重|整株", na=False) & (out["flag"] != "")
    return out


def verify_reference_ratio() -> float:
    """Recompute the clean-sample SLA ratio from the three measured dates."""
    rows = []
    for sheet, plotcol in [("0502", "小区"), ("0602", "处理"), ("0717", "处理")]:
        df = pd.read_excel(REF_XLSX, sheet_name=sheet)
        sub = pd.DataFrame({
            "sheet": sheet,
            "leafdw": pd.to_numeric(df["叶干重"], errors="coerce"),
            "lai": pd.to_numeric(df["LAI"], errors="coerce"),
            "flag": df["剔除标记"].astype(str).str.strip() if "剔除标记" in df.columns else "",
        })
        rows.append(sub)
    d = pd.concat(rows, ignore_index=True)
    d["flag"] = d["flag"].fillna("")
    bad = d["flag"].str.contains("叶干重|LAI|整株", na=False)
    clean = d[~bad].dropna(subset=["leafdw", "lai"])
    clean = clean[clean["lai"] > 0]
    ratio = clean["leafdw"] / clean["lai"]
    full_mean = float(ratio.mean())
    if abs(full_mean - 18.58) > 0.05:
        raise SystemExit(f"reference ratio drifted: full-clean mean {full_mean:.3f} (expected ~18.58)")
    return full_mean


def plot_imputations(raw: pd.DataFrame) -> pd.DataFrame:
    valid = raw[~raw["excluded"] & raw["leafdw"].notna()].copy()
    valid["lai_est"] = valid["leafdw"] / R_SLA
    recs = []
    for plot, grp in valid.groupby("plot"):
        vals = grp["lai_est"].to_numpy(float)
        mean = float(np.mean(vals))
        sd_reps = float(np.std(vals, ddof=1)) if len(vals) >= 2 else 0.0
        total_sd = float(np.sqrt(sd_reps ** 2 + (RATIO_CV * mean) ** 2))
        recs.append({"plot": int(plot), "lai": round(mean, 3), "raw_sd": round(total_sd, 3),
                     "n_rep": int(len(vals)), "sd_reps": round(sd_reps, 3)})
    out = pd.DataFrame(recs).sort_values("plot").reset_index(drop=True)
    if len(out) != 12 or (out["n_rep"] < 2).any():
        raise SystemExit(f"unexpected imputation coverage: {out}")
    return out


def patch_tmt_lines(lines: list[str], table: pd.DataFrame) -> tuple[list[str], int]:
    lookup = {int(r.plot): r for r in table.itertuples()}
    patched = 0
    out = []
    for line in lines:
        m = re.match(r"^(\s*\d+)(\s+26180)(\s{2,}.{6})(.{6})(.*)$", line.rstrip("\n"))
        if m and int(m.group(1)) in lookup:
            rec = lookup[int(m.group(1))]
            old_field = m.group(4)
            if old_field.strip() not in {"-99", ""}:
                raise SystemExit(f"LAID field not empty for plot {m.group(1).strip()}: {old_field!r}")
            new_field = f"{rec.lai:>6.3f}"
            if len(new_field) != 6:
                raise SystemExit(f"formatted LAI exceeds 6-char field: {new_field!r}")
            line = line[:18] + new_field + line[24:]
            patched += 1
        out.append(line)
    return out, patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run == args.apply:
        parser.error("choose exactly one of --dry-run or --apply")

    full_mean = verify_reference_ratio()
    raw = load_raw_0629()
    table = plot_imputations(raw)

    print(f"reference ratio (full clean sample) = {full_mean:.3f}; approved R = {R_SLA}")
    print(table.to_string(index=False))

    if args.dry_run:
        tmt = (PARENT / "XXQL2601.TMT").read_text(encoding="utf-8-sig").splitlines(keepends=True)
        _, n = patch_tmt_lines(tmt, table)
        print(f"dry-run: {n} TMT lines would be patched in {TARGET.name}")
        return 0

    if TARGET.exists():
        raise SystemExit(f"target bundle already exists: {TARGET}")
    shutil.copytree(PARENT, TARGET)

    # 1. TMT: fill LAID at 26180 (fixed-width, additive only)
    tmt_path = TARGET / "XXQL2601.TMT"
    lines = tmt_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    lines, n_patched = patch_tmt_lines(lines, table)
    header_note = ("! LAID at 26180 imputed from leaf dry weight / SLA ratio "
                   f"(R={R_SLA}, ratio CV {RATIO_CV:.3f}); user-approved 2026-08-31; "
                   "flagged replicates excluded; FileA LAIX unchanged (measured only).\n")
    at_idx = next(i for i, l in enumerate(lines) if l.lstrip().startswith("@TRNO"))
    lines.insert(at_idx, header_note)
    tmt_path.write_text("".join(lines), encoding="utf-8", newline="")

    # 2. FileT_values.csv: fill LAID at 2026-06-29
    ftv_path = TARGET / "FileT_values.csv"
    ftv = pd.read_csv(ftv_path)
    mask = (ftv["TRNO"].astype(int).isin(table["plot"])) & (ftv["DATE"].astype(str) == TARGET_DATE_ISO)
    if int(mask.sum()) != 12:
        raise SystemExit(f"FileT_values: expected 12 rows at {TARGET_DATE_ISO}, found {int(mask.sum())}")
    lookup = {int(r.plot): r.lai for r in table.itertuples()}
    ftv.loc[mask, "LAID"] = ftv.loc[mask, "TRNO"].astype(int).map(lookup)
    ftv.to_csv(ftv_path, index=False)

    # 3. observation_uncertainty.csv: append imputed rows
    unc_path = TARGET / "observation_uncertainty.csv"
    unc = pd.read_csv(unc_path)
    dup = unc[(unc["trno"].isin(table["plot"])) & (unc["date"].astype(str) == TARGET_DATE_TMT) & (unc["variable"] == "LAID")]
    if len(dup):
        raise SystemExit("uncertainty already carries LAID rows at 26180")
    src_wb = "2026春生长指标集.xlsx"
    new_rows = pd.DataFrame([{
        "season_id": "26SP", "excode": "XXQL2601", "trno": int(r.plot), "date": TARGET_DATE_TMT,
        "variable": "LAID", "value": r.lai, "raw_sd": r.raw_sd, "n_rep": r.n_rep,
        "sd_method": SD_METHOD, "source_workbook": src_wb, "source_sheet": "0629",
        "source_row_rule": "imputed_from_leafdw_over_sla_ratio",
        "quality_flag": IMPUTED_FLAG,
    } for r in table.itertuples()])
    pd.concat([unc, new_rows], ignore_index=True).to_csv(unc_path, index=False)

    # 4. imputation audit (replicate-level)
    audit = raw.copy()
    audit["lai_est_row"] = audit["leafdw"] / R_SLA
    audit.to_csv(TARGET / "lai0629_imputation_audit.csv", index=False)

    # 5. minimal manifest with hashes + correction record
    manifest = {
        "bundle_id": TARGET.name,
        "derived_from_bundle": PARENT.name,
        "derived_from_manifest_sha256": None,
        "note": ("parent canonical root carries no input_manifest.json; this manifest "
                 "covers the additive LAI imputation only and preserves the parent's "
                 "harvest value system unchanged"),
        "data_corrections": {
            "correction_id": IMPUTED_FLAG,
            "method": "LAI = leaf_dry_weight / SLA ratio (R=18.52), global clean-sample mean",
            "validation": "leave-one-date-out on 0602: MAE 6.1%, RMSE 7.9%",
            "ratio_cv": RATIO_CV,
            "imputed_points": 12,
            "excluded_flagged_rows": int(raw["excluded"].sum()),
            "filea_unchanged": True,
        },
        "files": [
            {"name": name, "sha256": sha256(TARGET / name)}
            for name in ["XXQL2601.TMT", "FileT_values.csv", "observation_uncertainty.csv",
                         "lai0629_imputation_audit.csv"]
        ],
    }
    (TARGET / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"applied: {n_patched} TMT lines, 12 uncertainty rows, manifest written -> {TARGET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
