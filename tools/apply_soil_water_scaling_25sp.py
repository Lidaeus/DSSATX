import os
import sys
import json
import re
import hashlib
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def scale_tmx_content(tmx_path):
    lines = tmx_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    new_lines = []
    in_ic = False
    modified_count_12 = 0
    modified_count_13 = 0
    
    for line in lines:
        if line.startswith("*INITIAL CONDITIONS"):
            in_ic = True
        elif in_ic and line.startswith("*"):
            in_ic = False
            
        if in_ic:
            # Treatment 12 layer lines
            m12 = re.match(r"^(\s*12\s+)(\d+)\s+([0-9.]+)(.*)$", line)
            if m12:
                depth = int(m12.group(2))
                orig_sh2o = float(m12.group(3))
                sh2o = orig_sh2o * 0.9
                tail = m12.group(4)
                new_line = f" 12  {depth:4d} {sh2o:5.3f}{tail}"
                new_lines.append(new_line)
                modified_count_12 += 1
                continue
                
            # Treatment 13 layer lines
            m13 = re.match(r"^(\s*13\s+)(\d+)\s+([0-9.]+)(.*)$", line)
            if m13:
                depth = int(m13.group(2))
                orig_sh2o = float(m13.group(3))
                sh2o = orig_sh2o * 0.8
                tail = m13.group(4)
                new_line = f" 13  {depth:4d} {sh2o:5.3f}{tail}"
                new_lines.append(new_line)
                modified_count_13 += 1
                continue
                
        new_lines.append(line)
        
    if modified_count_12 >= 5 and modified_count_13 >= 5:
        tmx_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True, modified_count_12, modified_count_13
    else:
        return False, modified_count_12, modified_count_13

def update_bundle_manifest(bundle_dir):
    manifest_path = bundle_dir / "input_manifest.json"
    if not manifest_path.exists():
        return False
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Warning: failed to load JSON from {manifest_path}: {e}")
        return False
        
    files = data.get("files", [])
    updated = False
    for f in files:
        fname = f.get("name")
        target_f = bundle_dir / fname
        if target_f.exists():
            new_sha = sha256_file(target_f)
            new_size = target_f.stat().st_size
            if f.get("sha256") != new_sha or f.get("size_bytes") != new_size:
                f["sha256"] = new_sha
                f["size_bytes"] = new_size
                updated = True
                
    if updated:
        manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return updated

def main():
    target_files = []
    
    # 1. Raw
    raw_tmx = PROJECT_ROOT / "data/raw/experiments/XXQL2501.TMX"
    if raw_tmx.exists():
        target_files.append(raw_tmx)
        
    # 2. User experiments
    for p in (PROJECT_ROOT / "data/user/experiments").rglob("XXQL2501.TMX"):
        if "_archive" not in str(p):
            target_files.append(p)
            
    # 3. Scratch working run
    scratch_tmx = PROJECT_ROOT / "scratch/eval_new_tb1_150x6/run_new_iter6_real90/25SP/XXQL2501.TMX"
    if scratch_tmx.exists():
        target_files.append(scratch_tmx)
        
    print(f"Found {len(target_files)} candidate XXQL2501.TMX files to update.")
    
    modified_tmx = 0
    updated_manifests = 0
    
    for tmx in sorted(target_files):
        ok, c12, c13 = scale_tmx_content(tmx)
        if ok:
            modified_tmx += 1
            print(f"  [OK] Modified: {tmx.relative_to(PROJECT_ROOT)} (tmt12: {c12} layers, tmt13: {c13} layers)")
            # If parent has manifest, update it
            if update_bundle_manifest(tmx.parent):
                updated_manifests += 1
                print(f"       -> Updated input_manifest.json in {tmx.parent.relative_to(PROJECT_ROOT)}")
        else:
            print(f"  [SKIP/MISMATCH] {tmx.relative_to(PROJECT_ROOT)}: c12={c12}, c13={c13}")
            
    print(f"\nSummary: Modified {modified_tmx} TMX files, updated {updated_manifests} bundle manifests.")

if __name__ == "__main__":
    main()
