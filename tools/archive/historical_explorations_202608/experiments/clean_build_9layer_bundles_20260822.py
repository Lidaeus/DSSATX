"""Build clean 9-layer experiment bundles matching manifest schema."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP_25_BASE = ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"
EXP_26_BASE = ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"

EXP_25_9L = ROOT / "data/user/experiments/xxql2501_rootzone_9layer_30cm_20260822"
EXP_26_9L = ROOT / "data/user/experiments/xxql2601_rootzone_9layer_30cm_20260822"

import sys
sys.path.insert(0, str(ROOT / "tools/experiments"))
from exp_9layer_30cm_tillage_soil_plwt_ladder_20260822 import generate_9layer_soil_sol, generate_9layer_tmx


def main():
    for exp_dst, exp_src, sname, yr in [
        (EXP_25_9L, EXP_25_BASE, "XXQL2501", "25"),
        (EXP_26_9L, EXP_26_BASE, "XXQL2601", "26")
    ]:
        if exp_dst.exists():
            shutil.rmtree(exp_dst)
        shutil.copytree(exp_src, exp_dst)
        generate_9layer_soil_sol(exp_src / "SOIL.SOL", exp_dst / "SOIL.SOL")
        generate_9layer_tmx(exp_src / f"{sname}.TMX", exp_dst / f"{sname}.TMX", yr, 7.0)
        
        # Remove any stray genotype files if copied before
        for f in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base", "TMGRO048.SPE"]:
            p = exp_dst / f
            if p.exists():
                p.unlink()

        # Update sha256 in manifest
        manifest_path = exp_dst / "input_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bundle_id"] = exp_dst.name
            manifest["package_name"] = exp_dst.name
            
            def _update_file_list(flist):
                for entry in flist:
                    fn = entry.get("name") or entry.get("filename") or entry.get("relative_path")
                    if fn and (exp_dst / fn).exists():
                        b = (exp_dst / fn).read_bytes()
                        entry["sha256"] = hashlib.sha256(b).hexdigest()
                        entry["bytes"] = len(b)
                        
            files_dict = manifest.get("files", {})
            if isinstance(files_dict, dict):
                for k, v in files_dict.items():
                    if isinstance(v, list):
                        _update_file_list(v)
            elif isinstance(files_dict, list):
                _update_file_list(files_dict)
                
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("9-Layer Bundles cleanly created with updated manifest hashes!")


if __name__ == "__main__":
    main()
