"""Build clean 5-layer 0-60cm experiment bundles matching manifest schema."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP_25_BASE = ROOT / "data/user/experiments/xxql2501_rootzone_9layer_30cm_20260822"
EXP_26_BASE = ROOT / "data/user/experiments/xxql2601_rootzone_9layer_30cm_20260822"

EXP_25_5L = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
EXP_26_5L = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"


def generate_soil_sol_60cm(src_soil_path: Path, dst_soil_path: Path):
    text = src_soil_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    layer_def = """@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
    60     1  .150  .320  .450  .900  0.23  1.50  0.65  35.0  30.0   -99  0.05   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .305  .400  .080  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""
    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("*IBTM910017"):
            new_lines.append(l)
            i += 1
            while i < len(lines) and not lines[i].startswith("@  SLB"):
                new_lines.append(lines[i])
                i += 1
            new_lines.append(layer_def)
            while i < len(lines) and not lines[i].startswith("*IBPP910015"):
                i += 1
        else:
            new_lines.append(l)
            i += 1
    dst_soil_path.write_text("\n".join(new_lines), encoding="utf-8")


def generate_5layer_tmx(src_tmx_path: Path, dst_tmx_path: Path, yr: str, plwt_val: float):
    text = src_tmx_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    
    new_lines = []
    in_planting = False
    
    for l in lines:
        if l.startswith("*PLANTING DETAILS"):
            in_planting = True
            new_lines.append(l)
        elif in_planting:
            if l.startswith("@P"):
                new_lines.append(l)
            elif l.strip() and not l.startswith("*") and not l.startswith("@"):
                # Exact fixed format for 60cm deep plow
                new_lines.append(f" 2 {yr}075   -99   2.7   2.7     T     R    90    90     8   {plwt_val:3.1f}    60    25     1     8                        Eggplant")
                in_planting = False
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)
            
    dst_tmx_path.write_text("\n".join(new_lines), encoding="utf-8")


def main():
    for exp_dst, exp_src, sname, yr in [
        (EXP_25_5L, EXP_25_BASE, "XXQL2501", "25"),
        (EXP_26_5L, EXP_26_BASE, "XXQL2601", "26")
    ]:
        if exp_dst.exists():
            shutil.rmtree(exp_dst)
        shutil.copytree(exp_src, exp_dst)
        generate_soil_sol_60cm(exp_src / "SOIL.SOL", exp_dst / "SOIL.SOL")
        generate_5layer_tmx(exp_src / f"{sname}.TMX", exp_dst / f"{sname}.TMX", yr, 9.5)
        
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
    print("5-Layer 0-60cm Bundles cleanly created with updated manifest hashes!")


if __name__ == "__main__":
    main()
