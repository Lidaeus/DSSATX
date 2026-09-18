"""Set treatment 12 INITIAL CONDITIONS in every user XXQL2601 TMX file."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/user"
BACKUP = ROOT / "workspace/backups/tmx_26sp_t12_ic_20260818"
REPORT = ROOT / "workspace/reports/tmx_26sp_t12_ic_20260818"
TARGET = {
    20: (".21", "3.9", "38.3"),
    40: (".298", "1.6", "31.8"),
    60: (".27", "1.1", "11"),
    80: (".28", ".5", "1"),
    100: (".34", ".5", "1"),
}
PREFIX = re.compile(r"^\s*(\d+)\s+(\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_row(treatment: int, depth: int, values: tuple[str, str, str]) -> str:
    row = f"{treatment:2d}{depth:6d}" + "".join(value.rjust(6) for value in values)
    if len(row) != 26:
        raise AssertionError(f"unexpected row width: {len(row)}")
    return row


def repair_text(text: str, source: Path) -> tuple[str, list[dict]]:
    lines = text.splitlines()
    output: list[str] = []
    audit: list[dict] = []
    in_initial = False
    in_layers = False
    seen_depths: set[int] = set()
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
        if in_initial and upper.startswith("@C"):
            in_layers = all(name in upper for name in ("ICBL", "SH2O", "SNH4", "SNO3"))
            output.append(line)
            continue
        if not in_layers or not line.strip():
            output.append(line)
            continue
        match = PREFIX.match(line)
        if not match:
            raise ValueError(f"{source}:{line_no}: malformed IC row: {line!r}")
        treatment, depth = int(match.group(1)), int(match.group(2))
        if treatment != 12:
            output.append(line)
            continue
        if depth not in TARGET:
            raise ValueError(f"{source}:{line_no}: unexpected treatment-12 depth {depth}")
        if depth in seen_depths:
            raise ValueError(f"{source}:{line_no}: duplicate treatment-12 depth {depth}")
        seen_depths.add(depth)
        new_line = canonical_row(treatment, depth, TARGET[depth])
        output.append(new_line)
        audit.append({
            "file": str(source.relative_to(SOURCE)),
            "line": line_no,
            "treatment": treatment,
            "depth_cm": depth,
            "old_line": line,
            "new_line": new_line,
            "changed": line != new_line,
        })
    if seen_depths != set(TARGET):
        raise ValueError(f"{source}: treatment-12 depths {sorted(seen_depths)} != {sorted(TARGET)}")
    trailing_newline = text.endswith(("\n", "\r"))
    return "\n".join(output) + ("\n" if trailing_newline else ""), audit


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
                if value.get("sha256") != digest or value.get("bytes") != size:
                    value["sha256"], value["bytes"] = digest, size
                    changed = True
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    correction = {
        "correction_id": "xxql2601_treatment12_initial_conditions_20260818",
        "scope": "XXQL2601 treatment 12 INITIAL CONDITIONS only",
        "change": "Set five ICBL/SH2O/SNH4/SNO3 rows to the user-specified 26SP values.",
        "repair_audit": str((REPORT / "rows.csv").resolve()),
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
    files = sorted(SOURCE.rglob("XXQL2601.TMX"), key=lambda path: str(path).lower())
    if not files:
        raise FileNotFoundError("no XXQL2601.TMX files found")
    REPORT.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    file_audit: list[dict] = []
    for path in files:
        relative = path.relative_to(SOURCE)
        backup = BACKUP / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        body = raw[3:] if bom else raw
        newline = "\r\n" if b"\r\n" in body else "\n"
        before_hash = sha256(path)
        repaired, rows = repair_text(body.decode("utf-8"), path)
        encoded = repaired.replace("\n", newline).encode("utf-8")
        if bom:
            encoded = b"\xef\xbb\xbf" + encoded
        path.write_bytes(encoded)
        manifest_updated = update_manifest(path)
        all_rows.extend(rows)
        file_audit.append({
            "file": str(relative),
            "rows": len(rows),
            "changed_rows": sum(bool(row["changed"]) for row in rows),
            "sha256_before": before_hash,
            "sha256_after": sha256(path),
            "manifest_updated": manifest_updated,
        })
    with (REPORT / "rows.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    with (REPORT / "files.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(file_audit[0]))
        writer.writeheader()
        writer.writerows(file_audit)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(SOURCE),
        "backup_root": str(BACKUP),
        "files": len(files),
        "rows": len(all_rows),
        "changed_rows": sum(bool(row["changed"]) for row in all_rows),
        "manifests_updated": sum(bool(row["manifest_updated"]) for row in file_audit),
        "target": {str(depth): list(values) for depth, values in TARGET.items()},
    }
    (REPORT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
