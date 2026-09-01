"""Audit 26SP TMX treatment, irrigation, fertilizer and IC provenance.

The audit derives treatment factors from the current TMX rather than trusting
the hand-written mapping CSV.  It is intended as an S0 gate before any new
nitrogen calibration.  No input file is modified.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.common.experiment_inputs import parse_filex
from tools.calibration.audit_three_season_n_response import irrigation_profiles


def _event_totals(path: Path, section_start: str, stop_prefix: str, value_index: int,
                  date_index: int, first_date: int) -> tuple[dict[int, float], dict[int, float]]:
    all_totals: dict[int, float] = {}
    early_totals: dict[int, float] = {}
    active = False
    ready = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        upper = stripped.upper()
        if upper.startswith(section_start.upper()):
            active = True
            continue
        if active and stripped.startswith("*") and not upper.startswith(section_start.upper()):
            break
        if not active or not stripped or stripped.startswith("!"):
            continue
        if stripped.startswith("@"):
            # Ignore irrigation profile headers (EFIR/IDEP/...) and begin only
            # after the event table header (@I IDATE or @F FDATE).
            ready = "DATE" in upper
            continue
        if not ready:
            continue
        fields = stripped.split()
        try:
            treatment = int(fields[0])
            date = int(fields[date_index])
            value = float(fields[value_index])
        except (ValueError, IndexError):
            continue
        if value < 0:
            continue
        all_totals[treatment] = all_totals.get(treatment, 0.0) + value
        if date <= first_date:
            early_totals[treatment] = early_totals.get(treatment, 0.0) + value
    return all_totals, early_totals


def _ic_totals(path: Path, max_depth: float = 60.0) -> dict[int, dict[str, float]]:
    active = False
    in_rows = False
    out: dict[int, dict[str, float]] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        upper = stripped.upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            active = True
            continue
        if active and stripped.startswith("*") and not upper.startswith("*INITIAL CONDITIONS"):
            break
        if not active or not stripped:
            continue
        if upper.startswith("@C") and "ICBL" in upper:
            in_rows = True
            continue
        if not in_rows or stripped.startswith("@") or stripped.startswith("!"):
            continue
        fields = stripped.split()
        if len(fields) < 5:
            continue
        try:
            treatment, depth = int(fields[0]), float(fields[1])
            sh2o, snh4, sno3 = map(float, fields[2:5])
        except ValueError:
            continue
        if depth > max_depth or depth < 0:
            continue
        row = out.setdefault(treatment, {"ic_depth_max_cm": 0.0, "ic_sh2o_sum": 0.0,
                                         "ic_snh4_sum": 0.0, "ic_sno3_sum": 0.0,
                                         "ic_rows_0_60": 0.0})
        row["ic_depth_max_cm"] = max(row["ic_depth_max_cm"], depth)
        row["ic_sh2o_sum"] += sh2o
        row["ic_snh4_sum"] += snh4
        row["ic_sno3_sum"] += sno3
        row["ic_rows_0_60"] += 1
    return out


def audit(tmx: Path, mapping_csv: Path, out_csv: Path, first_date: int = 26146) -> pd.DataFrame:
    factors = parse_filex(tmx)["treatments"]
    irrigation = irrigation_profiles(tmx)
    # Irrigation rows are keyed by MI (irrigation management level), whereas
    # fertilizer rows are keyed by MF (fertilizer level), not by TN.
    irr_all, irr_early = _event_totals(tmx, "*IRRIGATION AND WATER MANAGEMENT", "*", 3, 1, first_date)
    fert_all, fert_early = _event_totals(tmx, "*FERTILIZERS (INORGANIC)", "*", 5, 1, first_date)
    ic = _ic_totals(tmx)
    expected = pd.read_csv(mapping_csv)
    expected = expected[expected["season_id"].eq("26SP")].copy()
    rows = []
    for treatment, f in sorted(factors.items()):
        mi, mf = int(f["MI"]), int(f["MF"])
        profile = irrigation.get(mi, {})
        level = expected.loc[expected["treatment"].eq(treatment), "nitrogen_level"]
        water = expected.loc[expected["treatment"].eq(treatment), "water_level"]
        dose = expected.loc[expected["treatment"].eq(treatment), "nitrogen_kg_ha"]
        irr = expected.loc[expected["treatment"].eq(treatment), "irrigation_mm"]
        row = {
            "season_id": "26SP", "treatment": treatment, "MI": mi, "MF": mf,
            "tmx_water_name": profile.get("name", ""),
            "mapping_water_level": water.iloc[0] if len(water) else "",
            "mapping_nitrogen_level": level.iloc[0] if len(level) else "",
            "irrigation_total_mm_tmx": irr_all.get(mi, 0.0),
            "irrigation_to_first_harvest_mm_tmx": irr_early.get(mi, 0.0),
            "mapping_irrigation_mm": float(irr.iloc[0]) if len(irr) else float("nan"),
            "fertilizer_N_total_tmx": fert_all.get(mf, 0.0),
            "fertilizer_N_to_first_harvest_tmx": fert_early.get(mf, 0.0),
            "mapping_nitrogen_kg_ha": float(dose.iloc[0]) if len(dose) else float("nan"),
        }
        row.update(ic.get(treatment, {}))
        row["water_mapping_match"] = row["tmx_water_name"] == row["mapping_water_level"]
        row["irrigation_mapping_match"] = abs(row["irrigation_total_mm_tmx"] - row["mapping_irrigation_mm"]) < 1e-6
        row["fertilizer_mapping_match"] = abs(row["fertilizer_N_total_tmx"] - row["mapping_nitrogen_kg_ha"]) < 1e-6
        rows.append(row)
    frame = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return frame


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tmx", type=Path, required=True)
    p.add_argument("--mapping-csv", type=Path, required=True)
    p.add_argument("--out-csv", type=Path, required=True)
    p.add_argument("--first-harvest-date", type=int, default=26146)
    a = p.parse_args()
    frame = audit(a.tmx, a.mapping_csv, a.out_csv, a.first_harvest_date)
    checks = ["water_mapping_match", "irrigation_mapping_match", "fertilizer_mapping_match"]
    print(f"rows={len(frame)}", flush=True)
    for col in checks:
        print(f"{col}={int(frame[col].sum())}/{len(frame)}", flush=True)
    return 0 if frame[checks].all(axis=None) else 2


if __name__ == "__main__":
    raise SystemExit(main())
