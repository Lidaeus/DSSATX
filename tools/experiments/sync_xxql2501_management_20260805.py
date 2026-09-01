"""Synchronize operational XXQL2501 management and spring observations.

The corrected FileX under ``data/user/ref`` is the sole authority for the
fertilizer and harvest schedules.  Historical run sandboxes are intentionally
not touched; this script updates only reusable source bundles and the root
Workspace/raw copies used to build them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.experiment_inputs import (
    filex_management_signature,
    replace_filex_management_sections,
)


REFERENCE = ROOT / "data" / "user" / "ref" / "XXQL2501.TMX"
REFERENCE_OUTPUT = ROOT / "data" / "user" / "ref" / "DSSAT文件" / "2025春" / "DSSAT输出_v2"

TMX_TARGETS = [
    ROOT / "data/raw/experiments/XXQL2501.TMX",
    ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMX",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/XXQL2501.TMX",
    ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/XXQL2501.TMX",
    ROOT / "_seasons/25SP/XXQL2501.TMX",
    ROOT / "Workspace/XXQL2501.TMX",
]

FULL_OBSERVATION_BUNDLES = [
    ROOT / "data/user/experiments/XXQL2501",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
    ROOT / "_seasons/25SP",
]

ROOT_OBSERVATION_DIRS = [ROOT / "data/raw/experiments", ROOT / "Workspace"]
OBSERVATION_NAMES = ("XXQL2501.TMA", "XXQL2501.TMT")
GENERATED_NAMES = (
    "XXQL2501.TMA",
    "XXQL2501.TMT",
    "observation_uncertainty.csv",
    "fruit_quality_match_audit.csv",
    "FileA_values.csv",
    "FileT_values.csv",
    "treatment_exclusion_audit.csv",
    "generator_log.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_manifest(bundle: Path) -> None:
    manifest_path = bundle / "input_manifest.json"
    if not manifest_path.is_file():
        return
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {entry.get("name"): entry for entry in data.get("files", [])}
    generator_hash = sha256(ROOT / "tools/experiments/build_trial_observations_v2_20260726.py")
    for name, entry in by_name.items():
        path = bundle / name
        if path.is_file() and name in GENERATED_NAMES + ("XXQL2501.TMX",):
            entry["sha256"] = sha256(path)
            entry["bytes"] = path.stat().st_size
            if name in GENERATED_NAMES:
                entry["generated_by"] = "tools/experiments/build_trial_observations_v2_20260726.py"
                entry["generator_sha256"] = generator_hash
    qa = data.get("trial_observation_qa")
    if isinstance(qa, dict):
        qa["harvest_dates"] = 9
        qa["total_observations"] = 490
    corrections = data.get("data_corrections")
    if not isinstance(corrections, dict):
        corrections = {}
        data["data_corrections"] = corrections
    corrections.update(
        {
            "filex_management_reference": "data/user/ref/XXQL2501.TMX",
            "filex_management_reference_sha256": sha256(REFERENCE),
            "filex_management_scope": ["*FERTILIZERS (INORGANIC)", "*HARVEST DETAILS"],
            "estimated_harvest_records_removed": [25198, 25203, 25204],
        }
    )
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if not REFERENCE.is_file():
        raise FileNotFoundError(REFERENCE)
    for target in TMX_TARGETS:
        if not target.is_file():
            raise FileNotFoundError(target)
        replace_filex_management_sections(target, REFERENCE)
        if filex_management_signature(target) != filex_management_signature(REFERENCE):
            raise RuntimeError(f"Management alignment failed: {target}")

    for bundle in FULL_OBSERVATION_BUNDLES:
        for name in GENERATED_NAMES:
            source = REFERENCE_OUTPUT / name
            target = bundle / name
            if source.is_file() and target.parent.is_dir():
                shutil.copy2(source, target)
        update_manifest(bundle)

    for directory in ROOT_OBSERVATION_DIRS:
        for name in OBSERVATION_NAMES:
            source = REFERENCE_OUTPUT / name
            target = directory / name
            if target.is_file():
                shutil.copy2(source, target)

    print(json.dumps({
        "reference": str(REFERENCE),
        "tmx_targets": [str(path) for path in TMX_TARGETS],
        "full_observation_bundles": [str(path) for path in FULL_OBSERVATION_BUNDLES],
        "harvest_dates": 9,
        "removed_estimated_dates": [25198, 25203, 25204],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
