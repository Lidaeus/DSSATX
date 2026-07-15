import sys
import os

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

print("="*70)
print("Running DSSAT Model using refactored run_dssat.py")
print("="*70)

from src.dssat.run_dssat import run_dssat_broadcast

batch_file = "d:/Tomato_Cal/workspace/DSSBatch.v48"
output_dir = "d:/Tomato_Cal/workspace"

print(f"Batch file: {batch_file}")
print(f"Output dir: {output_dir}")

try:
    results = run_dssat_broadcast(
        batch_file=batch_file,
        output_dir=output_dir,
        dssat_exe="DSCSM048.EXE",
        generate_pest_output=True,
        harvest_var="CHPDT",
        max_workers=1,
    )

    print(f"\nDSSAT run completed!")
    print(f"Results: {len(results)} entries processed")

    for r in results[:3]:
        print(f"  Run {r.get('run')}: success={r.get('success')}")

except Exception as e:
    print(f"\nError running DSSAT: {e}")
    import traceback
    traceback.print_exc()

print("\nChecking for generated files:")
pest_files = [
    "PestEval.OUT",
    "PestJoint.OUT",
    "PestHarvest.OUT",
    "PestTmtGrow.OUT",
    "Evaluate.OUT"
]
for f in pest_files:
    fpath = os.path.join(output_dir, f)
    if os.path.exists(fpath):
        print(f"  FOUND: {f} ({os.path.getsize(fpath)} bytes)")
    else:
        print(f"  MISSING: {f}")