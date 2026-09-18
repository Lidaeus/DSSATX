"""Freeze corrected 0-4/4-60 cm bundles for the E02 formal calibration.

The 20260827 exploratory directories copied the 10L-B manifest unchanged after
replacing SOIL.SOL.  This script creates new immutable bundle IDs and rebuilds
their file inventory without altering either source bundle.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_BOTTOMS_CM = [4, 60, 80, 100, 140, 180]

BUNDLES = {
    "25SP": (
        "xxql2501_from_scratch_0_4_60cm_20260827",
        "xxql2501_from_scratch_0_4_60cm_formalprep_20260828",
    ),
    "26SP": (
        "xxql2601_from_scratch_0_4_60cm_20260827",
        "xxql2601_from_scratch_0_4_60cm_formalprep_20260828",
    ),
    "25FA": (
        "xxfa_from_scratch_0_4_60cm_20260827",
        "xxfa_from_scratch_0_4_60cm_formalprep_20260828",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rebuild_one(source: Path, destination: Path) -> dict[str, object]:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite frozen bundle: {destination}")

    source_manifest_path = source / "input_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    shutil.copytree(source, destination)

    manifest = dict(source_manifest)
    manifest["bundle_id"] = destination.name
    manifest["derived_from_bundle"] = source.name
    manifest["derived_from_manifest_sha256"] = _sha256(source_manifest_path)
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    manifest["soil_profile_scheme"] = "0-4cm, 4-60cm, then 60-180cm fixed subsoil"
    manifest["soil_profile_override"] = {
        "reason": "current-soil formal calibration scheme approved 2026-08-28",
        "source_bundle": source.name,
        "profile_id": "IBTM910017",
        "dssat_layer_bottoms_cm": PROFILE_BOTTOMS_CM,
    }
    if isinstance(manifest.get("soil_water_qa"), dict):
        soil_qa = dict(manifest["soil_water_qa"])
        soil_qa["dssat_layer_bottoms_cm"] = PROFILE_BOTTOMS_CM
        soil_qa["soil_profile_layer_count"] = len(PROFILE_BOTTOMS_CM)
        manifest["soil_water_qa"] = soil_qa

    payloads = sorted(
        path for path in destination.iterdir()
        if path.is_file() and path.name != "input_manifest.json"
    )
    manifest["files"] = [
        {"name": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in payloads
    ]
    manifest_path = destination / "input_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "bundle": destination.name,
        "manifest_sha256": _sha256(manifest_path),
        "files": len(payloads),
        "prohibited_use": manifest.get("prohibited_use", []),
    }


def main() -> int:
    experiment_root = ROOT / "data" / "user" / "experiments"
    results = {}
    for season, (source_name, destination_name) in BUNDLES.items():
        results[season] = _rebuild_one(
            experiment_root / source_name,
            experiment_root / destination_name,
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
