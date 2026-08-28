"""Replace FileX INITIAL CONDITIONS mineral N (SNH4/SNO3, 20/40/60 cm) with
pre-season measured values from the two reference workbooks (2026-08-20).

Sources (sheet 剔异常平均版, outlier-removed means):
  - 25SP硝态氮铵态氮参考.xlsx       -> plots 2-13  (last-season-end N, prior trial)
  - 26SP和25FA硝态氮铵态氮参考.xlsx -> plots 1-12  (cucumber-trial-end N, shared)

New versioned bundles (sources untouched, SHA manifests preserved by derivation):
  xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820  <- v2_20260819
  xxql2502_actual_trial_calibration_v8_measuredn_20260820    <- v7_20260729
  xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820  <- v2_20260819

Rules: SH2O untouched; 80/100 cm untouched; 25SP IC1/IC14 untouched;
26SP special IC55 untouched; six-char fields with ~5 significant digits.

Usage:
    python tools/experiments/apply_measuredn_v3_20260820.py --dry-run | --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "data/user/experiments"
AUDIT_DIR = ROOT / "workspace/reports/measuredn_replacement_20260820"

SEASONS = {
    "25SP": {
        "xlsx": ROOT / "data/user/ref/25SP硝态氮铵态氮参考.xlsx",
        "plots": list(range(2, 14)),
        "src_bundle": "xxql2501_repfilter_measuredmoisture_v2_20260819",
        "new_bundle": "xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820",
        "excode": "XXQL2501",
    },
    "25FA": {
        "xlsx": ROOT / "data/user/ref/26SP和25FA硝态氮铵态氮参考.xlsx",
        "plots": list(range(1, 13)),
        "src_bundle": "xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "new_bundle": "xxql2502_actual_trial_calibration_v8_measuredn_20260820",
        "excode": "XXQL2502",
    },
    "26SP": {
        "xlsx": ROOT / "data/user/ref/26SP和25FA硝态氮铵态氮参考.xlsx",
        "plots": list(range(1, 13)),
        "src_bundle": "xxql2601_repfilter_measuredmoisture_v2_20260819",
        "new_bundle": "xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820",
        "excode": "XXQL2601",
    },
}
LAYER_MAP = {"0-20": "20", "20-40": "40", "40-60": "60"}
NO3_COL = "硝态氮纯氮-剔异常平均"
NH4_COL = "铵态氮-剔异常平均"
NO3_REP = "硝态氮有效重复数"
NH4_REP = "铵态氮有效重复数"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmt6(value: float) -> str:
    """Six-char field, ~5 significant digits, FileX style (no leading zero)."""
    for sig in (5, 4, 3, 2, 1):
        text = f"{value:.{sig}g}"
        if text.startswith("0."):
            text = text[1:]
        if len(text) <= 6:
            return f"{text:>6}"
    return f"{value:>6.0f}"


def _fit(v: float, max_len: int = 5) -> str:
    for sig in (5, 4, 3, 2, 1):
        text = f"{v:.{sig}g}"
        if text.startswith("0."):
            text = text[1:]
        elif text.startswith("-0."):
            text = "-." + text[3:]
        if len(text) <= max_len:
            return text
    return f"{v:.0f}"[:max_len]


def fmt_pair(nh4: float, no3: float) -> tuple[str, str]:
    """Adjacent six-column fields formatted with max 5 chars for leading space in 6 cols."""
    return f"{_fit(nh4, 5):>6}", f"{_fit(no3, 5):>6}"


def load_measurements(season: str) -> pd.DataFrame:
    cfg = SEASONS[season]
    frame = pd.read_excel(cfg["xlsx"], sheet_name="剔异常平均版")
    frame["小区"] = pd.to_numeric(frame["小区"], errors="raise").astype(int)
    frame = frame[frame["小区"].isin(cfg["plots"])].copy()
    frame["layer"] = frame["土层"].astype(str).map(LAYER_MAP)
    if frame["layer"].isna().any():
        raise ValueError(f"{season}: unexpected soil layers {sorted(frame['土层'].unique())}")
    for col in (NO3_COL, NH4_COL):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
        if (frame[col] <= 0).any():
            raise ValueError(f"{season}: non-positive values in {col}")
    dup = frame.duplicated(subset=["小区", "layer"])
    if dup.any():
        raise ValueError(f"{season}: duplicate plot-layer rows")
    if len(frame) != 36:
        raise ValueError(f"{season}: expected 36 rows, got {len(frame)}")
    return frame


def ic_rows(lines: list[str]):
    """Yield (line_idx, c, icbl, tokens) for every IC layer row in the FileX."""
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("@C") and "ICBL" in lines[i]:
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("@") \
                    and not lines[j].startswith("*"):
                tokens = lines[j].split()
                if len(tokens) == 5:
                    try:
                        yield j, int(tokens[0]), int(tokens[1]), tokens
                    except ValueError:
                        pass
                j += 1
            i = j
        else:
            i += 1


def build_plan(season: str) -> list[dict]:
    cfg = SEASONS[season]
    frame = load_measurements(season)
    src_tmx = EXP / cfg["src_bundle"] / f"{cfg['excode']}.TMX"
    lines = src_tmx.read_text(encoding="utf-8", errors="ignore").splitlines()
    index = {(c, icbl): (idx, tokens) for idx, c, icbl, tokens in ic_rows(lines)}
    plan = []
    for _, row in frame.sort_values(["小区", "layer"]).iterrows():
        key = (int(row["小区"]), int(row["layer"]))
        if key not in index:
            raise ValueError(f"{season}: FileX has no IC row for C={key[0]} ICBL={key[1]}")
        idx, tokens = index[key]
        if len(tokens[2]) > 5:
            raise ValueError(f"{season}: SH2O token wider than 5 chars: {tokens}")
        nh4_field, no3_field = fmt_pair(float(row[NH4_COL]), float(row[NO3_COL]))
        plan.append({
            "season": season, "source_workbook": cfg["xlsx"].name, "plot": key[0],
            "layer_cm": key[1], "target_bundle": cfg["new_bundle"], "ic": key[0],
            "old_snh4": tokens[3], "old_sno3": tokens[4],
            "new_snh4_raw": float(row[NH4_COL]), "new_sno3_raw": float(row[NO3_COL]),
            "new_snh4": nh4_field, "new_sno3": no3_field,
            "nh4_reps": int(row[NH4_REP]), "no3_reps": int(row[NO3_REP]),
            "line_idx": idx,
        })
    return plan


def apply_season(season: str, plan: list[dict]) -> None:
    cfg = SEASONS[season]
    src_dir = EXP / cfg["src_bundle"]
    new_dir = EXP / cfg["new_bundle"]
    if new_dir.exists():
        shutil.rmtree(new_dir)
    shutil.copytree(src_dir, new_dir)
    tmx = new_dir / f"{cfg['excode']}.TMX"
    lines = tmx.read_text(encoding="utf-8", errors="ignore").splitlines()
    for item in plan:
        tokens = lines[item["line_idx"]].split()
        if len(tokens) != 5 or int(tokens[0]) != item["ic"] or int(tokens[1]) != item["layer_cm"]:
            raise AssertionError(f"line drifted: {item}")
        # DSSAT IPSLIN fixed columns: I2 (col 1-2), I4 (col 3-6), 3x F6.0 (col 7-12, 13-18, 19-24)
        rebuilt = (
            f"{int(tokens[0]):2d}"
            f"{int(tokens[1]):6d}"
            f"{tokens[2]:>6}"
            f"{item['new_snh4']:>6}"
            f"{item['new_sno3']:>6}"
        )
        check = rebuilt.split()
        if len(check) != 5:
            raise AssertionError(f"field merge in rebuilt line: {rebuilt!r}")
        float(check[2]), float(check[3]), float(check[4])
        lines[item["line_idx"]] = rebuilt

    if season == "26SP":
        filtered_lines = []
        in_ic55 = False
        for line in lines:
            if line.strip().startswith("55 ") and "-99" in line:
                in_ic55 = True
                if filtered_lines and filtered_lines[-1].strip().startswith("@C   PCR"):
                    filtered_lines.pop()
                continue
            if in_ic55:
                if line.strip().startswith("55 ") or line.strip().startswith("@C  ICBL"):
                    continue
                else:
                    in_ic55 = False
            filtered_lines.append(line)
        lines = filtered_lines

    tmx.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not (args.dry_run or args.apply):
        parser.error("choose --dry-run or --apply")

    plans = {season: build_plan(season) for season in SEASONS}
    all_rows = [row for plan in plans.values() for row in plan]
    table = pd.DataFrame(all_rows)
    print(table[["season", "plot", "layer_cm", "old_snh4", "new_snh4",
                 "old_sno3", "new_sno3", "nh4_reps", "no3_reps"]].to_string(index=False))
    for season, plan in plans.items():
        print(f"{season}: {len(plan)} replacement rows (expect 36)")

    if args.dry_run:
        print("[dry-run] no files modified")
        return 0

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    pre_hashes = {
        "25SP_workbook": sha256(SEASONS["25SP"]["xlsx"]),
        "26SP_25FA_workbook": sha256(SEASONS["26SP"]["xlsx"]),
        **{f"{s}_src_tmx": sha256(EXP / c["src_bundle"] / f"{c['excode']}.TMX")
           for s, c in SEASONS.items()},
        **{f"{s}_src_manifest": sha256(EXP / c["src_bundle"] / "input_manifest.json")
           for s, c in SEASONS.items()},
    }
    for season, plan in plans.items():
        apply_season(season, plan)

    table.to_csv(AUDIT_DIR / "initial_mineral_n_replacement_audit.csv", index=False,
                 encoding="utf-8-sig")
    post_hashes = {
        **{f"{s}_new_tmx": sha256(EXP / c["new_bundle"] / f"{c['excode']}.TMX")
           for s, c in SEASONS.items()},
        **{f"{s}_new_manifest": sha256(EXP / c["new_bundle"] / "input_manifest.json")
           for s, c in SEASONS.items()},
    }
    audit = {
        "schema_version": 1,
        "date": "2026-08-20",
        "rule": "measured pre-season mineral N (outlier-removed means) -> FileX SNH4/SNO3 at ICBL 20/40/60",
        "field_mapping": {"硝态氮纯氮-剔异常平均": "SNO3", "铵态氮-剔异常平均": "SNH4"},
        "outlier_rule": "source workbook sheet 剔异常平均版 (per-workbook 异常值明细/三重复与判定)",
        "provenance": {
            "25SP": "上一季试验末期实测（25SP硝态氮铵态氮参考.xlsx），小区2-13 -> IC2-13",
            "25FA_26SP": "25FA 地块上一季黄瓜试验末期实测（26SP和25FA硝态氮铵态氮参考.xlsx），小区1-12 -> IC1-12",
        },
        "untouched": ["SH2O", "ICBL 80/100 cm", "25SP IC1/IC14", "26SP IC55",
                      "SA bundles", "data/raw", "_archive_20260808", "layermean/special_defaultn bundles"],
        "format": "six-character fields, ~5 significant digits (e.g. 49.708496 -> '49.708')",
        "rows_per_season": {s: len(p) for s, p in plans.items()},
        "sha256": {**pre_hashes, **post_hashes},
    }
    (AUDIT_DIR / "initial_mineral_n_replacement_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # manifests: update bundle ids, TMX hashes, correction log
    for season, cfg in SEASONS.items():
        manifest_path = EXP / cfg["new_bundle"] / "input_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["derived_from_bundle"] = cfg["src_bundle"]
        manifest["derived_from_manifest_sha256"] = pre_hashes[f"{season}_src_manifest"]
        manifest["bundle_id"] = cfg["new_bundle"]
        tmx_path = EXP / cfg["new_bundle"] / f"{cfg['excode']}.TMX"
        hit = False
        for record in manifest.get("files", []):
            if record.get("name") == f"{cfg['excode']}.TMX":
                record["sha256"] = sha256(tmx_path)
                record["bytes"] = tmx_path.stat().st_size
                hit = True
        if not hit:
            raise ValueError(f"{season}: manifest has no TMX file record")
        correction = {
            "correction_id": "measured_mineral_n_ic_20260820",
            "date": "2026-08-20",
            "file": f"{cfg['excode']}.TMX",
            "change": "SNH4/SNO3 at ICBL 20/40/60 replaced with pre-season measured "
                      "outlier-removed means (36 rows); SH2O and deeper layers untouched",
            "source_workbook": SEASONS[season]["xlsx"].name,
            "source_sheet": "剔异常平均版",
            "audit": "workspace/reports/measuredn_replacement_20260820/initial_mineral_n_replacement_audit.csv",
            "source_workbook_sha256": pre_hashes[
                "25SP_workbook" if season == "25SP" else "26SP_25FA_workbook"],
        }
        corrections = manifest.setdefault("data_corrections", [])
        if isinstance(corrections, list):
            corrections.append(correction)
        else:
            corrections["measured_mineral_n_ic_20260820"] = correction
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(f"audits: {AUDIT_DIR}")
    print("bundles:", [SEASONS[s]["new_bundle"] for s in SEASONS])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
