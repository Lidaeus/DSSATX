"""Prepare a versioned formal design with corrected 26SP initial mineral N.

Only SNH4/SNO3 at 20, 40 and 60 cm are replaced.  Treatment-specific
sequential measured SH2O and the 80/100-cm rows remain byte-semantically
unchanged.  The source bundle and source formal design are never modified.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_BUNDLE = ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_20260828"
TARGET_BUNDLE = ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828"
SOURCE_CONFIG = ROOT / "configs/runs/e02_formal_armab_rrmse_200x6_20260828.json"
TARGET_CONFIG = ROOT / "configs/runs/e02_formal_armab_rrmse_26spncal_200x6_20260828.json"
MEANS_JSON = ROOT / "workspace/reports/26sp_initial_n_calibration_20260828/26sp_initial_n_means.json"
AUDIT_CSV = ROOT / "workspace/reports/26sp_initial_n_calibration_20260828/initial_mineral_n_replacement_audit.csv"
RECEIPT_JSON = ROOT / "workspace/reports/26sp_initial_n_calibration_20260828/preparation_receipt.json"
FILEX_NAME = "XXQL2601.TMX"
DESIGN_ID = "e02_formal_armab_rrmse_26spncal_200x6_20260828"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def field6(value: float) -> str:
    rendered = format(float(value), ".5g")
    if rendered.startswith("0."):
        rendered = rendered[1:]
    elif rendered.startswith("-0."):
        rendered = "-." + rendered[3:]
    if len(rendered) > 6:
        raise ValueError(f"Value does not fit six-character FileX field: {value}")
    return rendered.rjust(6)


def load_means() -> tuple[dict[tuple[int, int], dict], dict]:
    payload = json.loads(MEANS_JSON.read_text(encoding="utf-8"))
    records = payload.get("records") or []
    lookup = {(int(r["treatment"]), int(r["bottom_cm"])): r for r in records}
    expected = {(tn, depth) for tn in range(1, 13) for depth in (20, 40, 60)}
    if set(lookup) != expected:
        missing = sorted(expected - set(lookup))
        extra = sorted(set(lookup) - expected)
        raise ValueError(f"Workbook means do not cover expected cells; missing={missing}, extra={extra}")
    return lookup, payload


def replace_filex(source_text: str, lookup: dict[tuple[int, int], dict]) -> tuple[str, list[dict]]:
    lines = source_text.splitlines()
    in_initial = False
    in_layer_table = False
    audit: list[dict] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_initial = True
            in_layer_table = False
            continue
        if in_initial and upper.startswith("*"):
            in_initial = False
            in_layer_table = False
        if not in_initial:
            continue
        if upper.startswith("@C"):
            in_layer_table = all(token in upper for token in ("ICBL", "SH2O", "SNH4", "SNO3"))
            continue
        if not in_layer_table:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            treatment = int(parts[0])
            depth = int(float(parts[1]))
            old_sh2o, old_snh4, old_sno3 = map(float, parts[2:5])
        except ValueError:
            continue
        if depth not in (20, 40, 60):
            continue
        record = lookup[(treatment, depth)]
        new_snh4 = float(record["snh4_mean"])
        new_sno3 = float(record["sno3_mean"])
        new_line = f"{treatment:3d}{depth:6d}{field6(old_sh2o)}{field6(new_snh4)}{field6(new_sno3)}"
        if len(new_line) != 27:
            raise AssertionError(f"Unexpected fixed-width row length {len(new_line)}: {new_line!r}")
        lines[index] = new_line
        audit.append({
            "treatment": treatment,
            "bottom_cm": depth,
            "sh2o": old_sh2o,
            "old_snh4": old_snh4,
            "new_snh4_unrounded": new_snh4,
            "new_snh4_written": float(field6(new_snh4)),
            "old_sno3": old_sno3,
            "new_sno3_unrounded": new_sno3,
            "new_sno3_written": float(field6(new_sno3)),
            "snh4_r1": record["snh4_replicates"][0],
            "snh4_r2": record["snh4_replicates"][1],
            "snh4_r3": record["snh4_replicates"][2],
            "sno3_r1": record["sno3_replicates"][0],
            "sno3_r2": record["sno3_replicates"][1],
            "sno3_r3": record["sno3_replicates"][2],
        })
    if len(audit) != 36 or {(r["treatment"], r["bottom_cm"]) for r in audit} != set(lookup):
        raise AssertionError(f"Expected exactly 36 target replacements, found {len(audit)}")
    return "\n".join(lines) + "\n", audit


def file_hashes(bundle: Path) -> dict[str, str]:
    return {
        path.relative_to(bundle).as_posix(): sha256(path)
        for path in sorted(bundle.rglob("*"))
        if path.is_file() and path.name != "input_manifest.json"
    }


def refresh_manifest_file(manifest: dict, bundle: Path, name: str) -> None:
    matches = [r for r in manifest.get("files", []) if r.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Manifest must contain exactly one record for {name}; found {len(matches)}")
    path = bundle / name
    matches[0]["sha256"] = sha256(path)
    matches[0]["bytes"] = path.stat().st_size


def main() -> int:
    if TARGET_BUNDLE.exists() or TARGET_CONFIG.exists():
        raise FileExistsError("Refusing to overwrite an existing target bundle or design")
    lookup, workbook_payload = load_means()
    source_hashes = file_hashes(SOURCE_BUNDLE)
    source_manifest_path = SOURCE_BUNDLE / "input_manifest.json"
    source_filex_path = SOURCE_BUNDLE / FILEX_NAME

    shutil.copytree(SOURCE_BUNDLE, TARGET_BUNDLE)
    target_filex_path = TARGET_BUNDLE / FILEX_NAME
    transformed, audit = replace_filex(source_filex_path.read_text(encoding="utf-8"), lookup)
    target_filex_path.write_text(transformed, encoding="utf-8", newline="")

    target_hashes = file_hashes(TARGET_BUNDLE)
    changed = sorted(name for name in source_hashes if source_hashes[name] != target_hashes.get(name))
    if changed != [FILEX_NAME] or set(source_hashes) != set(target_hashes):
        raise AssertionError(f"Unexpected payload changes: {changed}")

    AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(sorted(audit, key=lambda r: (r["treatment"], r["bottom_cm"])))

    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    corrections = dict(manifest.get("data_corrections") or {})
    corrections.pop("measured_mineral_n_ic_20260820", None)
    corrections["measured_mineral_n_ic_26sp_calibration_20260828"] = {
        "correction_id": "measured_mineral_n_ic_26sp_calibration_20260828",
        "date": "2026-08-28",
        "file": FILEX_NAME,
        "section": "*INITIAL CONDITIONS",
        "fields": ["SNH4", "SNO3"],
        "scope": "TN1-TN12, ICBL 20/40/60 cm (36 rows)",
        "aggregation": "arithmetic mean of R1/R2/R3 for each treatment x layer",
        "unchanged": ["SH2O at all layers", "SNH4/SNO3 at 80/100 cm", "all other bundle payloads"],
        "source_workbook": Path(workbook_payload["source_workbook"]).name,
        "source_sheet": workbook_payload["source_sheet"],
        "source_workbook_sha256": workbook_payload["source_workbook_sha256"],
        "audit": AUDIT_CSV.relative_to(ROOT).as_posix(),
    }
    manifest.update({
        "bundle_id": TARGET_BUNDLE.name,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "derived_from_bundle": SOURCE_BUNDLE.name,
        "derived_from_manifest_sha256": sha256(source_manifest_path),
        "initial_condition_policy": (
            "26SP treatment-specific sequential measured SH2O retained; "
            "SNH4/SNO3 at 20/40/60 cm are treatment-layer means of three workbook replicates; "
            "80/100 cm mineral N retained from source bundle"
        ),
        "data_corrections": corrections,
        "manifest_repair": {
            "date": "2026-08-28",
            "scope": "versioned 26SP initial mineral-N replacement",
            "source_payload_modified": False,
            "target_payload_changed": [FILEX_NAME],
            "removed_inapplicable_metadata": ["measured_mineral_n_ic_20260820 (25SP source reference)"],
        },
    })
    refresh_manifest_file(manifest, TARGET_BUNDLE, FILEX_NAME)
    target_manifest_path = TARGET_BUNDLE / "input_manifest.json"
    target_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    config.update({
        "design_id": DESIGN_ID,
        "purpose": "Formal Arm-A/B continuation after calibrated 26SP initial SNH4/SNO3 replacement",
        "initial_condition_policy": (
            "25SP/25FA unchanged; 26SP sequential measured SH2O retained and initial SNH4/SNO3 "
            "at 20/40/60 cm replaced by audited treatment-layer three-replicate means"
        ),
    })
    season26 = next(s for s in config["seasons"] if s["season_id"] == "26SP")
    season26["bundle_path"] = TARGET_BUNDLE.relative_to(ROOT).as_posix()
    season26["bundle_manifest_sha256"] = sha256(target_manifest_path)
    TARGET_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema_version": 1,
        "design_id": DESIGN_ID,
        "source_bundle": SOURCE_BUNDLE.relative_to(ROOT).as_posix(),
        "target_bundle": TARGET_BUNDLE.relative_to(ROOT).as_posix(),
        "source_manifest_sha256": sha256(source_manifest_path),
        "target_manifest_sha256": sha256(target_manifest_path),
        "source_filex_sha256": sha256(source_filex_path),
        "target_filex_sha256": sha256(target_filex_path),
        "workbook_sha256": workbook_payload["source_workbook_sha256"],
        "replacement_rows": len(audit),
        "payload_files_changed": changed,
        "audit_csv": AUDIT_CSV.relative_to(ROOT).as_posix(),
        "config": TARGET_CONFIG.relative_to(ROOT).as_posix(),
    }
    RECEIPT_JSON.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
