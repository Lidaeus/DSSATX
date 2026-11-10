import os
import sys
import json
import hashlib
from pathlib import Path

ROOT = Path("D:/Tomato_Cal")
sys.path.insert(0, str(ROOT))
from src.common.project import sha256_file
from src.common.input_manifest import verify_manifest_integrity

TAV_NEW = 20.0
AMP_NEW = 6.0

def update_wth_content(file_path: Path, tav: float, amp: float):
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines(keepends=True)
    new_lines = []
    header_found = False
    for line in lines:
        if "@ INSI" in line:
            header_found = True
            new_lines.append(line)
        elif header_found and ("XXLI" in line or "XXQL" in line or len(line.split()) >= 6):
            parts = line.split()
            if len(parts) >= 6:
                insi = parts[0]
                lat = float(parts[1])
                lon = float(parts[2])
                elev = float(parts[3])
                refht = parts[6] if len(parts) > 6 else "-99.0"
                wndht = parts[7] if len(parts) > 7 else "-99.0"
                new_line = f"  {insi:<4s}  {lat:6.3f}  {lon:7.3f}    {elev:2.0f}  {tav:4.1f}   {amp:3.1f} {refht:>5s} {wndht:>5s}\n"
                new_lines.append(new_line)
                header_found = False
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    file_path.write_text("".join(new_lines), encoding="utf-8")
    print(f"Updated {file_path} with TAV={tav:.1f}, AMP={amp:.1f}")

# 1. Update raw weather files
raw_wths = [
    ROOT / "data/raw/weather/XXLI2502.WTH",
    ROOT / "data/raw/experiments/XXQL2601.WTH",
    ROOT / "data/raw/weather/XXQL2601.WTH",
]
for p in raw_wths:
    if p.exists():
        update_wth_content(p, TAV_NEW, AMP_NEW)

# 2. Update experiment bundle files and manifests
bundles = {
    "25SP": ("xxql2501_corrected_20260923", "XXLI2502.WTH"),
    "26SP": ("xxql2601_corrected_20260923", "XXQL2601.WTH"),
    "25FA": ("xxql2502_corrected_20260923", "XXLI2502.WTH"),
}

bundle_manifest_hashes = {}

for season, (bname, wth_name) in bundles.items():
    bdir = ROOT / "data/user/experiments" / bname
    wth_path = bdir / wth_name
    update_wth_content(wth_path, TAV_NEW, AMP_NEW)
    
    # Update input_manifest.json
    manifest_path = bdir / "input_manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    wth_sha256 = sha256_file(wth_path)
    wth_bytes = wth_path.stat().st_size
    
    found = False
    for fentry in manifest_data["files"]:
        if fentry["name"] == wth_name:
            fentry["sha256"] = wth_sha256
            fentry["size_bytes"] = wth_bytes
            found = True
            break
            
    if not found:
        manifest_data["files"].append({
            "name": wth_name,
            "sha256": wth_sha256,
            "size_bytes": wth_bytes
        })
        
    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated input_manifest.json for {bname}: {wth_name} sha256={wth_sha256[:10]}... bytes={wth_bytes}")
    
    # Verify manifest integrity
    im = verify_manifest_integrity(bdir)
    print(f"Verified manifest integrity for {bname}: OK! Manifest hash: {im.manifest_sha256}")
    bundle_manifest_hashes[season] = {
        "bundle_id": bname,
        "manifest_sha256": im.manifest_sha256
    }

# 3. Update configs/experiments/current_bundles.json
current_bundles_path = ROOT / "configs/experiments/current_bundles.json"
curr_data = json.loads(current_bundles_path.read_text(encoding="utf-8"))
curr_data["as_of"] = "2026-09-30"
curr_data["notes"] = "Promoted Scheme 1 corrected bundles with greenhouse soil thermal boundary calibration (TAV=20.0°C, AMP=6.0°C)"
curr_data["bundles"] = bundle_manifest_hashes

current_bundles_path.write_text(json.dumps(curr_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Updated {current_bundles_path} successfully!")
