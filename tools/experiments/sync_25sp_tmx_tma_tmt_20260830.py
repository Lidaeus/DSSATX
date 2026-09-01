import os
import shutil
from pathlib import Path

root = Path(".").resolve()
ref_tmx = root / "data/user/ref/XXQL2501.TMX"
ref_out = root / "data/user/ref/DSSAT文件/2025春/DSSAT输出_v2"
ref_tma = ref_out / "XXQL2501.TMA"
ref_tmt = ref_out / "XXQL2501.TMT"

ref_tmx_text = ref_tmx.read_text(encoding="utf-8")
ref_tma_bytes = ref_tma.read_bytes()
ref_tmt_bytes = ref_tmt.read_bytes()

updated_tmx = 0
updated_tma = 0
updated_tmt = 0
failed = []

for p in root.rglob("XXQL2501.TM*"):
    if ".git" in p.parts:
        continue
    name = p.name
    if name == "XXQL2501.TMX":
        if p.resolve() == ref_tmx.resolve(): continue
        try:
            tmp = p.with_suffix(".sync_tmp")
            tmp.write_text(ref_tmx_text, encoding="utf-8")
            os.replace(tmp, p)
            updated_tmx += 1
        except Exception as e:
            failed.append((str(p), str(e)))
            
    elif name == "XXQL2501.TMA":
        if p.resolve() == ref_tma.resolve(): continue
        try:
            tmp = p.with_suffix(".sync_tmp")
            tmp.write_bytes(ref_tma_bytes)
            os.replace(tmp, p)
            updated_tma += 1
        except Exception as e:
            failed.append((str(p), str(e)))

    elif name == "XXQL2501.TMT":
        if p.resolve() == ref_tmt.resolve(): continue
        try:
            tmp = p.with_suffix(".sync_tmp")
            tmp.write_bytes(ref_tmt_bytes)
            os.replace(tmp, p)
            updated_tmt += 1
        except Exception as e:
            failed.append((str(p), str(e)))

print(f"Total synchronized -> TMX: {updated_tmx}, TMA: {updated_tma}, TMT: {updated_tmt}")
if failed:
    print(f"Failed count: {len(failed)}")
    for path, err in failed[:10]:
        print(f"  {path}: {err}")
else:
    print("All files synchronized successfully!")
