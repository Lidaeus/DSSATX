"""Create 13-layer refined soil input packages for 25SP, 25FA, 26SP.

Refines the 100-180 cm layer into 20 cm increments:
- Layer 10: 100-120 cm (SLB=120, SLLL=0.170, SDUL=0.310, SSAT=0.420, SRGF=0.100, SBDM=1.52, SLOC=0.08)
- Layer 11: 120-140 cm (SLB=140, SLLL=0.173, SDUL=0.300, SSAT=0.390, SRGF=0.070, SBDM=1.54, SLOC=0.06)
- Layer 12: 140-160 cm (SLB=160, SLLL=0.175, SDUL=0.295, SSAT=0.370, SRGF=0.040, SBDM=1.55, SLOC=0.05)
- Layer 13: 160-180 cm (SLB=180, SLLL=0.176, SDUL=0.290, SSAT=0.350, SRGF=0.020, SBDM=1.55, SLOC=0.05)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "data/user/experiments"

V3_MAPPING = {
    "25SP": ("xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820", "xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"),
    "25FA": ("xxql2502_actual_trial_calibration_v8_measuredn_20260820", "xxql2502_actual_trial_calibration_v9_13layer_20260820"),
    "26SP": ("xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820", "xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"),
}

NEW_13_LAYERS = """     5     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    10     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    20     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    30     2  .150  .320  .430  .850  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99
    40     2  .150  .320  .430  .650  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99
    50     3  .172  .330  .440  .450  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    60     3  .172  .330  .440  .300  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   120     6  .170  .310  .420  .100  0.24  1.52  0.08  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .300  .390  .070  0.24  1.54  0.06  35.0  30.0   -99   -99   -99   -99   -99   -99
   160     6  .175  .295  .370  .040  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .020  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""


def create_13layer_bundles() -> list[str]:
    created = []
    for season, (src_name, dst_name) in V3_MAPPING.items():
        src_path = EXP_DIR / src_name
        dst_path = EXP_DIR / dst_name
        
        if dst_path.exists():
            shutil.rmtree(dst_path)
        shutil.copytree(src_path, dst_path)
        
        # Modify SOIL.SOL in dst_path
        soil_path = dst_path / "SOIL.SOL"
        lines = soil_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        
        new_lines = []
        in_target_soil = False
        in_layers = False
        
        for l in lines:
            if l.startswith("*IBTM910017"):
                in_target_soil = True
                new_lines.append("*IBTM910017  SCS           CL     180  Orangeburg Sandy Loam (13-Layer Refined)")
                continue
            elif in_target_soil and l.startswith("*") and not l.startswith("*IBTM910017"):
                in_target_soil = False
                in_layers = False
                new_lines.append(l)
                continue
                
            if in_target_soil:
                if l.startswith("@  SLB"):
                    in_layers = True
                    new_lines.append(l)
                    new_lines.extend(NEW_13_LAYERS.splitlines())
                    continue
                elif in_layers:
                    # skip old layer lines
                    continue
                else:
                    new_lines.append(l)
            else:
                new_lines.append(l)
                
        soil_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        
        # Update manifest in dst_path
        manifest_path = dst_path / "input_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bundle_id"] = dst_name
            manifest["package_name"] = dst_name
            manifest["notes"] = f"Refined 13-layer soil profile (100-180cm partitioned to 20cm increments) derived from {src_name}"
            # Recompute file hashes as a list of dicts
            file_hashes = []
            for p in sorted(dst_path.glob("*")):
                if p.is_file() and p.name != "input_manifest.json":
                    file_hashes.append({
                        "name": p.name,
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "bytes": p.stat().st_size
                    })
            manifest["files"] = file_hashes
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            
        print(f"Created 13-layer bundle: {dst_path}")
        created.append(dst_name)
    return created


if __name__ == "__main__":
    create_13layer_bundles()
