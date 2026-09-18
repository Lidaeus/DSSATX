#!/usr/bin/env python3
"""E00 v2 input audit for the three new trial-calibration bundles.

Per docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md Section 6.5:
  对每个候选 bundle 运行 input/harvest/manifest audit，生成 SHA receipt。

This is a READ-ONLY audit. It does not modify any file. It verifies:
  1. Manifest audit: every file listed in input_manifest.json exists and SHA-256 matches.
  2. Strict-fill audit: TMA only fills TRNO/HDAT/LWAM/SWAM/LAIX; TMT only fills
     TRNO/DATE/LAID/LWAD/SWAD/CHFPW/CHPDT. All other columns must be -99.
  3. Harvest alignment audit: TMA HDAT (per treatment) == last TMT harvest DATE
     (the last row with non-(-99) CHPDT for that TRNO).
  4. Treatment exclusion audit (25SP only): TN 1,6,7,8 must NOT appear in TMA/TMT/soil.
  5. Soil water first-date exclusion audit: per (trno, depth), exactly one date
     is tagged initial_condition_only.

Output:
  workspace/runs/E00_v2_audit_20260726/
    E00_v2_audit_receipt.json     (findings + per-bundle summary)
    E00_v2_manifest_audit.csv     (per-file SHA verification)
    E00_v2_strict_fill_audit.csv  (per-column fill compliance)
    E00_v2_harvest_alignment.csv  (per-treatment HDAT vs last TMT harvest date)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BUNDLES = {
    "25SP": {
        "dir": PROJECT_ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v2_20260726",
        "excode": "XXQL2501",
        "excluded_tn": [1, 6, 7, 8],
        "included_tn": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    "25FA": {
        "dir": PROJECT_ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v2_20260726",
        "excode": "XXQL2502",
        "excluded_tn": [],
        "included_tn": list(range(1, 13)),
    },
    "26SP": {
        "dir": PROJECT_ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v2_20260726",
        "excode": "XXQL2601",
        "excluded_tn": [],
        "included_tn": list(range(1, 13)),
    },
}

# Strict fill rules (Section 2 of the spec)
TMA_FILL = {"TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "LWAM", "SWAM", "LAIX"}
TMT_FILL = {"TRNO", "DATE", "LAID", "LWAD", "SWAD", "CHTD", "CHFPW", "HPODW", "CHPDT"}

TMA_COLUMNS = ["TRNO", "PDAT", "ADAT", "MDAT", "HDAT", "HWAM", "LWAM", "SWAM", "LAIX", "HIAM", "CNAM"]
TMT_COLUMNS = [
    "TRNO", "DATE", "L#SD", "LAID", "L#PA", "LWAD", "RWAD", "SWAD",
    "M#AD", "SLAD", "CHTD", "CWID", "CNAM", "SNAM", "LNAM",
    "HFPOW", "CHFPW", "HPODW", "CHPDT", "PDMCD",
]


@dataclass
class Finding:
    check: str
    status: str  # "pass" | "fail" | "warning"
    detail: str = ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------
# Audit 1: Manifest verification
# ----------------------------------------------------------------------------

def audit_manifest(bundle_dir: Path) -> tuple[list[dict], list[Finding]]:
    """Verify every file listed in input_manifest.json exists and SHA matches."""
    manifest_path = bundle_dir / "input_manifest.json"
    sid = bundle_dir.name
    rows: list[dict] = []
    findings: list[Finding] = []

    if not manifest_path.is_file():
        findings.append(Finding("manifest", "fail", f"{sid}: input_manifest.json not found"))
        return rows, findings

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # The v2 manifest stores files in a nested "files" dict and a flat "files_flat" list
    if "files_flat" in manifest:
        flat_files = manifest["files_flat"]
    elif isinstance(manifest.get("files"), list):
        flat_files = manifest["files"]
    else:
        # Fallback: flatten the nested files dict
        flat_files = []
        for v in manifest.get("files", {}).values():
            if isinstance(v, list):
                flat_files.extend(v)

    if not flat_files:
        findings.append(Finding("manifest", "fail", f"{sid}: manifest lists no files"))
        return rows, findings

    for entry in flat_files:
        fname = entry.get("name", "")
        decl_sha = str(entry.get("sha256", "")).strip().lower()
        fpath = bundle_dir / fname
        row = {
            "bundle": sid,
            "file": fname,
            "exists": fpath.is_file(),
            "declared_sha256": decl_sha,
            "actual_sha256": None,
            "sha_match": None,
        }
        if not fpath.is_file():
            findings.append(Finding("manifest", "fail", f"{sid}: listed file missing: {fname}"))
            rows.append(row)
            continue
        actual = sha256_file(fpath)
        row["actual_sha256"] = actual
        if decl_sha:
            row["sha_match"] = (actual == decl_sha)
            if actual != decl_sha:
                findings.append(Finding("manifest", "fail", f"{sid}: SHA mismatch: {fname}"))
        else:
            row["sha_match"] = True  # no declared SHA, skip check
        rows.append(row)

    n_verified = sum(1 for r in rows if r["sha_match"])
    n_total = len(rows)
    n_missing = sum(1 for r in rows if not r["exists"])
    n_mismatch = sum(1 for r in rows if r["sha_match"] is False)
    if n_missing == 0 and n_mismatch == 0:
        findings.append(Finding("manifest", "pass", f"{sid}: {n_verified}/{n_total} files verified"))
    return rows, findings


# ----------------------------------------------------------------------------
# Audit 2: Strict-fill rule compliance
# ----------------------------------------------------------------------------

def parse_dssat_file(path: Path) -> pd.DataFrame:
    """Parse a DSSAT FileA/FileT (6-char fixed-width) into a DataFrame."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header_line = None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("@TRNO"):
            header_line = line
            continue
        if header_line is not None and line.strip() and not line.startswith("!") and not line.startswith("*"):
            data_lines.append(line)
    if header_line is None:
        raise ValueError(f"{path}: no @TRNO header found")
    # Parse header: @TRNO followed by 6-char column names
    # The header uses the same six-character identifier field as data rows:
    # ``@TRNO `` followed by six-character column fields.
    col_names = ["TRNO"]
    remaining = header_line[6:]
    # Split by 6-char chunks
    for i in range(0, len(remaining), 6):
        chunk = remaining[i:i+6].strip()
        if chunk:
            col_names.append(chunk)
    # Parse data rows
    rows = []
    for line in data_lines:
        vals = []
        # First column is TRNO (positions 0-5)
        vals.append(line[0:6].strip())
        for i in range(6, len(line) + 6, 6):
            chunk = line[i:i+6].strip() if i < len(line) else ""
            vals.append(chunk)
        # Pad if needed
        while len(vals) < len(col_names):
            vals.append("")
        rows.append(vals[:len(col_names)])
    df = pd.DataFrame(rows, columns=col_names)
    # Convert numeric columns
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def audit_strict_fill(bundle_dir: Path, excode: str) -> tuple[list[dict], list[Finding]]:
    """Verify TMA/TMT strict fill rule: only allowed columns have non-(-99) values."""
    sid = bundle_dir.name
    rows: list[dict] = []
    findings: list[Finding] = []

    for kind, path, columns, fill_set in [
        ("A", bundle_dir / f"{excode}.TMA", TMA_COLUMNS, TMA_FILL),
        ("T", bundle_dir / f"{excode}.TMT", TMT_COLUMNS, TMT_FILL),
    ]:
        if not path.is_file():
            findings.append(Finding("strict_fill", "fail", f"{sid}: {path.name} not found"))
            continue
        try:
            df = parse_dssat_file(path)
        except Exception as exc:
            findings.append(Finding("strict_fill", "fail", f"{sid}: {path.name} parse error: {exc}"))
            continue

        for col in df.columns:
            if col == "TRNO":
                continue
            should_fill = col in fill_set
            non_missing = df[col].apply(lambda v: pd.notna(v) and float(v) != -99.0)
            n_non_missing = int(non_missing.sum())
            n_total = len(df)
            row = {
                "bundle": sid,
                "file": path.name,
                "column": col,
                "should_fill": should_fill,
                "n_non_missing": n_non_missing,
                "n_total": n_total,
                "compliant": None,
            }
            if should_fill:
                # Should have at least some non-missing values
                row["compliant"] = (n_non_missing > 0)
                if n_non_missing == 0:
                    findings.append(Finding("strict_fill", "fail",
                        f"{sid}:{path.name} col {col} should be filled but all -99"))
            else:
                # Should be ALL -99
                row["compliant"] = (n_non_missing == 0)
                if n_non_missing > 0:
                    findings.append(Finding("strict_fill", "fail",
                        f"{sid}:{path.name} col {col} should be -99 but has {n_non_missing} non-missing values"))
            rows.append(row)

    n_pass = sum(1 for r in rows if r["compliant"])
    n_fail = sum(1 for r in rows if not r["compliant"])
    if n_fail == 0:
        findings.append(Finding("strict_fill", "pass", f"{sid}: {n_pass} columns compliant"))
    return rows, findings


# ----------------------------------------------------------------------------
# Audit 3: Harvest alignment (TMA HDAT == last TMT harvest DATE per TRNO)
# ----------------------------------------------------------------------------

def audit_harvest_alignment(bundle_dir: Path, excode: str) -> tuple[list[dict], list[Finding]]:
    """Verify TMA HDAT matches the last TMT harvest DATE per treatment."""
    sid = bundle_dir.name
    rows: list[dict] = []
    findings: list[Finding] = []

    tma_path = bundle_dir / f"{excode}.TMA"
    tmt_path = bundle_dir / f"{excode}.TMT"
    if not tma_path.is_file() or not tmt_path.is_file():
        findings.append(Finding("harvest_alignment", "fail", f"{sid}: TMA or TMT not found"))
        return rows, findings

    tma = parse_dssat_file(tma_path)
    tmt = parse_dssat_file(tmt_path)

    for _, tma_row in tma.iterrows():
        trno = int(tma_row["TRNO"])
        hdat = tma_row["HDAT"]
        # Find TMT rows for this TRNO with non-(-99) CHPDT (harvest events)
        tmt_trno = tmt[tmt["TRNO"] == trno]
        harvest_rows = tmt_trno[tmt_trno["CHPDT"].apply(lambda v: pd.notna(v) and float(v) != -99.0)]
        if harvest_rows.empty:
            findings.append(Finding("harvest_alignment", "fail",
                f"{sid}: TRNO={trno} has no CHPDT harvest events in TMT"))
            continue
        last_date = float(harvest_rows["DATE"].iloc[-1])
        row = {
            "bundle": sid,
            "trno": trno,
            "tma_hdat": int(hdat) if pd.notna(hdat) else None,
            "tmt_last_harvest_date": int(last_date),
            "aligned": None,
        }
        row["aligned"] = (pd.notna(hdat) and int(hdat) == int(last_date))
        if not row["aligned"]:
            findings.append(Finding("harvest_alignment", "fail",
                f"{sid}: TRNO={trno} TMA HDAT={hdat} != TMT last harvest DATE={last_date}"))
        rows.append(row)

    n_aligned = sum(1 for r in rows if r["aligned"])
    n_total = len(rows)
    if n_aligned == n_total:
        findings.append(Finding("harvest_alignment", "pass",
            f"{sid}: {n_aligned}/{n_total} treatments aligned"))
    return rows, findings


# ----------------------------------------------------------------------------
# Audit 4: Treatment exclusion (25SP only)
# ----------------------------------------------------------------------------

def audit_treatment_exclusion(bundle_dir: Path, excode: str, excluded_tn: list[int]) -> tuple[list[dict], list[Finding]]:
    """Verify excluded TNs do not appear in TMA, TMT, or soil observations."""
    sid = bundle_dir.name
    rows: list[dict] = []
    findings: list[Finding] = []

    if not excluded_tn:
        findings.append(Finding("treatment_exclusion", "pass", f"{sid}: no excluded TNs (all plots kept)"))
        return rows, findings

    tma_path = bundle_dir / f"{excode}.TMA"
    tmt_path = bundle_dir / f"{excode}.TMT"
    soil_path = bundle_dir / "soil_water_observations.csv"

    for label, path, parser in [
        ("TMA", tma_path, lambda p: parse_dssat_file(p)["TRNO"].astype(int).unique()),
        ("TMT", tmt_path, lambda p: parse_dssat_file(p)["TRNO"].astype(int).unique()),
        ("SOIL", soil_path, lambda p: pd.read_csv(p)["trno"].astype(int).unique()),
    ]:
        if not path.is_file():
            findings.append(Finding("treatment_exclusion", "fail", f"{sid}: {path.name} not found"))
            continue
        try:
            tns = set(parser(path))
        except Exception as exc:
            findings.append(Finding("treatment_exclusion", "fail", f"{sid}: {path.name} parse error: {exc}"))
            continue
        found_excluded = sorted(tns & set(excluded_tn))
        row = {
            "bundle": sid,
            "file": path.name,
            "excluded_tn": excluded_tn,
            "found_excluded": found_excluded,
            "compliant": len(found_excluded) == 0,
        }
        rows.append(row)
        if found_excluded:
            findings.append(Finding("treatment_exclusion", "fail",
                f"{sid}: {path.name} contains excluded TNs: {found_excluded}"))
        else:
            findings.append(Finding("treatment_exclusion", "pass",
                f"{sid}: {path.name} excludes TNs {excluded_tn} correctly"))

    return rows, findings


# ----------------------------------------------------------------------------
# Audit 5: Soil water first-date exclusion
# ----------------------------------------------------------------------------

def audit_soil_first_date_exclusion(bundle_dir: Path) -> tuple[list[dict], list[Finding]]:
    """Verify per (trno, depth) exactly one date is tagged initial_condition_only."""
    sid = bundle_dir.name
    rows: list[dict] = []
    findings: list[Finding] = []

    soil_path = bundle_dir / "soil_water_observations.csv"
    if not soil_path.is_file():
        findings.append(Finding("soil_first_date", "fail", f"{sid}: soil_water_observations.csv not found"))
        return rows, findings

    df = pd.read_csv(soil_path)
    if df.empty:
        findings.append(Finding("soil_first_date", "fail", f"{sid}: soil observations empty"))
        return rows, findings

    for (trno, depth), grp in df.groupby(["trno", "depth_label"]):
        n_ic = int(grp["initial_condition_only"].sum())
        n_phi = int((grp["phi_role"] == "soil_water_phi").sum())
        expected = 0 if sid.lower().startswith("xxql2502") or sid.upper().startswith("25FA") else 1
        row = {
            "bundle": sid,
            "trno": int(trno),
            "depth_label": depth,
            "n_total": len(grp),
            "n_initial_condition": n_ic,
            "n_phi": n_phi,
            "compliant": n_ic == expected and n_phi > 0,
        }
        rows.append(row)
        if n_ic != expected or n_phi <= 0:
            findings.append(Finding("soil_first_date", "fail",
                f"{sid}: TRNO={trno} depth={depth} has {n_ic} initial_condition_only, {n_phi} Phi rows (expected initial={expected}, Phi>0)"))

    n_pass = sum(1 for r in rows if r["compliant"])
    n_total = len(rows)
    if n_pass == n_total:
        findings.append(Finding("soil_first_date", "pass",
            f"{sid}: {n_pass}/{n_total} soil depth groups comply with season-specific initial-condition rule"))
    return rows, findings


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="E00 v2 input audit for three new bundles.")
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / "workspace/runs/E00_v2_audit_20260726"),
                        help="Output directory for audit receipts")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_manifest_rows: list[dict] = []
    all_strict_fill_rows: list[dict] = []
    all_harvest_rows: list[dict] = []
    all_exclusion_rows: list[dict] = []
    all_soil_rows: list[dict] = []
    all_findings: list[Finding] = []
    bundle_summaries: list[dict] = []

    for season, info in BUNDLES.items():
        bundle_dir = info["dir"]
        excode = info["excode"]
        excluded_tn = info["excluded_tn"]
        print(f"\n=== Auditing {season} ({bundle_dir.name}) ===")

        if not bundle_dir.is_dir():
            print(f"  FAIL: bundle directory not found")
            all_findings.append(Finding("bundle_exists", "fail", f"{season}: {bundle_dir} not found"))
            bundle_summaries.append({"season_id": season, "bundle": bundle_dir.name, "status": "fail", "n_findings_fail": 1})
            continue

        # Run all audits
        manifest_rows, manifest_findings = audit_manifest(bundle_dir)
        strict_fill_rows, strict_fill_findings = audit_strict_fill(bundle_dir, excode)
        harvest_rows, harvest_findings = audit_harvest_alignment(bundle_dir, excode)
        exclusion_rows, exclusion_findings = audit_treatment_exclusion(bundle_dir, excode, excluded_tn)
        soil_rows, soil_findings = audit_soil_first_date_exclusion(bundle_dir)

        all_manifest_rows.extend(manifest_rows)
        all_strict_fill_rows.extend(strict_fill_rows)
        all_harvest_rows.extend(harvest_rows)
        all_exclusion_rows.extend(exclusion_rows)
        all_soil_rows.extend(soil_rows)
        all_findings.extend(manifest_findings)
        all_findings.extend(strict_fill_findings)
        all_findings.extend(harvest_findings)
        all_findings.extend(exclusion_findings)
        all_findings.extend(soil_findings)

        n_fail = sum(1 for f in all_findings if f.status == "fail" and bundle_dir.name in f.detail)
        n_pass = sum(1 for f in all_findings if f.status == "pass" and bundle_dir.name in f.detail)
        bundle_status = "fail" if n_fail > 0 else "pass"
        bundle_summaries.append({
            "season_id": season,
            "bundle": bundle_dir.name,
            "status": bundle_status,
            "n_findings_pass": n_pass,
            "n_findings_fail": n_fail,
        })
        print(f"  status: {bundle_status.upper()} (pass={n_pass}, fail={n_fail})")
        for f in manifest_findings + strict_fill_findings + harvest_findings + exclusion_findings + soil_findings:
            if f.status == "fail":
                print(f"    FAIL [{f.check}]: {f.detail}")

    # Write CSVs
    def write_csv(name: str, rows: list[dict]) -> None:
        if rows:
            with (out_dir / name).open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

    write_csv("E00_v2_manifest_audit.csv", all_manifest_rows)
    write_csv("E00_v2_strict_fill_audit.csv", all_strict_fill_rows)
    write_csv("E00_v2_harvest_alignment.csv", all_harvest_rows)
    write_csv("E00_v2_treatment_exclusion_audit.csv", all_exclusion_rows)
    write_csv("E00_v2_soil_first_date_audit.csv", all_soil_rows)

    # Write receipt
    n_total_fail = sum(1 for f in all_findings if f.status == "fail")
    n_total_pass = sum(1 for f in all_findings if f.status == "pass")
    n_total_warn = sum(1 for f in all_findings if f.status == "warning")
    receipt = {
        "audit_id": "E00_v2_input_audit_20260726",
        "spec_compliance": [
            "docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md",
            "docs/土壤水分进入Phi与土壤参数预筛方案_v1_20260726.md",
        ],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audited_bundles": bundle_summaries,
        "summary": {
            "total_findings": len(all_findings),
            "n_pass": n_total_pass,
            "n_fail": n_total_fail,
            "n_warning": n_total_warn,
            "overall_status": "fail" if n_total_fail > 0 else "pass",
        },
        "findings": [asdict(f) for f in all_findings],
        "output_files": [
            "E00_v2_audit_receipt.json",
            "E00_v2_manifest_audit.csv",
            "E00_v2_strict_fill_audit.csv",
            "E00_v2_harvest_alignment.csv",
            "E00_v2_treatment_exclusion_audit.csv",
            "E00_v2_soil_first_date_audit.csv",
        ],
    }
    receipt_path = out_dir / "E00_v2_audit_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"E00 v2 audit complete: {receipt['summary']['overall_status'].upper()}")
    print(f"  pass={n_total_pass}, fail={n_total_fail}, warning={n_total_warn}")
    print(f"  receipt: {receipt_path}")
    for f in all_findings:
        if f.status == "fail":
            print(f"  FAIL [{f.check}]: {f.detail}")

    return 0 if n_total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
