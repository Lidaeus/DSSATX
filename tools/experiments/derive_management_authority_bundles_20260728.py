"""Derive immutable calibration bundles with approved transplant settings.

The historical/source bundles are retained unchanged.  This script creates new
versioned bundles in which PAGE is 25 d and SPRL is DSSAT's missing/default
value (-99).  The 25SP source bundle already contains the authoritative
ADAP=21 d correction.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import argparse
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

DERIVATIONS = (
    {
        "season": "25SP_MOISTUREFIX",
        "source": "xxql2501_actual_trial_calibration_v4_adap21_moisturefix_20260728",
        "destination": "xxql2501_actual_trial_calibration_v5_adap21_moisturefix_page25_20260729",
        "filex": "XXQL2501.TMX",
        "old_sprl": "3",
        "adap": 21,
    },
    {
        "season": "25SP",
        "source": "xxql2501_actual_trial_calibration_v3_adap21_20260728",
        "destination": "xxql2501_actual_trial_calibration_v4_adap21_page25_20260728",
        "filex": "XXQL2501.TMX",
        "old_sprl": "3",
        "adap": 21,
    },
    {
        "season": "25FA",
        "source": "xxql2502_actual_trial_calibration_v2_20260726",
        "destination": "xxql2502_actual_trial_calibration_v3_page25_20260728",
        "filex": "XXQL2502.TMX",
        "old_sprl": "6",
        "adap": None,
    },
    {
        "season": "26SP",
        "source": "xxql2601_actual_trial_calibration_v2_20260726",
        "destination": "xxql2601_actual_trial_calibration_v3_page25_20260728",
        "filex": "XXQL2601.TMX",
        "old_sprl": "5",
        "adap": None,
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_planting_line(path: Path, old_sprl: str) -> None:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    section_index = next(
        i for i, line in enumerate(lines) if line.startswith("*PLANTING DETAILS")
    )
    header_index = next(
        i
        for i in range(section_index + 1, len(lines))
        if lines[i].lstrip().startswith("@P PDATE")
    )
    data_index = next(
        i
        for i in range(header_index + 1, len(lines))
        if lines[i].strip() and not lines[i].startswith(("@", "*", "!"))
    )
    fields = lines[data_index].split()
    if len(fields) < 16:
        raise RuntimeError(f"Unexpected planting row in {path}: {lines[data_index]!r}")
    if fields[11] != "60" or fields[14] != old_sprl:
        raise RuntimeError(
            f"Expected PAGE=60/SPRL={old_sprl} in {path}; "
            f"found PAGE={fields[11]}/SPRL={fields[14]}"
        )
    old_fragment = f"    60    25     1     {old_sprl}"
    new_fragment = "    25    25     1   -99"
    if old_fragment not in lines[data_index]:
        raise RuntimeError(f"Fixed-width planting fragment not found in {path}")
    lines[data_index] = lines[data_index].replace(old_fragment, new_fragment, 1)
    path.write_text("".join(lines), encoding="utf-8", newline="")


def update_manifest(
    destination: Path,
    source: Path,
    definition: dict[str, object],
) -> str:
    manifest_path = destination / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest_hash = sha256(source / "input_manifest.json")
    old_bundle_id = str(manifest["bundle_id"])

    manifest["bundle_id"] = str(definition["destination"])
    manifest["derived_from_bundle"] = old_bundle_id
    manifest["derived_from_manifest_sha256"] = source_manifest_hash
    manifest["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    adap_clause = (
        " ADAP=21 d (PDAT 25075, ADAT 25096) remains authoritative."
        if definition["adap"] == 21
        else ""
    )
    manifest["revision_note"] = (
        "User-approved management authority: PAGE=25 d for all seasons and "
        "SPRL=-99 (DSSAT missing/default), matching the historical calibration "
        f"FileX convention.{adap_clause} Source bundle retained unchanged."
    )
    manifest["management_authority"] = {
        "authority": "user decision in project thread",
        "approved_on": "2026-07-28",
        "transplant_age_days_PAGE": 25,
        "sprl": -99,
        "sprl_policy": "DSSAT missing/default",
        "adap_days": definition["adap"],
        "immutable_source_bundle": old_bundle_id,
        "immutable_source_manifest_sha256": source_manifest_hash,
    }
    preservation = manifest.setdefault("actual_trial_preservation", {})
    preservation["reference_filex"] = str((source / str(definition["filex"])).resolve())
    preservation["reference_filex_sha256"] = sha256(
        source / str(definition["filex"])
    )
    preservation["filex_retention_proof"] = (
        "Derived from the immutable source bundle; only the approved planting "
        "fields PAGE and SPRL changed."
    )
    manifest["filex_fix_status"] = (
        "Calibration-authoritative derived FileX: PAGE=25 and SPRL=-99; "
        "all other FileX content retained from the source bundle."
    )

    for entry in manifest["files"]:
        file_path = destination / entry["name"]
        if entry["name"] == definition["filex"]:
            entry["previous_sha256"] = entry.get("sha256")
            entry["copied_from"] = str(
                (source / str(definition["filex"])).resolve()
            )
            entry["change_scope"] = "PLANTING DETAILS: PAGE 60->25; SPRL -> -99"
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
        "--only",
        choices=[str(item["season"]) for item in DERIVATIONS],
        help="Create only one named derivation.",
    )
    args = parser.parse_args()
    base = ROOT / "data" / "user" / "experiments"
    receipts: list[dict[str, object]] = []
    for definition in DERIVATIONS:
        if args.only and definition["season"] != args.only:
            continue
        source = base / str(definition["source"])
        destination = base / str(definition["destination"])
        if destination.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing derived bundle: {destination}"
            )
        shutil.copytree(source, destination)
        filex = destination / str(definition["filex"])
        update_planting_line(filex, str(definition["old_sprl"]))
        manifest_hash = update_manifest(destination, source, definition)
        receipts.append(
            {
                "season": definition["season"],
                "bundle": destination.relative_to(ROOT).as_posix(),
                "filex_sha256": sha256(filex),
                "manifest_sha256": manifest_hash,
            }
        )
    print(json.dumps(receipts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
