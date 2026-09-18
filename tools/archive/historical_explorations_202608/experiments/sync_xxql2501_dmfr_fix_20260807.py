"""Sync the corrected 25SP TMT (dry-weight DMFR outlier fix) to all bundles.

The generator (build_trial_observations_v2_20260726.py) now removes anomalous
fruit-moisture replicates before converting fresh -> dry yield (deviation >
0.05 from the (TRNO, date) group median).  Treatment 13 rep3 (moisture 0.7848)
and treatment 5 rep2 (moisture 0.8936) were removed, so TN13 DMFR drops from
9.31% to 3.21% and TN5 from 6.35% to 4.20%.

This script copies the regenerated files from DSSAT输出_v2 into every bundle
that contains XXQL2501.TMT and updates each input_manifest.json SHA-256 records
for the affected files (and the trial-observations generator SHA).

Affected files (regenerated): XXQL2501.TMT, FileT_values.csv,
observation_uncertainty.csv, fruit_quality_match_audit.csv, generator_log.json
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(r"D:/Tomato_Cal")
SRC = ROOT / "data/user/ref/DSSAT文件/2025春/DSSAT输出_v2"
AFFECTED = ["XXQL2501.TMT", "FileT_values.csv", "observation_uncertainty.csv",
            "fruit_quality_match_audit.csv", "generator_log.json"]

# Bundles containing XXQL2501.TMT (all found by scan)
BUNDLES = [
    ROOT / "data/user/experiments/XXQL2501",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v4_adap21_moisturefix_20260728",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v5_adap21_moisturefix_page25_20260729",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v6_adap34_moisturefix_page25_20260729",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    ROOT / "data/user/experiments/xxql2501_corrected_management_layermean_20260806",
    ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
    ROOT / "data/user/experiments/xxql2501_special_defaultn_page25_v1_20260730",
    ROOT / "data/user/experiments/xxql2501_special_defaultn_v1_20260730",
    ROOT / "data/raw/experiments",  # raw copy of authoritative TMT
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _update_files_entries(manifest: dict, files: list[Path]) -> None:
    """Update .files[].sha256/bytes and .files_by_role.generated_trial[].sha256."""
    by_name = {p.name: p for p in files}

    def patch(entries):
        for e in entries:
            name = e.get("name")
            if name in by_name:
                p = by_name[name]
                e["sha256"] = sha256_file(p)
                e["bytes"] = p.stat().st_size

    patch(manifest.get("files", []))
    for role, entries in manifest.get("files_by_role", {}).items():
        patch(entries)


def main() -> None:
    # The authoritative generator SHA is taken from the regenerated generator_log.json
    gen_log = json.loads((SRC / "generator_log.json").read_text(encoding="utf-8"))
    new_gen_sha = gen_log["generator_sha256"]
    print(f"new generator_sha256: {new_gen_sha}")
    print(f"source dir: {SRC}")

    for bundle in BUNDLES:
        if not bundle.is_dir():
            print(f"SKIP (no dir): {bundle}")
            continue
        tmt = bundle / "XXQL2501.TMT"
        if not tmt.is_file():
            print(f"SKIP (no TMT): {bundle}")
            continue

        old_tmt_sha = sha256_file(tmt)
        # Copy affected files
        for name in AFFECTED:
            src = SRC / name
            dst = bundle / name
            if src.is_file():
                shutil.copy2(src, dst)

        new_tmt_sha = sha256_file(tmt)
        print(f"UPDATED {bundle.name}: TMT {old_tmt_sha[:12]} -> {new_tmt_sha[:12]}")

        # Update manifest if present
        manifest_path = bundle / "input_manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            affected_paths = [bundle / n for n in AFFECTED if (bundle / n).is_file()]
            _update_files_entries(manifest, affected_paths)
            # Update generator SHA for trial_observations
            gens = manifest.get("generators", {})
            if "trial_observations" in gens:
                gens["trial_observations"]["sha256"] = new_gen_sha
            # Note the correction (data_corrections is a dict in existing manifests)
            corrections = manifest.setdefault("data_corrections", {})
            note = {
                "correction_id": "dmfr_anomalous_replicate_removal_20260807",
                "scope": "25SP XXQL2501 fruit dry-weight conversion",
                "change": ("Removed anomalous fruit-moisture replicates (deviation > 0.05 "
                           "from (TRNO,date) median): TN13 rep3 moisture=0.7848, TN5 rep2 "
                           "moisture=0.8936. TN13 DMFR 9.31%->3.21%, TN5 6.35%->4.20%."),
                "generator_sha256": new_gen_sha,
            }
            if isinstance(corrections, dict):
                if corrections.get("correction_id") != note["correction_id"]:
                    manifest["data_corrections"] = [corrections, note]
            elif isinstance(corrections, list):
                if not any(c.get("correction_id") == note["correction_id"] for c in corrections if isinstance(c, dict)):
                    corrections.append(note)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"  manifest updated: {manifest_path.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
