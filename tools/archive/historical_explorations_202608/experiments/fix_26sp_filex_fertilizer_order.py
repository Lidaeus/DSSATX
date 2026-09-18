"""Fix 26SP FileX inorganic-fertilizer management row order per spec section 6.2.

Spec: docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md section 6.2:
  "修正 26SP 派生 FileX。只调整无机肥管理行次序，保留实测初始条件、
   土壤分析、水氮管理内容；输入审计必须通过。"

This script ONLY reorders rows within each (treatment, FDATE) group by FMCD
code ascending (FE005 -> FE013 -> FE018 -> FE300). All numeric values are
preserved byte-for-byte. After fixing the TMX, the manifest SHA is regenerated
and filex_fix_status is updated to DONE.

Usage:
  python tools/experiments/fix_26sp_filex_fertilizer_order.py
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2601_actual_trial_calibration_v2_20260726"
TMX_PATH = BUNDLE_DIR / "XXQL2601.TMX"
MANIFEST_PATH = BUNDLE_DIR / "input_manifest.json"

FERT_HEADER_RE = re.compile(r"^\*FERTILIZERS\s*\(INORGANIC\)\s*$")
COL_HEADER_RE = re.compile(r"^@F\s+FDATE\s+FMCD")
NEXT_SECTION_RE = re.compile(r"^\*[A-Z]")

# FMCD sort key: lower code first. Codes observed: FE005, FE013, FE018, FE300.
def fmcd_sort_key(fmcd: str) -> str:
    return fmcd.strip().upper()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fix_fertilizer_order(tmx_path: Path) -> tuple[str, str, int, int]:
    """Reorder fertilizer rows within each (treatment, FDATE) group by FMCD.

    Returns (old_sha, new_sha, n_groups_reorderd, n_rows_total).
    """
    old_sha = sha256_file(tmx_path)
    lines = tmx_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    # Locate the FERTILIZERS (INORGANIC) section
    sec_start: int | None = None
    col_header_idx: int | None = None
    sec_end: int | None = None  # index of next section header line (exclusive of fertilizer block)

    for i, line in enumerate(lines):
        if FERT_HEADER_RE.match(line.strip()):
            sec_start = i
            continue
        if sec_start is not None and col_header_idx is None and COL_HEADER_RE.match(line):
            col_header_idx = i
            continue
        if sec_start is not None and col_header_idx is not None:
            # We're in the data rows. Detect end: blank line followed by next *SECTION,
            # or a *SECTION line directly.
            stripped = line.strip()
            if NEXT_SECTION_RE.match(stripped):
                sec_end = i
                break
            # also treat a completely blank line that is followed by a *SECTION as end
            if stripped == "" and i + 1 < len(lines) and NEXT_SECTION_RE.match(lines[i + 1].strip()):
                sec_end = i
                break
    if sec_end is None:
        # fallback: end of file
        sec_end = len(lines)

    if sec_start is None or col_header_idx is None:
        raise RuntimeError(f"Could not locate FERTILIZERS section in {tmx_path}")

    # Parse data rows between col_header_idx+1 and sec_end
    data_lines: list[tuple[int, str]] = []
    blank_tail: list[tuple[int, str]] = []
    for i in range(col_header_idx + 1, sec_end):
        line = lines[i]
        if line.strip() == "":
            blank_tail.append((i, line))
            continue
        data_lines.append((i, line))

    # Each data row: first token is treatment number, second is FDATE, third is FMCD
    # Use regex to extract leading three tokens.
    row_re = re.compile(r"^\s*(\d+)\s+(\d+)\s+(FE\d+)\s")
    parsed: list[dict] = []
    for idx, line in data_lines:
        m = row_re.match(line)
        if not m:
            raise RuntimeError(f"Cannot parse fertilizer row at line {idx+1}: {line!r}")
        trno = int(m.group(1))
        fdate = int(m.group(2))
        fmcd = m.group(3)
        parsed.append({"idx": idx, "line": line, "trno": trno, "fdate": fdate, "fmcd": fmcd})

    # Group by (trno, fdate), sort within group by fmcd, preserve group order
    # (groups appear in the order they first occur; do not re-sort groups).
    groups: dict[tuple[int, int], list[dict]] = {}
    group_order: list[tuple[int, int]] = []
    for r in parsed:
        key = (r["trno"], r["fdate"])
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(r)

    n_reordered = 0
    new_data_lines: list[str] = []
    for key in group_order:
        rows = groups[key]
        sorted_rows = sorted(rows, key=lambda r: fmcd_sort_key(r["fmcd"]))
        if [r["idx"] for r in sorted_rows] != [r["idx"] for r in rows]:
            n_reordered += 1
        new_data_lines.extend(r["line"] for r in sorted_rows)

    # Reassemble: section header -> col header -> reordered data -> blank tail -> rest
    # The fertilizer block occupies [sec_start, sec_end).
    # We keep [sec_start, col_header_idx+1) intact, replace data rows, keep blank tail,
    # then [sec_end, end) intact.
    head = lines[: col_header_idx + 1]
    tail = lines[sec_end:]
    # Preserve the blank tail lines that were between last data row and next section
    new_block = head + new_data_lines + [l for _, l in blank_tail] + tail

    new_text = "".join(new_block)
    tmx_path.write_text(new_text, encoding="utf-8")
    new_sha = sha256_file(tmx_path)
    return old_sha, new_sha, n_reordered, len(parsed)


def update_manifest(manifest_path: Path, old_tmx_sha: str, new_tmx_sha: str,
                    n_reordered: int, n_rows: int) -> None:
    """Update manifest: replace TMX SHA, set filex_fix_status to DONE."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Update filex_fix_status
    manifest["filex_fix_status"] = (
        f"DONE: reordered {n_reordered} (trno,FDATE) groups by FMCD ascending "
        f"(FE005->FE013->FE018->FE300); {n_rows} rows total; all numeric values "
        f"preserved. Old TMX SHA={old_tmx_sha[:12]}..., new SHA={new_tmx_sha[:12]}..."
    )

    # Update copied_from_v1 entry for XXQL2601.TMX
    for entry in manifest.get("files", {}).get("copied_from_v1", []):
        if entry.get("name") == "XXQL2601.TMX":
            entry["sha256"] = new_tmx_sha
            # Record the fix provenance
            entry["v2_fix"] = {
                "action": "inorganic_fertilizer_row_order_per_spec_6.2",
                "original_sha256": old_tmx_sha,
                "fixed_sha256": new_tmx_sha,
                "sort_key": "FMCD ascending within (trno, FDATE)",
                "spec": "docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md section 6.2",
            }
            break

    # Update files_flat entry
    for entry in manifest.get("files_flat", []):
        if entry.get("name") == "XXQL2601.TMX":
            entry["sha256"] = new_tmx_sha
            entry["v2_fix"] = {
                "action": "inorganic_fertilizer_row_order_per_spec_6.2",
                "original_sha256": old_tmx_sha,
                "fixed_sha256": new_tmx_sha,
                "sort_key": "FMCD ascending within (trno, FDATE)",
                "spec": "docs/三季FileA_FileT与不确定性适配计划_v1_20260726.md section 6.2",
            }
            break

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")


def main() -> None:
    print(f"[fix_26sp_filex_fertilizer_order] TMX: {TMX_PATH}")
    old_sha, new_sha, n_reordered, n_rows = fix_fertilizer_order(TMX_PATH)
    print(f"  old TMX SHA: {old_sha}")
    print(f"  new TMX SHA: {new_sha}")
    print(f"  groups reordered: {n_reordered}")
    print(f"  total fertilizer rows: {n_rows}")
    update_manifest(MANIFEST_PATH, old_sha, new_sha, n_reordered, n_rows)
    print(f"[fix_26sp_filex_fertilizer_order] manifest updated: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
