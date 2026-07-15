import sys
import os

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

from src.dssat.run_dssat import (
    _write_pest_tmtgrow_from_tmt_and_plantgro,
    PEST_TMTGROW_FILE
)

batch_file = "d:/Tomato_Cal/workspace/DSSBatch.v48"
plantgro_out = "d:/Tomato_Cal/workspace/PlantGro.OUT"
tmt_path = "d:/Tomato_Cal/workspace/XXQL2501.TMT"
pest_tmtgrow_path = "d:/Tomato_Cal/workspace/PestTmtGrow_test.OUT"

print("Calling _write_pest_tmtgrow_from_tmt_and_plantgro...")
_write_pest_tmtgrow_from_tmt_and_plantgro(
    batch_file=batch_file,
    plantgro_path=plantgro_out,
    pest_tmtgrow_path=pest_tmtgrow_path,
    tmt_path=tmt_path
)

print(f"\nGenerated file: {pest_tmtgrow_path}")
with open(pest_tmtgrow_path, 'r') as f:
    lines = f.readlines()
    print(f"Total lines: {len(lines)}")

print("\nFirst 5 lines:")
for line in lines[:5]:
    print(f"  {line.rstrip()}")

print("\nLast 5 lines:")
for line in lines[-5:]:
    print(f"  {line.rstrip()}")