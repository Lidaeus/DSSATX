"""Derive two-spring default-N bundles with PAGE=25 and SPRL=-99."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "user" / "experiments"
DERIVATIONS = (
    {
        "season_id": "25SP",
        "source": "xxql2501_special_defaultn_v1_20260730",
        "destination": "xxql2501_special_defaultn_page25_v1_20260730",
        "filex": "XXQL2501.TMX",
        "old_sprl": "3",
    },
    {
        "season_id": "26SP",
        "source": "xxql2601_special_defaultn_v1_20260730",
        "destination": "xxql2601_special_defaultn_page25_v1_20260730",
        "filex": "XXQL2601.TMX",
        "old_sprl": "5",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_planting_line(path: Path, old_sprl: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
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


def refresh_record(record: dict, bundle: Path, filex_name: str, source: Path) -> None:
    name = str(record.get("name") or "")
    path = bundle / name
    if not path.is_file():
        return
    record["sha256"] = sha256(path)
    record["bytes"] = path.stat().st_size
    if name == filex_name:
        record["copied_from"] = str((source / filex_name).resolve())
        record["derived_transformation"] = "default_initial_mineral_n_plus_page25_sprl_default"
        record["change_scope"] = "INITIAL CONDITIONS retain default N; PLANTING DETAILS PAGE 60->25 and SPRL->-99"


def update_manifest(bundle: Path, source: Path, filex_name: str) -> str:
    manifest_path = bundle / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest = source / "input_manifest.json"
    source_hash = sha256(source_manifest)
    manifest["bundle_id"] = bundle.name
    manifest["derived_from_bundle"] = source.name
    manifest["derived_from_manifest_sha256"] = source_hash
    manifest["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest["revision_note"] = (
        "Derived from the immutable special_defaultn bundle; FileX initial mineral N "
        "remains SNO3=1.0 and SNH4=0.5, while PAGE is set to 25 d and SPRL to -99."
    )
    manifest["management_authority"] = {
        "authority": "两个春季默认硝态氮铵态氮率定v1",
        "approved_on": "2026-07-30",
        "transplant_age_days_PAGE": 25,
        "sprl": -99,
        "sprl_policy": "DSSAT missing/default",
        "immutable_source_bundle": source.name,
        "immutable_source_manifest_sha256": source_hash,
    }
    manifest["filex_fix_status"] = (
        "Calibration-authoritative derived FileX: default initial mineral N preserved; "
        "PAGE=25 and SPRL=-99."
    )
    transforms = list(manifest.get("counterfactual_transformations") or [])
    transforms.append(
        {
            "transformation_id": "page25_sprl_default_v1_20260730",
            "section": "*PLANTING DETAILS",
            "fields": {"PAGE": 25, "SPRL": -99},
            "scope": "planting detail row in FileX",
            "unchanged": [
                "*INITIAL CONDITIONS default mineral N audit",
                "*SOIL ANALYSIS",
                "fertilizer management",
                "irrigation management",
                "weather",
                "SOIL.SOL",
                "observations",
            ],
        }
    )
    manifest["counterfactual_transformations"] = transforms
    for record in manifest.get("files", []):
        refresh_record(record, bundle, filex_name, source)
    for records in manifest.get("files_by_role", {}).values():
        for record in records:
            refresh_record(record, bundle, filex_name, source)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return sha256(manifest_path)


def main() -> int:
    receipts: list[dict[str, object]] = []
    for item in DERIVATIONS:
        source = BASE / item["source"]
        destination = BASE / item["destination"]
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing bundle: {destination}")
        shutil.copytree(source, destination)
        filex = destination / item["filex"]
        update_planting_line(filex, str(item["old_sprl"]))
        manifest_hash = update_manifest(destination, source, str(item["filex"]))
        receipts.append(
            {
                "season_id": item["season_id"],
                "bundle": destination.relative_to(ROOT).as_posix(),
                "filex_sha256": sha256(filex),
                "manifest_sha256": manifest_hash,
            }
        )
    print(json.dumps(receipts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
