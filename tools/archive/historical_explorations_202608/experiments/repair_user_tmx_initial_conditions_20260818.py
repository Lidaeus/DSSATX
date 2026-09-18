"""Canonicalize INITIAL CONDITIONS rows in every data/user TMX file.

Only the ICBL/SH2O/SNH4/SNO3 layer header/rows and surplus blank records inside
those tables are changed.  The header and data share DSSAT widths 2/6/6/6/6.
Semantic values are retained when they fit in five characters; longer values
are rounded to the closest representable token so each six-character DSSAT
field retains at least one leading separator.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/user"
BACKUP = ROOT / "workspace/backups/tmx_ic_format_20260818"
REPORT = ROOT / "workspace/reports/tmx_ic_format_repair_20260818"
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")
PREFIX = re.compile(r"^\s*(\d+)\s+(\d+)")
IC_HEADER = "@C  ICBL  SH2O  SNH4  SNO3"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact_decimal(value: Decimal) -> str:
    plain = format(value, "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    if plain.startswith("0."):
        plain = plain[1:]
    elif plain.startswith("-0."):
        plain = "-." + plain[3:]
    if len(plain) <= 5:
        return plain
    for significant in range(5, 0, -1):
        rendered = format(value, f".{significant}g")
        if rendered.startswith("0."):
            rendered = rendered[1:]
        elif rendered.startswith("-0."):
            rendered = "-." + rendered[3:]
        if len(rendered) <= 5 and "E" not in rendered.upper():
            return rendered
    raise ValueError(f"value cannot fit a five-character TMX token: {value}")


def repair_text(text: str) -> tuple[str, list[dict], int, int]:
    lines = text.splitlines()
    output: list[str] = []
    in_initial = False
    in_layers = False
    rows: list[dict] = []
    removed_blanks = 0
    headers_rewritten = 0
    for line_no, line in enumerate(lines, 1):
        upper = line.strip().upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_initial = True
            in_layers = False
            output.append(line)
            continue
        if in_initial and upper.startswith("*"):
            in_initial = False
            in_layers = False
            output.append(line)
            continue
        if in_initial and upper.startswith("@C") and all(x in upper for x in ("ICBL", "SH2O", "SNH4", "SNO3")):
            in_layers = True
            if line != IC_HEADER:
                headers_rewritten += 1
            output.append(IC_HEADER)
            continue
        if in_initial and upper.startswith("@C"):
            in_layers = False
            output.append(line)
            continue
        if not in_layers:
            output.append(line)
            continue
        if not line.strip():
            removed_blanks += 1
            continue
        match = PREFIX.match(line)
        if not match:
            raise ValueError(f"line {line_no}: malformed IC prefix: {line!r}")
        values = NUMBER.findall(line[match.end():])
        if len(values) < 3:
            raise ValueError(f"line {line_no}: expected SH2O/SNH4/SNO3: {line!r}")
        ic, depth = int(match.group(1)), int(match.group(2))
        old = [Decimal(token) for token in values[:3]]
        tokens = [compact_decimal(value) for value in old]
        new = [Decimal(token) for token in tokens]
        canonical = f"{ic:2d}{depth:6d}" + "".join(token.rjust(6) for token in tokens)
        if len(canonical) != 26:
            raise AssertionError(f"line {line_no}: canonical width {len(canonical)} != 26")
        output.append(canonical)
        rows.append({
            "line_before": line_no, "ic": ic, "depth_cm": depth,
            "old_sh2o": str(old[0]), "new_sh2o": str(new[0]),
            "old_snh4": str(old[1]), "new_snh4": str(new[1]),
            "old_sno3": str(old[2]), "new_sno3": str(new[2]),
            "max_abs_change": str(max(abs(a - b) for a, b in zip(old, new))),
            "old_line": line, "new_line": canonical,
        })
    trailing_newline = text.endswith(("\n", "\r"))
    result = "\n".join(output) + ("\n" if trailing_newline else "")
    return result, rows, removed_blanks, headers_rewritten


def update_manifest(tmx: Path) -> bool:
    manifest_path = tmx.parent / "input_manifest.json"
    if not manifest_path.is_file():
        return False
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest, size = sha256(tmx), tmx.stat().st_size
    changed = False

    def visit(value):
        nonlocal changed
        if isinstance(value, dict):
            if value.get("name") == tmx.name and "sha256" in value:
                value["sha256"], value["bytes"] = digest, size
                changed = True
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    correction = {
            "correction_id": "canonical_tmx_ic_fixed_width_20260818",
            "scope": "INITIAL CONDITIONS ICBL/SH2O/SNH4/SNO3 header and records only",
            "change": "Removed surplus blank records and rewrote the header and rows as DSSAT widths 2/6/6/6/6; numeric changes limited to width-safe rounding.",
            "repair_audit": str((REPORT / "tmx_ic_repair_rows.csv").resolve()),
        }
    corrections = payload.setdefault("data_corrections", [])
    if isinstance(corrections, list):
        existing = next((item for item in corrections if isinstance(item, dict) and item.get("correction_id") == correction["correction_id"]), None)
        if existing is None:
            corrections.append(correction)
            changed = True
        elif existing != correction:
            existing.clear()
            existing.update(correction)
            changed = True
    elif isinstance(corrections, dict):
        if corrections.get(correction["correction_id"]) != correction:
            corrections[correction["correction_id"]] = correction
            changed = True
    else:
        payload["data_corrections"] = [correction]
        changed = True
    if changed:
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    files = sorted(SOURCE.rglob("*.TMX"), key=lambda path: str(path).lower())
    if not files:
        raise FileNotFoundError(f"no TMX files below {SOURCE}")
    audit_rows: list[dict] = []
    file_rows: list[dict] = []
    for path in files:
        relative = path.relative_to(SOURCE)
        backup = BACKUP / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        body = raw[3:] if bom else raw
        text = body.decode("utf-8")
        newline = "\r\n" if b"\r\n" in body else "\n"
        before_hash = sha256(path)
        repaired, rows, removed, headers_rewritten = repair_text(text)
        encoded = repaired.replace("\n", newline).encode("utf-8")
        if bom:
            encoded = b"\xef\xbb\xbf" + encoded
        path.write_bytes(encoded)
        manifest_updated = update_manifest(path)
        for row in rows:
            audit_rows.append({"file": str(relative), **row})
        file_rows.append({
            "file": str(relative), "rows": len(rows), "blank_lines_removed": removed,
            "headers_rewritten": headers_rewritten,
            "sha256_before": before_hash, "sha256_after": sha256(path),
            "bytes_before": len(raw), "bytes_after": path.stat().st_size,
            "newline": "CRLF" if newline == "\r\n" else "LF",
            "manifest_updated": manifest_updated,
        })
    with (REPORT / "tmx_ic_repair_rows.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit_rows[0]))
        writer.writeheader(); writer.writerows(audit_rows)
    with (REPORT / "tmx_ic_repair_files.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(file_rows[0]))
        writer.writeheader(); writer.writerows(file_rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "source_root": str(SOURCE),
        "backup_root": str(BACKUP), "files": len(files), "rows": len(audit_rows),
        "blank_lines_removed": sum(row["blank_lines_removed"] for row in file_rows),
        "headers_rewritten": sum(row["headers_rewritten"] for row in file_rows),
        "max_abs_numeric_change": max(float(row["max_abs_change"]) for row in audit_rows),
        "manifests_updated": sum(bool(row["manifest_updated"]) for row in file_rows),
    }
    (REPORT / "repair_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
