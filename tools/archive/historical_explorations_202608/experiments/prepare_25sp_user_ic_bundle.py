#!/usr/bin/env python3
"""Build calibrated input bundle for 25SP using user-modified XXQL2501.TMX and Scheme 4 soil.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.project import sha256_file
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration.explore_soil_layering_for_nitrogen_response import patch_filex_mesol

BUNDLE_DIR = PROJECT_ROOT / "data/user/experiments/xxql2501_user_ic_scheme4_20260830"


def main():
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy base aux files from scheme 4 bundle
    base_src = PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830"
    for f in base_src.iterdir():
        if f.is_file() and f.name != "input_manifest.json":
            shutil.copy2(f, BUNDLE_DIR / f.name)
            
    # 2. Overwrite XXQL2501.TMX with user-modified version from data/user/experiments/XXQL2501/XXQL2501.TMX
    user_tmx = PROJECT_ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMX"
    dest_tmx = BUNDLE_DIR / "XXQL2501.TMX"
    shutil.copy2(user_tmx, dest_tmx)
    patch_filex_mesol(dest_tmx)
    
    # 3. Build input_manifest.json
    manifest = {
        "bundle_id": BUNDLE_DIR.name,
        "files": [
            {
                "name": p.name,
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            for p in sorted(BUNDLE_DIR.iterdir())
            if p.is_file() and p.name != "input_manifest.json"
        ],
    }
    (BUNDLE_DIR / "input_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    # 4. Verify bundle
    v_man = verify_calibrated_input_bundle(BUNDLE_DIR)
    print(f"[OK] Successfully built and verified bundle: {v_man.bundle_id}")
    print(f"     Payload file count: {len(v_man.files)}")


if __name__ == "__main__":
    main()
