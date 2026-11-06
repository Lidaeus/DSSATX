"""Build and export conditional prediction uncertainty data bundle for Champion C23.

Uses export_conditional_predictions to perform deterministic replay of the
final conditional parameter ensemble (iter8, 141 retained valid members) across
all 23 treatments for the two spring seasons (25SP: 11 trt, 26SP: 12 trt).
Synchronizes the frozen bundle with paper/07_C23_Revision_20260922/paper_data/conditional/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.export_conditional_predictions import export_conditional_predictions

CASE = 'full_gen_13trt_final_calib_200x8'
RUN_DIR = ROOT / 'workspace/runs/full_gen_13trt_final_calib_200x8_20260922'
DESIGN_PATH = ROOT / 'configs/runs/full_gen_13trt_final_calib_200x8_20260922_design.json'
METADATA_PATH = ROOT / 'configs/figures/treatment_metadata_two_season_20260922.csv'
OFFICIAL_DSSAT = Path('C:/DSSAT48/DSCSM048.EXE')
SEASON_BUNDLES = {
    '25SP': ROOT / 'data/user/experiments/xxql2501_corrected_20260923',
    '26SP': ROOT / 'data/user/experiments/xxql2601_corrected_20260923',
}
OUT_DATA_DIR = RUN_DIR / 'paper_data_conditional'
REVISION_DIR = ROOT / 'paper/07_C23_Revision_20260922/paper_data/conditional'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sync_bundle(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src_file in src_dir.glob('*'):
        if src_file.is_file():
            shutil.copy2(src_file, dst_dir / src_file.name)
    print(f"Synchronized bundle to {dst_dir}")


def verify_bundle(bundle_dir: Path) -> None:
    manifest_path = bundle_dir / 'paper_data_manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for artifact in manifest.get('artifacts', []):
        file_path = bundle_dir / artifact['path']
        assert file_path.is_file(), f"Missing artifact: {file_path}"
        actual_hash = sha256_file(file_path)
        assert actual_hash == artifact['sha256'], (
            f"Hash mismatch for {artifact['path']}: expected {artifact['sha256']}, got {actual_hash}"
        )
    print(f"Verified {len(manifest['artifacts'])} artifacts in {bundle_dir} against manifest.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and export conditional predictions for Champion C23")
    parser.add_argument('--force-replay', action='store_true', help="Force re-running DSSAT deterministic replays")
    parser.add_argument('--workers', type=int, default=min(6, os.cpu_count() or 4), help="Parallel replay workers")
    args = parser.parse_args(argv)

    print("=" * 80)
    print("Building Champion C23 Conditional Uncertainty Suite")
    print("=" * 80)

    needs_replay = args.force_replay or not (OUT_DATA_DIR / 'paper_data_manifest.json').is_file()
    if needs_replay:
        print("Executing deterministic conditional replay exporter...")
        OUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        export_conditional_predictions(
            run_dir=RUN_DIR,
            case=CASE,
            iteration=8,
            calibration_design=DESIGN_PATH,
            season_bundles=SEASON_BUNDLES,
            treatment_metadata_csv=METADATA_PATH,
            official_dssat=OFFICIAL_DSSAT,
            out_dir=OUT_DATA_DIR,
            workers=args.workers,
            member_limit=None,
            member_list=None,
            verify_members=3,
            allow_unvalidated_demo=True,
            replay_root_base=None,
        )
    else:
        print(f"Using existing replay bundle at {OUT_DATA_DIR}")

    verify_bundle(OUT_DATA_DIR)
    sync_bundle(OUT_DATA_DIR, REVISION_DIR)
    verify_bundle(REVISION_DIR)
    print("Champion C23 conditional prediction suite completed successfully!")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
