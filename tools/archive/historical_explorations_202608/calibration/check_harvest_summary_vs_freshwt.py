"""Compare Summary.OUT harvest yield vs FreshWt.OUT final cumulative CHPDT.

User question (2026-07-26):
  DSSAT 鲜果采收事件设于第 N 日，数据在第 N+1 日才出现。
  最后一次采收结束后模拟即结束，那么最后一次采收的数据会不会
  出现在总结文件里？即总结文件的产量是否大于连续采收序列数据
  里的产量？若大于，说明终收数据应以总结文件为准。

This script parses both Summary.OUT and FreshWt.OUT for each season and
compares per-treatment:
  - Summary.OUT: HWAM, HWAH, PWAM, H#AM, FPWAM (and fresh weight cols)
  - FreshWt.OUT: final CHPDT (cum. dry har. pod weight),
                 final CHFPW (cum. fresh pod weight),
                 final CMFNM (cum. mature fruit number),
                 n_harvest_events (CHPDT increase days)

Output: per-treatment comparison table + season-level verdict.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = PROJECT_ROOT / "workspace" / "runs" / "E01_v2_soil_smoke_20260726"

SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501"},
    {"season_id": "25FA", "excode": "XXQL2502"},
    {"season_id": "26SP", "excode": "XXQL2601"},
]


def parse_summary_out(summary_path: Path) -> dict[int, dict]:
    """Parse Summary.OUT to extract per-treatment harvest-related fields.

    Summary.OUT uses a header line starting with '@'. The TNAM field may
    contain spaces/quotes. Strategy: TNAM is the ONLY field that can
    contain spaces. All columns before TNAM (RUNNO..EXNAME, 8 tokens) and
    after TNAM (FNAM..CRST) are space-free. So we take the first 8 tokens,
    the last (H-9) tokens, and join the middle as TNAM.
    """
    if not summary_path.is_file():
        return {}
    lines = summary_path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_cols: list[str] | None = None
    results: dict[int, dict] = {}

    for line in lines:
        s = line.rstrip()
        if not s.strip():
            continue
        if s.lstrip().startswith("@") and "TRNO" in s:
            header_cols = s.split()
            continue
        if header_cols is None:
            continue
        if s.startswith("*") or s.startswith("!"):
            continue

        parts = s.split()
        n_header = len(header_cols)
        n_parts = len(parts)

        # Header starts with "@" as a separate token (verified from actual
        # Summary.OUT). Data lines do NOT have a leading "@". So header has
        # one extra token at index 0. TNAM is at header index 9 (after
        # @, RUNNO, TRNO, R#, O#, P#, CR, MODEL, EXNAME). In data, the
        # TNAM starts at index 8. After-TNAM columns: header indices 10..n_header-1,
        # which is (n_header - 10) columns. If n_parts > (n_header - 1), the
        # extra tokens belong to TNAM.
        n_before_tnam_data = 8  # data indices 0-7: RUNNO TRNO R# O# P# CR MODEL EXNAME
        n_after_tnam_data = n_header - 10  # data columns matching header indices 10..n_header-1
        expected_without_tnam = n_before_tnam_data + n_after_tnam_data
        if n_parts > expected_without_tnam:
            before = parts[:n_before_tnam_data]
            after = parts[n_parts - n_after_tnam_data:]
            tnam_tokens = parts[n_before_tnam_data:n_parts - n_after_tnam_data]
            parts = before + [" ".join(tnam_tokens)] + after

        # Pad if still short
        if len(parts) < n_header - 1:
            parts += ["-99"] * (n_header - 1 - len(parts))

        # Build row dict. Drop header "@" token (index 0) since data has no "@".
        row = dict(zip(header_cols[1:], parts[:n_header - 1]))
        try:
            trno = int(row.get("TRNO", "-99"))
        except ValueError:
            continue
        if trno <= 0:
            continue

        def _f(name: str) -> float:
            try:
                return float(row.get(name, "-99"))
            except (ValueError, TypeError):
                return -99.0

        def _i(name: str) -> int:
            try:
                return int(float(row.get(name, "-99")))
            except (ValueError, TypeError):
                return -99

        results[trno] = {
            "TRNO": trno,
            "HDAT": _i("HDAT"),
            "HWAM": _f("HWAM"),       # dry harvested weight, kg/ha
            "HWAH": _f("HWAH"),       # adjusted harvested weight, kg/ha
            "PWAM": _f("PWAM"),       # pod weight at maturity, kg/ha
            "H#AM": _i("H#AM"),       # harvest number
            "HIAM": _f("HIAM"),       # harvest index
            "CWAM": _f("CWAM"),       # above-ground biomass, kg/ha
            "FCWAM": _f("FCWAM"),     # fresh canopy weight
            "FHWAM": _f("FHWAM"),     # fresh harvest weight
            "FPWAM": _f("FPWAM"),     # fresh pod weight at maturity
            "HWAHF": _f("HWAHF"),
            "FBWAH": _f("FBWAH"),
        }
    return results


def parse_freshwt_final(freshwt_path: Path) -> dict[int, dict]:
    """Parse FreshWt.OUT to extract the final (last-day) cumulative values
    and the list of harvest event dates per treatment.

    Returns {trno: {final_chpdt, final_chfpw, final_cmfnum, harvest_events}}.
    """
    if not freshwt_path.is_file():
        return {}
    lines = freshwt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    results: dict[int, dict] = {}
    current_trno: int | None = None
    year_col = doy_col = chpdt_col = chfpw_col = cmfnm_col = None
    prev_chpdt: float | None = None
    harvest_events: list[int] = []
    last_year = last_doy = None
    last_chpdt = last_chfpw = last_cmfnum = None

    for line in lines:
        if line.startswith("*RUN"):
            # Save previous treatment
            if current_trno is not None:
                results[current_trno] = {
                    "final_chpdt": last_chpdt if last_chpdt is not None else -99.0,
                    "final_chfpw": last_chfpw if last_chfpw is not None else -99.0,
                    "final_cmfnum": last_cmfnum if last_cmfnum is not None else -99,
                    "harvest_events": list(harvest_events),
                    "last_yyddd": (last_year % 100) * 1000 + last_doy
                                  if last_year and last_doy else -99,
                }
            parts = line.split()
            trno_candidate: int | None = None
            for tok in reversed(parts):
                try:
                    trno_candidate = int(tok)
                    break
                except ValueError:
                    continue
            current_trno = trno_candidate
            year_col = doy_col = chpdt_col = chfpw_col = cmfnm_col = None
            prev_chpdt = None
            harvest_events = []
            last_year = last_doy = None
            last_chpdt = last_chfpw = last_cmfnum = None
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
                elif c == "CHFPW":
                    chfpw_col = j
                elif c == "CMFNM":
                    cmfnm_col = j
            continue

        if current_trno is None or year_col is None or doy_col is None:
            continue
        if not line.strip() or line.startswith("@") or line.startswith("*") or line.startswith("!"):
            continue

        parts = line.split()
        max_col_needed = max([c for c in [year_col, doy_col, chpdt_col, chfpw_col, cmfnm_col]
                              if c is not None])
        if len(parts) <= max_col_needed:
            continue
        try:
            year_val = int(parts[year_col])
            doy_val = int(parts[doy_col])
            chpdt_val = float(parts[chpdt_col]) if chpdt_col is not None else -99.0
            chfpw_val = float(parts[chfpw_col]) if chfpw_col is not None else -99.0
            cmfnum_val = float(parts[cmfnm_col]) if cmfnm_col is not None else -99.0
        except (ValueError, IndexError):
            continue

        # Detect harvest event (strict increase in CHPDT)
        if prev_chpdt is not None and chpdt_val > prev_chpdt:
            yyddd = (year_val % 100) * 1000 + doy_val
            harvest_events.append(yyddd)
        prev_chpdt = chpdt_val

        last_year = year_val
        last_doy = doy_val
        last_chpdt = chpdt_val
        last_chfpw = chfpw_val
        last_cmfnum = int(cmfnum_val) if cmfnum_val >= 0 else -99

    # Save last treatment
    if current_trno is not None:
        results[current_trno] = {
            "final_chpdt": last_chpdt if last_chpdt is not None else -99.0,
            "final_chfpw": last_chfpw if last_chfpw is not None else -99.0,
            "final_cmfnum": last_cmfnum if last_cmfnum is not None else -99,
            "harvest_events": list(harvest_events),
            "last_yyddd": (last_year % 100) * 1000 + last_doy
                          if last_year and last_doy else -99,
        }
    return results


def main() -> None:
    print("=" * 100)
    print("Summary.OUT vs FreshWt.OUT harvest comparison")
    print("User question: does the final harvest appear in Summary but not FreshWt?")
    print("=" * 100)

    for season in SEASONS:
        sid = season["season_id"]
        run_dir = SMOKE_DIR / sid
        summary_path = run_dir / "Summary.OUT"
        freshwt_path = run_dir / "FreshWt.OUT"

        print(f"\n### {sid} ({season['excode']}) ###")
        if not summary_path.is_file():
            print(f"  SKIP: {summary_path} not found")
            continue

        summary = parse_summary_out(summary_path)
        freshwt = parse_freshwt_final(freshwt_path) if freshwt_path.is_file() else {}

        print(f"  Summary.OUT: {len(summary)} treatments")
        print(f"  FreshWt.OUT: {len(freshwt)} treatments")

        # Per-treatment comparison
        print(f"\n  {'TRNO':>4} {'HDAT':>8} | {'SumHWAM':>8} {'SumHWAH':>8} {'SumPWAM':>8} "
              f"{'SumH#AM':>8} {'SumFPWAM':>9} | {'FW_CHPDT':>9} {'FW_CHFPW':>9} "
              f"{'FW_CMFNM':>8} {'FW_NEVT':>7} {'FW_LAST':>8} | {'CHPDT<HWAM?':>11}")
        print(f"  {'-'*4} {'-'*8} | {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*9} | "
              f"{'-'*9} {'-'*9} {'-'*8} {'-'*7} {'-'*8} | {'-'*11}")

        n_summary_gt_freshwt = 0
        n_summary_eq_freshwt = 0
        n_summary_lt_freshwt = 0
        n_no_harvest_event_on_last = 0

        for trno in sorted(summary.keys()):
            s = summary[trno]
            f = freshwt.get(trno, {})

            fw_chpdt = f.get("final_chpdt", -99.0)
            fw_chfpw = f.get("final_chfpw", -99.0)
            fw_cmfnum = f.get("final_cmfnum", -99)
            fw_events = f.get("harvest_events", [])
            fw_last = f.get("last_yyddd", -99)

            sum_hwam = s["HWAM"]
            sum_hwah = s["HWAH"]
            sum_pwam = s["PWAM"]
            sum_ham = s["H#AM"]
            sum_fpwam = s["FPWAM"]

            # Compare cumulative dry harvest: Summary HWAM vs FreshWt CHPDT
            if fw_chpdt > 0 and sum_hwam > 0:
                if sum_hwam > fw_chpdt:
                    verdict = "HWAM>CHPDT"
                    n_summary_gt_freshwt += 1
                elif abs(sum_hwam - fw_chpdt) < 0.5:
                    verdict = "equal"
                    n_summary_eq_freshwt += 1
                else:
                    verdict = "HWAM<CHPDT"
                    n_summary_lt_freshwt += 1
            else:
                verdict = "-"

            # Check if the last harvest event in FreshWt is on the last day
            # (if so, the final harvest data DID appear in FreshWt)
            if fw_events and fw_last in fw_events:
                last_event_note = "LAST=EVT"
            elif fw_events:
                last_event_note = f"last_evt={fw_events[-1]}"
            else:
                last_event_note = "no_evts"

            print(f"  {trno:>4} {s['HDAT']:>8} | {sum_hwam:>8.1f} {sum_hwah:>8.1f} "
                  f"{sum_pwam:>8.1f} {sum_ham:>8} {sum_fpwam:>9.1f} | "
                  f"{fw_chpdt:>9.1f} {fw_chfpw:>9.1f} {fw_cmfnum:>8} "
                  f"{len(fw_events):>7} {fw_last:>8} | {verdict:>11}  {last_event_note}")

        total = n_summary_gt_freshwt + n_summary_eq_freshwt + n_summary_lt_freshwt
        print(f"\n  Verdict ({sid}):")
        print(f"    HWAM > CHPDT (Summary captures final harvest missing from FreshWt): "
              f"{n_summary_gt_freshwt}/{total}")
        print(f"    HWAM = CHPDT (Summary matches FreshWt cumulative):                  "
              f"{n_summary_eq_freshwt}/{total}")
        print(f"    HWAM < CHPDT (FreshWt cumulative exceeds Summary):                  "
              f"{n_summary_lt_freshwt}/{total}")

        if n_summary_gt_freshwt > 0:
            print(f"  >> CONFIRMED: Summary.OUT captures final-harvest data NOT in FreshWt.OUT")
            print(f"  >> Final harvest yield should use Summary.OUT as the authoritative source.")
        elif n_summary_eq_freshwt == total:
            print(f"  >> Summary.OUT matches FreshWt.OUT cumulative (no missing final harvest).")
        elif n_summary_lt_freshwt > 0:
            print(f"  >> FreshWt.OUT CHPDT > Summary.OUT HWAM (units or semantics differ).")


if __name__ == "__main__":
    main()
