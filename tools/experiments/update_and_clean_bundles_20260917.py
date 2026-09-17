"""Synchronize refreshed bundle data across user bundle aliases and clean obsolete bundles.

Targets:
1. data/user/experiments/XXQL2501 & xxql2501_unified_20260914 <- xxql2501_v20260917_refresh
2. data/user/experiments/XXQL2601 & xxql2601_unified_20260914 <- xxql2601_v20260917_refresh
3. data/user/experiments/XXQL2502 & xxql2502_unified_20260914 <- xxql2502_v20260917_refresh
4. Remove obsolete untracked trial bundles.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

ROOT = Path("D:/Tomato_Cal")
EXP_DIR = ROOT / "data" / "user" / "experiments"

REFRESH_25 = EXP_DIR / "xxql2501_v20260917_refresh"
REFRESH_26 = EXP_DIR / "xxql2601_v20260917_refresh"
REFRESH_FA = EXP_DIR / "xxql2502_v20260917_refresh"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sync_bundle(src_dir: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    # Remove existing files that might be obsolete
    for f in list(dst_dir.iterdir()):
        if f.is_file():
            f.unlink()
    
    # Copy all files from src_dir
    for src_file in src_dir.iterdir():
        if src_file.is_file():
            dst_file = dst_dir / src_file.name
            shutil.copy2(src_file, dst_file)
            assert sha256(src_file) == sha256(dst_file), f"Mismatch: {dst_file}"
    print(f"[SYNCED] {src_dir.name} -> {dst_dir.name} ({len(list(src_dir.iterdir()))} files)")


def remove_obsolete_dirs():
    obsolete = [
        EXP_DIR / "xxql2501_page60_penv20_double_n_20260901",
        EXP_DIR / "xxql2601_page25_double_n_imputed_lai_20260901",
        EXP_DIR / "xxql2601_page34_penv19_double_n_imputed_lai_20260901",
        EXP_DIR / "xxql2601_page36_penv16_double_n_imputed_lai_20260901",
    ]
    for d in obsolete:
        if d.is_dir():
            shutil.rmtree(d)
            print(f"[REMOVED OBSOLETE] {d.name}")


def main():
    print("Starting bundle synchronization and cleanup...")
    # 1. Sync aliases
    sync_bundle(REFRESH_25, EXP_DIR / "XXQL2501")
    sync_bundle(REFRESH_25, EXP_DIR / "xxql2501_unified_20260914")

    sync_bundle(REFRESH_26, EXP_DIR / "XXQL2601")
    sync_bundle(REFRESH_26, EXP_DIR / "xxql2601_unified_20260914")

    sync_bundle(REFRESH_FA, EXP_DIR / "XXQL2502")
    sync_bundle(REFRESH_FA, EXP_DIR / "xxql2502_unified_20260914")

    # 2. Clean obsolete ad-hoc untracked trial dirs
    remove_obsolete_dirs()

    print("Bundle synchronization and cleanup complete!")


if __name__ == "__main__":
    main()
