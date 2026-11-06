"""Version reusable 26SP bundles, changing only the approved 26180 LAI cells.

Historical bundles/run snapshots are never overwritten. The catalog maps each
input to its successor; new run designs must select the successor explicitly.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data/user/experiments/xxql2601_lai0629_imputed_20260831"
DEST = ROOT / "data/user/experiments/lai0629_synced_20260902"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path):
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))


def approved_rows():
    manifest = json.loads((REFERENCE / "input_manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if digest(REFERENCE / entry["name"]) != entry["sha256"]:
            raise ValueError(f"Approved imputation source hash mismatch: {entry['name']}")
    rows = {int(r["trno"]): r for r in csv_rows(REFERENCE / "observation_uncertainty.csv")
            if r["date"] == "26180" and r["variable"] == "LAID"}
    if set(rows) != set(range(1, 13)) or any(r["quality_flag"] != "imputed_20260831" for r in rows.values()):
        raise ValueError("Expected 12 approved imputed observations")
    return rows


def patch_tmt(raw, values):
    # Preserve every byte outside the six-character LAID field, including CRLF.
    seen = set()
    result = []
    for line in raw.splitlines(keepends=True):
        match = re.match(rb"^\s*(\d+)\s+(26180)\s", line)
        if match:
            tn = int(match[1])
            if tn in seen or tn not in values:
                raise ValueError("Duplicate/unexpected 26180 treatment")
            seen.add(tn)
            old = float(line[18:24])
            new = float(values[tn]["value"])
            if old != -99 and abs(old-new) > .00051:
                raise ValueError(f"Conflicting existing LAI for TN{tn}: {old}")
            line = line[:18] + f"{new:6.3f}".encode("ascii") + line[24:]
        result.append(line)
    if seen != set(values):
        raise ValueError("Missing 26180 rows; refusing to invent TMT records")
    return b"".join(result)


def patch_filet(raw, values):
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)
    header = next(csv.reader([lines[0]]))
    idx = header.index("LAID")
    seen = set()
    for k, line in enumerate(lines[1:], 1):
        cells = next(csv.reader([line]))
        row = dict(zip(header, cells))
        if row["DATE"] not in {"26180", "2026-06-29"}:
            continue
        tn = int(row["TRNO"])
        if tn in seen or tn not in values:
            raise ValueError("Duplicate/unexpected FileT treatment")
        seen.add(tn)
        old = float(cells[idx]) if cells[idx].strip() else -99
        new = float(values[tn]["value"])
        if old != -99 and abs(old-new) > .00051:
            raise ValueError(f"Conflicting FileT LAI TN{tn}")
        cells[idx] = f"{new:.3f}"
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\r\n" if line.endswith("\r\n") else "\n").writerow(cells)
        lines[k] = stream.getvalue()
    if seen != set(values):
        raise ValueError("Missing FileT LAI records")
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    return bom + "".join(lines).encode("utf-8")


def patch_uncertainty(path, values):
    rows = csv_rows(path)
    if not rows:
        raise ValueError("Uncertainty table empty")
    header = list(rows[0])
    rows = [r for r in rows if not (r["date"] == "26180" and r["variable"] == "LAID")]
    rows.extend({k: r.get(k, "") for k in header} for r in values.values())
    if not {"quality_flag", "raw_sd", "n_rep"}.issubset(header):
        raise ValueError("Uncertainty schema cannot retain imputation evidence")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    values = approved_rows()
    roots = [ROOT / "data/user/experiments",
             ROOT / "workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/bundles_v2"]
    sources = sorted({p.parent for root in roots for p in root.rglob("XXQL2601.TMT")
                      if DEST not in p.parents and not any(part.startswith("_archive") for part in p.parts)})
    catalog = []
    # Preflight every source before writing any derived bundle.
    plans = []
    for source in sources:
        required = ["XXQL2601.TMT", "FileT_values.csv", "observation_uncertainty.csv"]
        if not all((source / name).is_file() for name in required):
            catalog.append({"source": str(source), "status": "blocked_incomplete_bundle"})
            continue
        try:
            changes = {"XXQL2601.TMT": patch_tmt((source / "XXQL2601.TMT").read_bytes(), values),
                       "FileT_values.csv": patch_filet((source / "FileT_values.csv").read_bytes(), values),
                       "observation_uncertainty.csv": patch_uncertainty(source / "observation_uncertainty.csv", values)}
        except ValueError as exc:
            catalog.append({"source": str(source), "status": "blocked_conflict", "reason": str(exc)})
            continue
        existing = [r for r in csv_rows(source / "observation_uncertainty.csv")
                    if r["date"] == "26180" and r["variable"] == "LAID"]
        if len(existing) == 12 and all(r.get("quality_flag") == "imputed_20260831" and
                                      abs(float(r["value"]) - float(values[int(r["trno"])]["value"])) < 1e-6
                                      for r in existing):
            # Both value tables have passed patch validation above; retain existing versions.
            filet = csv_rows(source / "FileT_values.csv")
            actual = [r for r in filet if r["DATE"] in {"26180", "2026-06-29"}]
            if all(r["LAID"] and abs(float(r["LAID"]) - float(values[int(r["TRNO"])]["value"])) < .00051 for r in actual):
                catalog.append({"source": str(source), "successor": str(source), "status": "already_current"})
                continue
        key = hashlib.sha256(str(source.relative_to(ROOT)).encode()).hexdigest()[:8]
        target = DEST / f"{source.name}_{key}"
        if target.exists():
            raise ValueError(f"Destination exists; refusing overwrite: {target}")
        plans.append((source, target, changes))
        catalog.append({"source": str(source), "successor": str(target), "status": "ready"})
    if args.apply:
        for source, target, changes in plans:
            target.mkdir(parents=True)
            for file in source.iterdir():
                if file.is_file():
                    shutil.copy2(file, target / file.name)
            for name, raw in changes.items():
                (target / name).write_bytes(raw)
            shutil.copy2(REFERENCE / "lai0629_imputation_audit.csv", target / "lai0629_imputation_audit.csv")
            protected = [p for p in source.iterdir() if p.is_file() and p.name not in
                         {*changes, "input_manifest.json", "lai0629_imputation_audit.csv"}]
            assert all(digest(p) == digest(target / p.name) for p in protected)
            manifest = json.loads((source / "input_manifest.json").read_text(encoding="utf-8-sig")) if (source / "input_manifest.json").exists() else {}
            manifest.update({"bundle_id": target.name, "derived_from_bundle": str(source),
                             "derived_from_manifest_sha256": digest(source / "input_manifest.json") if (source / "input_manifest.json").exists() else None,
                             "lai_sync": {"date": 26180, "points": 12, "quality_flag": "imputed_20260831", "reference": str(REFERENCE),
                                          "unchanged": "All non-LAI fields, TMA, FileA, TMX, soil, weather and fruit moisture"},
                             "files": [{"name": p.name, "sha256": digest(p)} for p in sorted(target.iterdir()) if p.is_file() and p.name != "input_manifest.json"]})
            (target / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        DEST.mkdir(parents=True, exist_ok=True)
        (DEST / "bundle_successors.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"apply": args.apply, "ready": len(plans), "inventory": catalog}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
