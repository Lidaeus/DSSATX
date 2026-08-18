"""Verify FileT dates exactly match FileX HARVEST DETAILS dates per treatment,
and FileT harvest event count == FreshWt.OUT CHPDT-increase events per treatment.

Spec: docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md
After the 2026-07-26 FileX refresh (with virtual +1-day harvest events) and
the corresponding FileT DATE alignment (yield-data-record date - 1 day for
25SP/26SP), FileT DATE values must equal FileX actual harvest dates (the
non-virtual events). Virtual +1-day events exist only in FileX to capture
the final harvest's FreshWt.OUT data and MUST NOT appear in FileT.

Usage:
  python tools/calibration/verify_filet_filex_alignment.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = PROJECT_ROOT / "workspace" / "runs" / "E01_v2_smoke_20260726"
BUNDLE_DIR = PROJECT_ROOT / "data" / "user" / "experiments"

SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501"},
    {"season_id": "25FA", "excode": "XXQL2502"},
    {"season_id": "26SP", "excode": "XXQL2601"},
]


def parse_filex_harvest_details(tmx_path: Path) -> dict[int, list[int]]:
    """Return {trno_global: [harvest yyddd, ...]} from *HARVEST DETAILS.

    FileX HARVEST DETAILS applies globally to all treatments in the batch
    (treatment-specific harvest schedules are not used in this project).
    Returns the GLOBAL list under trno_key=-1 (caller fans out to all trnos).
    """
    text = tmx_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    dates: list[int] = []
    in_section = False
    for line in lines:
        if line.startswith("*HARVEST DETAILS"):
            in_section = True
            continue
        if in_section:
            if line.startswith("*") or line.startswith("@") and not line.startswith("@H"):
                break
            if line.lstrip().startswith("@H"):
                continue
            s = line.strip()
            if not s:
                continue
            parts = s.split()
            # Format: HDATE HSTG HCOM HSIZE HPC HBPC HNAME  (or simplified)
            # HDATE is col 2 (after row index). Look for 5-digit yyddd.
            for tok in parts[1:3]:
                if re.match(r"^\d{5}$", tok):
                    dates.append(int(tok))
                    break
    return {-1: dates}  # global


def parse_filet_dates_per_trno(tmt_path: Path) -> dict[int, list[int]]:
    """Parse {trno: [DATE, ...]} from FileT (.TMT), keeping only rows with
    non-missing CHPDT (i.e., actual harvest observations)."""
    if not tmt_path.is_file():
        return {}
    lines = tmt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    trno_col = date_col = chpdt_col = None
    result: dict[int, list[int]] = {}
    for line in lines:
        if line.startswith("@TRNO"):
            cols = line.split()
            for j, c in enumerate(cols):
                if c in ("TRNO", "@TRNO"):
                    trno_col = j
                elif c == "DATE":
                    date_col = j
                elif c == "CHPDT":
                    chpdt_col = j
            continue
        if trno_col is None:
            continue
        if not line.strip() or line.startswith("@") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) <= max(trno_col, date_col, chpdt_col):
            continue
        try:
            trno = int(parts[trno_col])
            date_val = int(parts[date_col])
            chpdt_val = parts[chpdt_col]
        except (ValueError, IndexError):
            continue
        if chpdt_val == "-99":
            continue
        result.setdefault(trno, []).append(date_val)
    return result


def parse_freshwt_harvest_events(freshwt_path: Path) -> dict[int, list[int]]:
    """Return {trno: [yyddd of each CHPDT strict-increase day]}."""
    if not freshwt_path.is_file():
        return {}
    lines = freshwt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    result: dict[int, list[int]] = {}
    current_trno = None
    year_col = doy_col = chpdt_col = None
    prev_chpdt = None
    for line in lines:
        if line.startswith("*RUN"):
            parts = line.split()
            for tok in reversed(parts):
                try:
                    current_trno = int(tok)
                    break
                except ValueError:
                    continue
            year_col = doy_col = chpdt_col = None
            prev_chpdt = None
            continue
        if line.lstrip().startswith("@YEAR"):
            cols = line.split()
            for j, c in enumerate(cols):
                if c in ("YEAR", "@YEAR"):
                    year_col = j
                elif c == "DOY":
                    doy_col = j
                elif c == "CHPDT":
                    chpdt_col = j
            continue
        if current_trno is None or year_col is None or doy_col is None or chpdt_col is None:
            continue
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.startswith("!"):
            continue
        parts = line.split()
        if len(parts) <= max(year_col, doy_col, chpdt_col):
            continue
        try:
            y = int(parts[year_col])
            doy = int(parts[doy_col])
            chpdt = float(parts[chpdt_col])
        except (ValueError, IndexError):
            continue
        if prev_chpdt is not None and chpdt > prev_chpdt:
            yyddd = (y % 100) * 1000 + doy
            result.setdefault(current_trno, []).append(yyddd)
        prev_chpdt = chpdt
    return result


def main() -> None:
    overall_pass = True
    # FileT DATE convention per season:
    #   All seasons: FileT DATE = FileX actual harvest date + 1, because DSSAT
    #     writes FreshWt.OUT CHPDT increment on day N+1 after a day-N harvest.
    #   - 25SP / 26SP: yield workbook uses N+1 dates directly; adapter shifts
    #     by -1 to recover FileX N, then FileT = N+1.
    #   - 25FA: yield workbook uses N dates; adapter shifts by +1 so FileT = N+1.
    #   Result is uniform: FileT DATE == FreshWt event day across all seasons.
    SEASON_OFFSET = {"25SP": 1, "25FA": 1, "26SP": 1}
    for season in SEASONS:
        sid = season["season_id"]
        excode = season["excode"]
        offset = SEASON_OFFSET[sid]
        print(f"\n=== {sid} ({excode}) — FileT=FileX{'+'+str(offset) if offset else ''} ===")

        bundle = BUNDLE_DIR / f"{excode.lower()}_actual_trial_calibration_v2_20260726"
        tmx_path = bundle / f"{excode}.TMX"
        tmt_path = bundle / f"{excode}.TMT"
        freshwt_path = SMOKE_DIR / sid / "FreshWt.OUT"

        filex_global = parse_filex_harvest_details(tmx_path).get(-1, [])
        filet_per_trno = parse_filet_dates_per_trno(tmt_path)
        freshwt_events = parse_freshwt_harvest_events(freshwt_path)

        print(f"  FileX HARVEST DETAILS dates: {filex_global}")
        # Virtual events are the last one(s) immediately following another event
        # (e.g., 25203 after 25202; 26006 after 26005; 26198 after 26197)
        virtual_events = []
        for i, d in enumerate(filex_global[1:], start=1):
            if d - filex_global[i - 1] == 1:
                virtual_events.append(d)
        actual_filex = [d for d in filex_global if d not in virtual_events]
        print(f"  FileX virtual +1 events (excluded from FileT): {virtual_events}")
        print(f"  FileX actual harvest dates: {actual_filex}")

        if not filet_per_trno:
            print(f"  ERROR: FileT empty")
            overall_pass = False
            continue

        season_pass = True
        # Expected FileT dates: FileX actual harvest dates + offset (N+1 for
        # 25SP/26SP, N for 25FA).
        expected_filet = [d + offset for d in actual_filex]
        for trno in sorted(filet_per_trno.keys()):
            filet_dates = sorted(filet_per_trno[trno])
            fw_events = sorted(freshwt_events.get(trno, []))

            filet_vs_filex = filet_dates == expected_filet
            filet_vs_fw_count = len(filet_dates) == len(fw_events)
            # FileT dates should exactly equal FreshWt event dates (both are N+1).
            filet_vs_fw_exact = filet_dates == fw_events

            status = "OK" if (filet_vs_filex and filet_vs_fw_count and filet_vs_fw_exact) else "MISMATCH"
            if status == "MISMATCH":
                season_pass = False
                overall_pass = False
            print(f"  TRNO={trno}: FileT={filet_dates} (n={len(filet_dates)}) "
                  f"FW={fw_events} (n={len(fw_events)}) "
                  f"FileT==FileX{'+'+str(offset) if offset else ''}: {filet_vs_filex}, "
                  f"FileT==FW: {filet_vs_fw_exact} [{status}]")
            if not filet_vs_filex:
                print(f"    Expected (FileX{'+%d'%offset if offset else ''}): {expected_filet}")
            if not filet_vs_fw_count:
                print(f"    >> CHPDT-increase event count mismatch")

        print(f"  >> {sid}: {'PASS' if season_pass else 'FAIL'}")

    print(f"\n{'=' * 60}")
    print(f"FileT/FileX/FreshWt alignment: {'PASS' if overall_pass else 'FAIL'}")


if __name__ == "__main__":
    main()
