"""Build the joint XXQL2501+XXQL2502 calibration input bundle for T7 formal v5.

Stages FileX/FileA/FileT/SOIL/WTH from the two approved source bundles and
writes a combined ``DSSBatch.v48`` plus an ``input_manifest.json`` that
explicitly freezes the calibration treatments, the validation season
(XXQL2601, sealed), and per-file SHA-256 provenance.

This script does NOT start DSSAT or PEST++; it only stages inputs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data/user/experiments/xxql_2501_2502_joint_calibration_v1_20260721"
SEASON_A_DIR = ROOT / "data/user/experiments/xxql2501_20260716"
SEASON_B_DIR = ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v1_20260721"

# T7 §4.2 treatment roles.
# XXQL2501 calibration: TN2/3/4/5 (W3 × N3/N2/N1/N0) + TN10/11/12/13 (W1 × N3/N2/N1/N0)
# XXQL2502 calibration: W3 = TN3/4/7/9; W1 = TN1/6/10/12
#   (mapped explicitly by MI/MF metadata, not by TN number; see T7 §4.2)
SEASON_A_TREATMENTS = [2, 3, 4, 5, 10, 11, 12, 13]
SEASON_B_TREATMENTS = [3, 4, 7, 9, 1, 6, 10, 12]
# Treatments intentionally left out of the joint batch are kept in the source
# bundles as diagnostic rows; they do not enter Phi here.
DIAGNOSTIC = {
    "XXQL2501": [9, 14],
    "XXQL2502": [2, 5, 8, 11],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


BATCH_HEADER = """$BATCH(TOMATO_CAL)
!
! Joint XXQL2501 + XXQL2502 calibration input for T7 formal v5.
! Scenario role: joint_calibration (XXQL2501 spring + XXQL2502 autumn)
! Validation season XXQL2601 is sealed and not present in this batch.
! Treatments follow T7 §4.2 (explicit MI/MF water-nitrogen subset).
!
@FILEX                                                                                        TRTNO     RP     SQ     OP     CO
"""

# Fixed-width FileX column layout, cloned byte-for-byte from the source
# per-season DSSBatch.v48 files.  The source uses Fortran-style formatting:
# FileX token left-justified in 91 characters (A91), followed by five
# right-justified integers each formatted as I7 (7 characters wide).  This
# reproduces the exact alignment of xxql2501_20260716/DSSBatch.v48, including
# the trailing CO=0 column.
FILEX_COLUMN_WIDTH = 91
INT_FIELD_WIDTH = 7


def _batch_row(filex_name: str, treatment: int) -> str:
    padded = filex_name.ljust(FILEX_COLUMN_WIDTH)
    fields = (
        f"{treatment:>{INT_FIELD_WIDTH}d}"
        f"{1:>{INT_FIELD_WIDTH}d}"
        f"{0:>{INT_FIELD_WIDTH}d}"
        f"{0:>{INT_FIELD_WIDTH}d}"
        f"{0:>{INT_FIELD_WIDTH}d}"
    )
    return f"{padded}{fields}"


def write_combined_batch(out_path: Path) -> list[dict]:
    rows: list[dict] = []
    run_no = 0
    for tn in SEASON_A_TREATMENTS:
        run_no += 1
        rows.append({"run": run_no, "filex": "XXQL2501.TMX", "tn": tn, "season": "XXQL2501"})
    for tn in SEASON_B_TREATMENTS:
        run_no += 1
        rows.append({"run": run_no, "filex": "XXQL2502.TMX", "tn": tn, "season": "XXQL2502"})
    lines = [BATCH_HEADER.rstrip("\n")]
    for r in rows:
        lines.append(_batch_row(r["filex"], r["tn"]))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return rows


def main() -> int:
    if OUT_DIR.exists() and any(OUT_DIR.iterdir()):
        raise SystemExit(f"refuse to overwrite non-empty bundle: {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    staged: list[dict] = []

    def stage(src: Path, dst_name: str | None = None, *, source_season: str, source_bundle: str) -> None:
        if not src.is_file():
            raise FileNotFoundError(src)
        dst = OUT_DIR / (dst_name or src.name)
        shutil.copy2(src, dst)
        staged.append(
            {
                "name": dst.name,
                "sha256": sha256(dst),
                "bytes": dst.stat().st_size,
                "source_season": source_season,
                "source_bundle": source_bundle,
                "source_path": str(src.relative_to(ROOT)).replace("\\", "/"),
            }
        )

    # XXQL2501: FileX/FileA/FileT + weather + shared SOIL.SOL
    stage(SEASON_A_DIR / "XXQL2501.TMX", source_season="XXQL2501", source_bundle="xxql2501_20260716")
    stage(SEASON_A_DIR / "XXQL2501.TMA", source_season="XXQL2501", source_bundle="xxql2501_20260716")
    stage(SEASON_A_DIR / "XXQL2501.TMT", source_season="XXQL2501", source_bundle="xxql2501_20260716")
    stage(SEASON_A_DIR / "XXN92501.WTH", source_season="XXQL2501", source_bundle="xxql2501_20260716")
    # XXQL2502: FileX/FileA/FileT + weather (SOIL.SOL shared, copy from season A)
    stage(SEASON_B_DIR / "XXQL2502.TMX", source_season="XXQL2502", source_bundle="xxql2502_actual_trial_calibration_v1_20260721")
    stage(SEASON_B_DIR / "XXQL2502.TMA", source_season="XXQL2502", source_bundle="xxql2502_actual_trial_calibration_v1_20260721")
    stage(SEASON_B_DIR / "XXQL2502.TMT", source_season="XXQL2502", source_bundle="xxql2502_actual_trial_calibration_v1_20260721")
    stage(SEASON_B_DIR / "XXLI2502.WTH", source_season="XXQL2502", source_bundle="xxql2502_actual_trial_calibration_v1_20260721")
    # SOIL.SOL is byte-identical across both source bundles; stage once with
    # both provenance hashes recorded in the manifest below.
    soil_a = sha256(SEASON_A_DIR / "SOIL.SOL")
    soil_b = sha256(SEASON_B_DIR / "SOIL.SOL")
    assert soil_a == soil_b, f"SOIL.SOL differs between source bundles: {soil_a} vs {soil_b}"
    shutil.copy2(SEASON_A_DIR / "SOIL.SOL", OUT_DIR / "SOIL.SOL")
    staged.append(
        {
            "name": "SOIL.SOL",
            "sha256": soil_a,
            "bytes": (OUT_DIR / "SOIL.SOL").stat().st_size,
            "source_season": "shared",
            "source_bundle": "xxql2501_20260716 + xxql2502_actual_trial_calibration_v1_20260721 (byte-identical)",
            "source_path": str((SEASON_A_DIR / "SOIL.SOL").relative_to(ROOT)).replace("\\", "/"),
        }
    )

    batch_rows = write_combined_batch(OUT_DIR / "DSSBatch.v48")
    staged.append(
        {
            "name": "DSSBatch.v48",
            "sha256": sha256(OUT_DIR / "DSSBatch.v48"),
            "bytes": (OUT_DIR / "DSSBatch.v48").stat().st_size,
            "source_season": "joint",
            "source_bundle": "generated by tools/calibration/build_t7_joint_bundle_20260721.py",
            "source_path": "generated",
        }
    )

    manifest = {
        "schema_version": 1,
        "bundle_id": OUT_DIR.name,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scenario_type": "joint_multiseason_calibration",
        "scenario_role": "calibration",
        "intended_use": "joint_parameter_calibration_XXQL2501_XXQL2502",
        "prohibited_use": [
            "sensitivity_analysis_only_input",
            "parameter_calibration_with_sealed_validation_season",
        ],
        "calibration_seasons": ["XXQL2501", "XXQL2502"],
        "validation_season_sealed": "XXQL2601",
        "validation_bundle_sealed": "xxql2601_actual_trial_validation_v1_20260721",
        "initial_condition_policy": "observed_treatment_specific_no_counterfactual_pooling",
        "soil_analysis_policy": "observed_treatment_specific_no_counterfactual_pooling",
        "counterfactual_transformations": [],
        "treatment_roles": {
            "XXQL2501": {
                "calibration": SEASON_A_TREATMENTS,
                "diagnostic": DIAGNOSTIC["XXQL2501"],
            },
            "XXQL2502": {
                "calibration": SEASON_B_TREATMENTS,
                "diagnostic": DIAGNOSTIC["XXQL2502"],
            },
        },
        "treatment_selection_rule": "T7 §4.2: XXQL2501 high/low water x 4 nitrogen levels; XXQL2502 explicit MI/MF high/low water x 4 nitrogen levels. Treatments are keyed by experiment_code+treatment, not by TN alone, so XXQL2501 TN3 and XXQL2502 TN3 are distinct design points.",
        "source_bundles": [
            {
                "season": "XXQL2501",
                "bundle_id": "xxql2501_20260716",
                "path": str(SEASON_A_DIR.relative_to(ROOT)).replace("\\", "/"),
            },
            {
                "season": "XXQL2502",
                "bundle_id": "xxql2502_actual_trial_calibration_v1_20260721",
                "path": str(SEASON_B_DIR.relative_to(ROOT)).replace("\\", "/"),
            },
        ],
        "batch_rows": batch_rows,
        "files": staged,
        "notes": [
            "SOIL.SOL is byte-identical across both source bundles (sha256 recorded once).",
            "DSSBatch.v48 is generated fresh for the joint case; it is not inherited from either source bundle.",
            "Treatments excluded from the calibration subset remain in the source bundles for diagnostic replay but do not enter the joint batch and therefore cannot receive non-zero PEST weights.",
        ],
    }
    (OUT_DIR / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    print(f"built joint bundle: {OUT_DIR}")
    print(f"  calibration treatments: XXQL2501 {SEASON_A_TREATMENTS} + XXQL2502 {SEASON_B_TREATMENTS}")
    print(f"  total batch rows: {len(batch_rows)} (Phi-eligible)")
    print(f"  diagnostic (NOT in batch): XXQL2501 {DIAGNOSTIC['XXQL2501']}, XXQL2502 {DIAGNOSTIC['XXQL2502']}")
    print(f"  files staged: {len(staged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
