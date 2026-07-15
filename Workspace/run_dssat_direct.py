import sys
import os
import subprocess
import shutil

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

print("="*70)
print("Step 1: Running DSSAT Model")
print("="*70)

dssat_exe = "d:/Tomato_Cal/workspace/DSCSM048.EXE"
batch_file = "d:/Tomato_Cal/workspace/DSSBatch.v48"

print(f"DSSAT Exe: {dssat_exe}")
print(f"Batch file: {batch_file}")
print(f"Working dir: {os.getcwd()}")

if not os.path.exists(dssat_exe):
    print(f"ERROR: DSSAT executable not found at {dssat_exe}")
    sys.exit(1)

result = subprocess.run(
    [dssat_exe, "B", batch_file],
    cwd="d:/Tomato_Cal/workspace",
    capture_output=True,
    text=True,
    timeout=300
)

print(f"\nDSSAT Exit Code: {result.returncode}")
if result.stdout:
    print(f"STDOUT:\n{result.stdout[:2000]}")
if result.stderr:
    print(f"STDERR:\n{result.stderr[:1000]}")

print("\n" + "="*70)
print("Step 2: Checking Generated Files")
print("="*70)

output_files = [
    "PlantGro.OUT", "FreshWt.OUT", "Summary.OUT",
    "Evaluate.OUT", "PestEval.OUT", "PestJoint.OUT",
    "PestHarvest.OUT", "PestTmtGrow.OUT"
]
for f in output_files:
    fpath = os.path.join("d:/Tomato_Cal/workspace", f)
    if os.path.exists(fpath):
        print(f"  FOUND: {f} ({os.path.getsize(fpath)} bytes)")
    else:
        print(f"  MISSING: {f}")

print("\n" + "="*70)
print("Step 3: Generating PEST Output Files")
print("="*70)

from src.dssat.run_dssat import (
    _write_pest_eval_from_evaluate,
    _write_pest_joint_from_evaluate,
    _write_pest_harvest_from_tmt_and_freshwt,
    _write_pest_tmtgrow_from_tmt_and_plantgro,
    PEST_EVAL_FILE, PEST_JOINT_FILE, PEST_HARVEST_FILE, PEST_TMTGROW_FILE
)

workspace_dir = "d:/Tomato_Cal/workspace"

evaluate_out = os.path.join(workspace_dir, "Evaluate.OUT")
plantgro_out = os.path.join(workspace_dir, "PlantGro.OUT")
freshwt_out = os.path.join(workspace_dir, "FreshWt.OUT")
tmt_path = os.path.join(workspace_dir, "XXQL2501.TMT")

if os.path.exists(evaluate_out):
    pest_eval_path = os.path.join(workspace_dir, PEST_EVAL_FILE)
    _write_pest_eval_from_evaluate(evaluate_out, pest_eval_path)
    print(f"Generated: {pest_eval_path}")

    pest_joint_path = os.path.join(workspace_dir, PEST_JOINT_FILE)
    _write_pest_joint_from_evaluate(evaluate_out, pest_joint_path)
    print(f"Generated: {pest_joint_path}")
else:
    print(f"WARNING: {evaluate_out} not found")

if os.path.exists(freshwt_out) and os.path.exists(tmt_path):
    pest_harvest_path = os.path.join(workspace_dir, PEST_HARVEST_FILE)
    _write_pest_harvest_from_tmt_and_freshwt(batch_file, freshwt_out, pest_harvest_path, tmt_path=tmt_path, harvest_var="CHPDT")
    print(f"Generated: {pest_harvest_path}")
else:
    print(f"WARNING: freshwt_out or tmt_path not found")

if os.path.exists(plantgro_out):
    pest_tmtgrow_path = os.path.join(workspace_dir, PEST_TMTGROW_FILE)
    _write_pest_tmtgrow_from_tmt_and_plantgro(batch_file, plantgro_out, pest_tmtgrow_path, tmt_path=tmt_path)
    print(f"Generated: {pest_tmtgrow_path}")
else:
    print(f"WARNING: {plantgro_out} not found")

print("\n" + "="*70)
print("Final File Check")
print("="*70)
for f in output_files:
    fpath = os.path.join(workspace_dir, f)
    if os.path.exists(fpath):
        print(f"  FOUND: {f} ({os.path.getsize(fpath)} bytes)")
    else:
        print(f"  MISSING: {f}")