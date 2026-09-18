"""Synchronize the two active formal bundle manifests with on-disk payloads.

This is a manifest-only repair: no TMA/TMT/TMX, observation, or soil payload is
edited.  All files in the active bundle are recorded so the standard integrity
gate can detect future drift.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.input_manifest import verify_manifest_integrity

BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830",
    ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repair(bundle: Path) -> dict[str, object]:
    manifest_path = bundle / "input_manifest.json"
    old_manifest_sha256 = sha256(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = []
    for path in sorted(bundle.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.name != "input_manifest.json":
            entries.append({
                "name": path.name,
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            })
    payload["files"] = entries
    payload["manifest_repair"] = {
        "repaired_at": datetime.now(timezone.utc).isoformat(),
        "repaired_from_manifest_sha256": old_manifest_sha256,
        "payload_hashes_regenerated": True,
        "all_payload_files_listed": True,
        "payload_file_count": len(entries),
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    verified = verify_manifest_integrity(bundle)
    return {
        "bundle": str(bundle),
        "manifest_sha256": verified.manifest_sha256,
        "payload_file_count": len(entries),
    }


def main() -> int:
    for bundle in BUNDLES:
        print(json.dumps(repair(bundle), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
