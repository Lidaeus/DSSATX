"""Create the immutable 25SP calibration bundle with ADAP=34 d.

The completed ADAP=21 bundle is preserved.  This derivation changes only the
FileA anthesis date (ADAT 25096 -> 25109) and provenance fields/checksums.
PAGE=25 and SPRL=-99 remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import argparse
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_NAME = (
    "xxql2501_actual_trial_calibration_v5_adap21_moisturefix_page25_20260729"
)
DESTINATION_NAME = (
    "xxql2501_actual_trial_calibration_v6_adap34_moisturefix_page25_20260729"
)
FILEA_NAME = "XXQL2501.TMA"
UNCERTAINTY_NAME = "observation_uncertainty.csv"
OLD_ADAT = "25096"
NEW_ADAT = "25109"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_filea(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    header_index = next(
        i for i, line in enumerate(lines) if line.lstrip().startswith("@TRNO")
    )
    changed = 0
    for i in range(header_index + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.startswith(("*", "@", "!")):
            continue
        fields = line.split()
        if len(fields) < 3:
            continue
        if fields[2] != OLD_ADAT:
            raise RuntimeError(
                f"Expected ADAT={OLD_ADAT} in FileA row, found {fields[2]}: {line!r}"
            )
        old_fragment = f" {OLD_ADAT} "
        if old_fragment not in line:
            raise RuntimeError(f"Fixed-width ADAT fragment not found: {line!r}")
        lines[i] = line.replace(old_fragment, f" {NEW_ADAT} ", 1)
        changed += 1
    if changed != 10:
        raise RuntimeError(f"Expected 10 included 25SP rows, changed {changed}")
    path.write_text("".join(lines), encoding="utf-8", newline="")
    return changed


def update_uncertainty(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    for i, line in enumerate(lines):
        if ",ADAT,21.0," in line:
            lines[i] = line.replace(",ADAT,21.0,", ",ADAT,34.0,", 1)
            changed += 1
    if changed != 10:
        raise RuntimeError(f"Expected 10 ADAT uncertainty rows, changed {changed}")
    path.write_text("".join(lines), encoding="utf-8", newline="")
    return changed


def update_manifest(
    destination: Path,
    source: Path,
    changed_rows: int,
    uncertainty_rows: int,
) -> str:
    manifest_path = destination / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest_hash = sha256(source / "input_manifest.json")
    source_manifest = json.loads(
        (source / "input_manifest.json").read_text(encoding="utf-8")
    )
    old_bundle_id = str(source_manifest["bundle_id"])
    manifest["bundle_id"] = DESTINATION_NAME
    manifest["derived_from_bundle"] = old_bundle_id
    manifest["derived_from_manifest_sha256"] = source_manifest_hash
    manifest["created_at"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    manifest["revision_note"] = (
        "User-authoritative correction: 25SP ADAP=34 d "
        "(PDAT 25075, ADAT 25109). PAGE=25 and SPRL=-99 remain unchanged. "
        "The completed ADAP=21 source bundle is retained unchanged."
    )
    manifest["management_authority"] = {
        "authority": "user decision in project thread",
        "approved_on": "2026-07-29",
        "transplant_age_days_PAGE": 25,
        "sprl": -99,
        "sprl_policy": "DSSAT missing/default",
        "adap_days": 34,
        "pdat": 25075,
        "adat": 25109,
        "changed_filea_rows": changed_rows,
        "changed_uncertainty_rows": uncertainty_rows,
        "immutable_source_bundle": old_bundle_id,
        "immutable_source_manifest_sha256": source_manifest_hash,
    }
    for entry in manifest["files"]:
        file_path = destination / entry["name"]
        if entry["name"] == FILEA_NAME:
            entry.setdefault("previous_sha256", entry.get("sha256"))
            entry["copied_from"] = str((source / FILEA_NAME).resolve())
            entry["change_scope"] = (
                "FileA ADAT 25096->25109 for 10 included treatments; "
                "ADAP 21->34 d"
            )
        if entry["name"] == UNCERTAINTY_NAME:
            entry.setdefault("previous_sha256", entry.get("sha256"))
            entry["copied_from"] = str((source / UNCERTAINTY_NAME).resolve())
            entry["change_scope"] = (
                "ADAT/ADAP uncertainty registry value 21.0->34.0 "
                "for 10 included treatments"
            )
        entry["sha256"] = sha256(file_path)
        entry["bytes"] = file_path.stat().st_size
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return sha256(manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repair-existing",
        action="store_true",
        help="Complete the synchronized uncertainty update in an existing v6 bundle.",
    )
    args = parser.parse_args()
    base = ROOT / "data" / "user" / "experiments"
    source = base / SOURCE_NAME
    destination = base / DESTINATION_NAME
    if destination.exists():
        if not args.repair_existing:
            raise FileExistsError(f"Refusing to overwrite derived bundle: {destination}")
        if f" {NEW_ADAT} " not in (destination / FILEA_NAME).read_text(
            encoding="utf-8"
        ):
            raise RuntimeError("Existing destination is not the expected ADAP=34 bundle")
        changed_rows = 10
    else:
        shutil.copytree(source, destination)
        changed_rows = update_filea(destination / FILEA_NAME)
    uncertainty_rows = update_uncertainty(destination / UNCERTAINTY_NAME)
    manifest_hash = update_manifest(
        destination, source, changed_rows, uncertainty_rows
    )
    print(
        json.dumps(
            {
                "bundle": destination.relative_to(ROOT).as_posix(),
                "changed_filea_rows": changed_rows,
                "changed_uncertainty_rows": uncertainty_rows,
                "filea_sha256": sha256(destination / FILEA_NAME),
                "manifest_sha256": manifest_hash,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
