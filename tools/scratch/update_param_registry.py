import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / "src/common/param_registry.py"
text = p.read_text(encoding="utf-8")

if '"PLDP":    (1.0,  30.0),' not in text:
    text = text.replace('"PLWT":    (1.0,  20.0),', '"PLWT":    (1.0,  20.0),\n    "PLDP":    (1.0,  30.0),')
if '"PLDP":    (5.0, 15.0),' not in text:
    text = text.replace('"PLWT":    (4.0, 9.5),', '"PLWT":    (4.0, 12.0),\n    "PLDP":    (5.0, 15.0),')

# Write to temp file in same directory and replace
tmp_p = p.with_name(p.name + ".tmp")
tmp_p.write_text(text, encoding="utf-8")
os.replace(tmp_p, p)
print("Updated param_registry.py with PLDP and expanded PLWT bounds")
