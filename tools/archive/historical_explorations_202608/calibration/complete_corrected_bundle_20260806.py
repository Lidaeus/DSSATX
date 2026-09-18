"""Add the audited observation sidecars to the corrected XXQL2501 bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "data/user/experiments/xxql2501_corrected_management_layermean_20260806"
SOURCE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for name in ("observation_uncertainty.csv", "soil_water_observations.csv"):
        shutil.copy2(SOURCE / name, BUNDLE / name)
    manifest_path = BUNDLE / "input_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["bundle_id"] = BUNDLE.name
    payload["derived_from_bundle"] = SOURCE.name
    payload["metadata_corrections"] = list(payload.get("metadata_corrections") or []) + [
        {"file": "XXQL2501.TMX", "field": "fertilizer/harvest management", "reference": "data/user/ref/XXQL2501.TMX"},
        {"file": "XXQL2501.TMT", "field": "estimated harvest events", "rule": "events after authoritative TMX cutoff removed"},
    ]
    payload["files"] = [
        {"name": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
        for p in sorted(BUNDLE.iterdir()) if p.is_file() and p.name != "input_manifest.json"
    ]
    payload["science_status"] = "pass_with_warnings"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(BUNDLE), "manifest_sha256": sha(manifest_path), "tmx_sha256": sha(BUNDLE / "XXQL2501.TMX"), "tmt_sha256": sha(BUNDLE / "XXQL2501.TMT")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
