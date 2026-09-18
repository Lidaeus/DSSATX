"""Derive an immutable 25SP bundle from the audited fruit-moisture correction."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


REPLACEMENTS = {
    "XXQL2501.TMA": "XXQL2501.TMA",
    "XXQL2501.TMT": "XXQL2501.TMT",
    "observation_uncertainty.csv": "observation_uncertainty.csv",
    "fruit_quality_match_audit.csv": "fruit_quality_match_audit.csv",
    "treatment_exclusion_audit.csv": "treatment_exclusion_audit.csv",
    "trial_generator_log.json": "generator_log.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refresh_record(record: dict, bundle: Path, generated_dir: Path) -> None:
    name = str(record.get("name") or "")
    path = bundle / name
    if path.is_file():
        record["sha256"] = sha256(path)
        record["bytes"] = path.stat().st_size
    if name in REPLACEMENTS:
        record["source_v2_dir"] = str((generated_dir / REPLACEMENTS[name]).resolve())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--output-bundle", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_bundle.resolve()
    generated = args.generated_dir.resolve()
    output = args.output_bundle.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle: {output}")
    shutil.copytree(source, output)

    for destination, generated_name in REPLACEMENTS.items():
        replacement = generated / generated_name
        if not replacement.is_file():
            raise FileNotFoundError(replacement)
        shutil.copy2(replacement, output / destination)

    manifest_path = output / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest = source / "input_manifest.json"
    manifest["bundle_id"] = output.name
    manifest["derived_from_bundle"] = source.name
    manifest["derived_from_manifest_sha256"] = sha256(source_manifest)
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    manifest["data_corrections"] = {
        "correction_id": "25SP_fruit_moisture_outliers_v1_20260729",
        "source_workbook": "2025春作物生长指标集_moisturefix_v1_20260728.xlsx",
        "changes": [
            {"trno": 5, "replicate": 2, "dates": ["2025-05-22", "2025-06-19"],
             "old": 0.8936, "new": 0.9580},
            {"trno": 13, "replicate": 3, "dates": ["2025-05-22", "2025-06-19"],
             "old": 0.7848, "new": 0.9680},
        ],
        "scope": "DMFR, HPODW, CHPDT and propagated uncertainty only; fresh yield unchanged",
    }
    trial_log = json.loads((output / "trial_generator_log.json").read_text(encoding="utf-8"))
    manifest["source_workbooks"]["trial_observations"] = trial_log.get("source_files", {})
    manifest["trial_observation_qa"] = trial_log.get("qa_metrics", manifest["trial_observation_qa"])
    for record in manifest.get("files", []):
        refresh_record(record, output, generated)
    for records in manifest.get("files_by_role", {}).values():
        for record in records:
            refresh_record(record, output, generated)
    manifest["summary"]["total_files"] = len([p for p in output.iterdir() if p.is_file() and p.name != "input_manifest.json"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "bundle": str(output),
        "manifest_sha256": sha256(manifest_path),
        "source_manifest_sha256": sha256(source_manifest),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
