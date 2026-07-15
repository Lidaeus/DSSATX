"""Set up the run directory for the improved weight scheme calibration.

This copies all necessary files from workspace to the run directory,
then runs PEST++ IES in parallel.

Usage:
    python workspace/setup_improved_run.py
"""
import shutil
import os
import sys

src_dir = "d:/Tomato_Cal/workspace"
run_dir = "d:/Tomato_Cal/workspace/runs/eggplant_stage2_v14_improved"
pst_case = "eggplant_stage2_v14_improved"

os.makedirs(run_dir, exist_ok=True)

needed = {
    ".pst",
    ".ins",
    ".tpl",
    ".tmt",
    ".tmx",
    ".v48",
    ".OUT",
    ".csv",
    ".txt",
    ".py",
    ".json",
    ".yaml",
}

stub_content = '''"""Stub entry point - redirects to the actual run_dssat.py.

Placed here for PEST++ IES model command execution.
When PEST++ calls this from a run directory, it sets PEST_OUT_DIR
so the model writes pest output files back to the PEST++ run directory.
"""
import os, sys, subprocess
_project_root = "d:/Tomato_Cal"
_actual = os.path.join(_project_root, "workspace", "run_dssat.py")

pest_run_dir = os.getcwd()
runs_marker = os.path.join(_project_root, "workspace", "runs")
pest_run_dir_norm = os.path.normpath(os.path.normcase(pest_run_dir))
runs_marker_norm = os.path.normpath(os.path.normcase(runs_marker))
if pest_run_dir_norm.startswith(runs_marker_norm) and os.path.basename(pest_run_dir_norm) != "runs":
    env = os.environ.copy()
    env["PEST_OUT_DIR"] = pest_run_dir
    model_cwd = os.path.join(_project_root, "workspace")
else:
    env = os.environ.copy()
    model_cwd = None

result = subprocess.run([sys.executable, _actual] + sys.argv[1:], cwd=model_cwd, env=env)
sys.exit(result.returncode)
'''

stub_path = os.path.join(run_dir, "run_dssat.py")

skip_patterns = {"__pycache__", ".pyc", "eggplant_stage2_v14_full"}

copied = []
for f in os.listdir(src_dir):
    if any(s in f for s in skip_patterns):
        continue
    src = os.path.join(src_dir, f)
    dst = os.path.join(run_dir, f)
    if os.path.isfile(src):
        ext = os.path.splitext(f)[1].lower()
        if ext in needed or any(f.endswith(s) for s in [".OUT", ".csv", ".py", ".json", ".yaml", ".v48"]):
            shutil.copy2(src, dst)
            copied.append(f)

with open(stub_path, "w") as f:
    f.write(stub_content)

if not os.path.exists(os.path.join(run_dir, f"{pst_case}.pst")):
    raise FileNotFoundError(f"PST file not found: {pst_case}.pst")

print(f"Run directory set up at: {run_dir}")
print(f"Files copied: {len(copied)}")
print("\nPST file:", os.path.exists(os.path.join(run_dir, f"{pst_case}.pst")))
print("run_dssat.py:", os.path.exists(os.path.join(run_dir, "run_dssat.py")))
print("DSSBatch.v48:", os.path.exists(os.path.join(run_dir, "DSSBatch.v48")))
print("PestEval.OUT.ins:", os.path.exists(os.path.join(run_dir, "eggplant_stage2_v14_improved_PestEval.OUT.ins")))
print("PestJoint.OUT.ins:", os.path.exists(os.path.join(run_dir, "eggplant_stage2_v14_improved_PestJoint.OUT.ins")))
print("PestTmtGrow.OUT.ins:", os.path.exists(os.path.join(run_dir, "eggplant_stage2_v14_improved_PestTmtGrow.OUT.ins")))
print("PestHarvest.OUT.ins:", os.path.exists(os.path.join(run_dir, "eggplant_stage2_v14_improved_PestHarvest.OUT.ins")))
