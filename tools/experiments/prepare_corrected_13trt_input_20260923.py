#!/usr/bin/env python3
"""Stage the corrected 25SP/26SP bundles for the legacy 13-treatment objective.

The output is a run-local, immutable composite input bundle. It is not an
additional active season bundle; both season inputs remain pinned by hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.input_manifest import verify_manifest_integrity

SEASONS = {
    "25SP": ("xxql2501_corrected_20260923", "XXQL2501"),
    "26SP": ("xxql2601_corrected_20260923", "XXQL2601"),
}
BATCH = ROOT / "data/templates/batch/DSSBatch_calib_13trt.v48"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing input: {destination}")
    if not BATCH.is_file():
        raise FileNotFoundError(BATCH)
    destination.mkdir(parents=True)
    parents = {}
    for season, (bundle_id, excode) in SEASONS.items():
        source = ROOT / "data/user/experiments" / bundle_id
        manifest = verify_manifest_integrity(source)
        parents[season] = {
            "bundle_id": bundle_id,
            "manifest_sha256": manifest.manifest_sha256,
        }
        for suffix in ("TMX", "TMA", "TMT"):
            name = f"{excode}.{suffix}"
            shutil.copyfile(source / name, destination / name)
        weather = sorted(source.glob("*.WTH"))
        if len(weather) != 1:
            raise ValueError(f"{source}: expected one weather file, found {len(weather)}")
        shutil.copyfile(weather[0], destination / weather[0].name)
        for name in ("SOIL.SOL", "TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"):
            target = destination / name
            if target.exists():
                if digest(target) != digest(source / name):
                    raise ValueError(f"Season bundles disagree on {name}")
            else:
                shutil.copyfile(source / name, target)
    shutil.copyfile(BATCH, destination / BATCH.name)
    manifest_data = {
        "bundle_id": destination.name,
        "intended_use": "parameter_calibration",
        "parents": parents,
        "batch_source": str(BATCH.relative_to(ROOT)).replace("\\", "/"),
        "batch_source_sha256": digest(BATCH),
        "files": [
            {"name": p.name, "sha256": digest(p), "size_bytes": p.stat().st_size}
            for p in sorted(destination.iterdir()) if p.is_file()
        ],
    }
    (destination / "input_manifest.json").write_text(
        json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify_manifest_integrity(destination)
    print(f"Staged {destination} (manifest {digest(destination / 'input_manifest.json')})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    build(parser.parse_args().out_dir.resolve())
