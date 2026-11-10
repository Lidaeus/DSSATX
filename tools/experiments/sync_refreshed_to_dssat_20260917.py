"""Synchronize refreshed 2026-09-17 bundle files to raw and DSSAT system directories.

Ensures:
1. data/raw/experiments/ has refreshed XXQL2501, XXQL2601, XXQL2502 (.TMX, .TMA, .TMT, etc.)
2. C:\\DSSAT48\\Tomato\\ has exact matching copies of refreshed files
3. C:\\DSSAT48\\Soil\\SOIL.SOL has XXSL2501 and XXSL2601 injected
4. SHA-256 verification confirms exact equality
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DSSAT_TOMATO = Path("C:/DSSAT48/Tomato")
DSSAT_SOIL = Path("C:/DSSAT48/Soil/SOIL.SOL")

SRC_25 = ROOT / "data/user/experiments/xxql2501_v20260917_refresh"
SRC_26 = ROOT / "data/user/experiments/xxql2601_v20260917_refresh"
SRC_FA = ROOT / "data/user/experiments/xxql2502_v20260917_refresh"
RAW_EXP = ROOT / "data/raw/experiments"
RAW_SOIL = ROOT / "data/raw/soil/SOIL.SOL"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sync_files():
    raise SystemExit("Retired 2026-09-17 sync: run from the three current input bundles instead")
    RAW_EXP.mkdir(parents=True, exist_ok=True)
    DSSAT_TOMATO.mkdir(parents=True, exist_ok=True)

    mappings = [
        (SRC_25, ["XXQL2501.TMX", "XXQL2501.TMA", "XXQL2501.TMT"]),
        (SRC_26, ["XXQL2601.TMX", "XXQL2601.TMA", "XXQL2601.TMT"]),
        (SRC_FA, ["XXQL2502.TMX", "XXQL2502.TMA", "XXQL2502.TMT"]),
    ]

    for src_dir, filenames in mappings:
        for fname in filenames:
            src_file = src_dir / fname
            if not src_file.is_file():
                raise FileNotFoundError(f"Missing source file: {src_file}")
            
            # Copy to data/raw/experiments
            dst_raw = RAW_EXP / fname
            shutil.copy2(src_file, dst_raw)
            assert sha256(src_file) == sha256(dst_raw), f"Hash mismatch for {dst_raw}"
            print(f"[SYNC] {fname} -> {dst_raw}")

            # Copy to C:\DSSAT48\Tomato
            dst_dssat = DSSAT_TOMATO / fname
            shutil.copy2(src_file, dst_dssat)
            assert sha256(src_file) == sha256(dst_dssat), f"Hash mismatch for {dst_dssat}"
            print(f"[SYNC] {fname} -> {dst_dssat}")

    # Copy observation support files to RAW_EXP
    obs_files = [
        (SRC_25, ["FileA_values.csv", "FileT_values.csv", "observation_uncertainty.csv", "fruit_quality_match_audit.csv"]),
        (SRC_26, ["FileA_values.csv", "FileT_values.csv", "observation_uncertainty.csv", "fruit_quality_match_audit.csv"]),
    ]
    for src_dir, filenames in obs_files:
        pfx = "2025SPR_" if "2501" in src_dir.name else "2026SPR_"
        for fname in filenames:
            src_file = src_dir / fname
            if src_file.is_file():
                dst_raw = RAW_EXP / f"{pfx}{fname}"
                shutil.copy2(src_file, dst_raw)

    # Sync soil profiles to C:\DSSAT48\Soil\SOIL.SOL
    if DSSAT_SOIL.is_file() and RAW_SOIL.is_file():
        from tools.soil.build_dual_plot_soil_profiles_20260917 import build_soil_sol
        build_soil_sol(DSSAT_SOIL, RAW_SOIL)
        print(f"[SYNC] Updated {DSSAT_SOIL} with refreshed XXSL2501 and XXSL2601 profiles")

    print("Synchronization successfully completed!")


if __name__ == "__main__":
    sync_files()
