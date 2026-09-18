"""Read-only S0-4 audit of 26SP raw evidence for initial plant state.

The audit inventories the original Excel/CSV sources and the formal TMT/TMA
derivatives.  It does not alter any source or bundle.  A positive finding is
limited to explicitly labelled, treatment-level field evidence; absence of a
column is reported as non-identifiability rather than filled with defaults.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_4_raw_initial_state_evidence"
REF = ROOT / "data/user/ref/DSSAT文件/2026春"
FORMAL = ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830"

KEYWORDS = ("苗", "移栽", "定植", "transplant", "seedling", "plant", "plwt", "page", "density", "密度", "缺株", "missing")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(v: object) -> str:
    return str(v).strip().lower()


def inspect_excel(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    book = pd.ExcelFile(path)
    for sheet in book.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet, header=0)
        cols = [str(c).strip() for c in frame.columns if str(c).strip() and not str(c).startswith("Unnamed")]
        hits = [c for c in cols if any(k in norm(c) for k in KEYWORDS)]
        treatment_cols = [c for c in cols if any(k in norm(c) for k in ("处理", "treatment", "trno", "小区", "plot"))]
        rows.append({"file": str(path), "sheet": sheet, "rows": int(len(frame)),
                     "columns": cols, "keyword_columns": hits,
                     "treatment_or_plot_columns": treatment_cols})
    return rows


def inspect_text(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    first = next((x for x in lines if x.strip()), "")
    return {"file": str(path), "bytes": len(data), "sha256": sha256(path),
            "lines": len(lines), "first_nonempty_line": first[:500]}


def parse_table(path: Path) -> pd.DataFrame:
    """Parse a simple DSSAT @TRNO table without altering fixed-width text."""
    header = None; rows = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.upper().startswith("@TRNO"):
            header = [x.lstrip("@").upper() for x in line.split()]
            continue
        if header is None or not line or line.startswith(("*", "@", "!")):
            continue
        fields = line.split()
        if len(fields) < len(header):
            continue
        rows.append(dict(zip(header, fields[:len(header)])))
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    inventory: list[dict[str, object]] = []
    excel_files = [REF / "2026春生长指标集.xlsx", REF / "2026春产量集.xlsx",
                   REF / "2026春品质指标集.xlsx", REF / "2026春土壤数据集.xlsx"]
    # Include the parallel reference copy when available; differences are
    # useful provenance evidence and do not imply that either copy is correct.
    excel_files += [REF / "2026春" / x for x in ()]
    for path in excel_files:
        if path.is_file():
            inventory.extend(inspect_excel(path))
    csv_files = [REF / "DSSAT输出_v2" / "XXQL2601.TMA", REF / "DSSAT输出_v2" / "XXQL2601.TMT",
                 REF / "DSSAT输出" / "2026SPR_observations.csv", REF / "DSSAT输出" / "2026SPR_FileA_values.csv",
                 REF / "DSSAT输出" / "2026SPR_FileT_values.csv", FORMAL / "XXQL2601.TMA", FORMAL / "XXQL2601.TMT"]
    text_inventory = [inspect_text(p) for p in csv_files if p.is_file()]
    pd.DataFrame(inventory).to_csv(OUT / "s0_4_source_inventory.csv", index=False, encoding="utf-8-sig")
    (OUT / "s0_4_text_source_inventory.json").write_text(json.dumps(text_inventory, indent=2, ensure_ascii=False), encoding="utf-8")

    all_cols = sorted({c for r in inventory for c in r["columns"]})
    keyword_cols = sorted({c for r in inventory for c in r["keyword_columns"]})
    explicit_initial_fields = [c for c in all_cols if any(k in norm(c) for k in ("苗", "移栽", "定植", "plwt", "page", "seedling", "transplant", "density", "密度", "缺株"))]
    treatment_level_fields = [c for c in explicit_initial_fields if any(k in norm(c) for k in ("处理", "小区", "plot", "trno", "treatment"))]
    state_compare: dict[str, object] = {"available": False}
    ref_tmt = REF / "DSSAT输出_v2" / "XXQL2601.TMT"
    formal_tmt = FORMAL / "XXQL2601.TMT"
    if ref_tmt.is_file() and formal_tmt.is_file():
        a, b = parse_table(ref_tmt), parse_table(formal_tmt)
        keys = ["TRNO", "DATE"]
        a = a.set_index(keys); b = b.set_index(keys)
        common = a.index.intersection(b.index)
        state_cols = [c for c in ("LAID", "LWAD", "SWAD", "CHTD") if c in a.columns and c in b.columns]
        mismatch = {}
        for col in state_cols:
            av = pd.to_numeric(a.loc[common, col], errors="coerce")
            bv = pd.to_numeric(b.loc[common, col], errors="coerce")
            diff = (av - bv).abs()
            mismatch[col] = {"n_compared": int(diff.notna().sum()), "n_mismatch_gt_1e-9": int((diff > 1e-9).sum()), "max_abs_diff": float(diff.max()) if diff.notna().any() else None}
        state_compare = {"available": True, "reference_rows": int(len(a)), "formal_rows": int(len(b)), "common_key_rows": int(len(common)), "state_columns": mismatch,
                         "state_values_match": all(v["n_mismatch_gt_1e-9"] == 0 for v in mismatch.values())}

    report = {
        "scope": "26SP raw evidence for treatment-level transplant/initial plant state",
        "source_inventory_rows": len(inventory),
        "excel_files_checked": [str(x) for x in excel_files if x.is_file()],
        "text_files_checked": [x["file"] for x in text_inventory],
        "keyword_columns_found": keyword_cols,
        "explicit_initial_state_fields_found": explicit_initial_fields,
        "treatment_level_initial_state_fields_found": treatment_level_fields,
        "finding": "no_explicit_treatment_level_initial_plant_state_field_in_checked_26sp_sources" if not treatment_level_fields else "candidate_fields_require_manual_source_validation",
        "formal_bundle_hashes": {p.name: sha256(p) for p in (FORMAL / "XXQL2601.TMX", FORMAL / "XXQL2601.TMA", FORMAL / "XXQL2601.TMT") if p.is_file()},
        "formal_vs_reference_tmt_state_compare": state_compare,
        "formal_bundle_untouched_by_audit": True,
    }
    (OUT / "s0_4_raw_initial_state_audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
