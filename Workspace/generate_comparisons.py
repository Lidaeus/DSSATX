"""Generate deterministic comparison CSVs and plots for eggplant calibration."""
import sys
import os

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

from src.reporting.analyze_results import (
    deterministic_process_compare,
    deterministic_harvest_compare
)

PREFIX = "eggplant_stage2_v14_full"
BATCH_FILE = "d:/Tomato_Cal/workspace/DSSBatch.v48"
WORKSPACE = "d:/Tomato_Cal/workspace"

print("="*70)
print("Generating Deterministic Comparison CSVs")
print("="*70)

print("\n[1] Generating process comparison CSV...")
process_csv = deterministic_process_compare(
    prefix=PREFIX,
    batch_file=BATCH_FILE,
    var_names=["L#SD", "LAID", "LWAD", "SWAD"],
    run_dir=WORKSPACE
)
print(f"Generated: {process_csv}")

print("\n[2] Generating harvest comparison CSV...")
harvest_csv = deterministic_harvest_compare(
    prefix=PREFIX,
    batch_file=BATCH_FILE,
    run_dir=WORKSPACE
)
print(f"Generated: {harvest_csv}")

print("\n" + "="*70)
print("Comparison CSVs Generated Successfully!")
print("="*70)