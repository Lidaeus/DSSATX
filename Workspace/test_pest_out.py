import os, sys

# Simulate what happens when PEST++ runs the stub from the run directory
# and the stub runs workspace/run_dssat.py

# When this runs from run directory (simulating PEST++ environment)
pest_run_dir = os.getcwd()
_project_root = "d:/Tomato_Cal"
runs_marker = os.path.join(_project_root, "workspace", "runs")
pest_run_dir_norm = os.path.normpath(os.path.normcase(pest_run_dir))
runs_marker_norm = os.path.normpath(os.path.normcase(runs_marker))
in_runs = pest_run_dir_norm.startswith(runs_marker_norm) and os.path.basename(pest_run_dir_norm) != "runs"
print(f"CWD: {pest_run_dir}")
print(f"runs_marker: {runs_marker}")
print(f"pest_run_dir_norm: {pest_run_dir_norm}")
print(f"runs_marker_norm: {runs_marker_norm}")
print(f"startswith: {pest_run_dir_norm.startswith(runs_marker_norm)}")
print(f"basename: {os.path.basename(pest_run_dir_norm)}")
print(f"in_runs: {in_runs}")

if in_runs:
    env = os.environ.copy()
    env["PEST_OUT_DIR"] = pest_run_dir
    model_cwd = os.path.join(_project_root, "workspace")
else:
    env = os.environ.copy()
    model_cwd = None

print(f"PEST_OUT_DIR will be: {env.get('PEST_OUT_DIR', 'NOT SET')}")
print(f"model_cwd: {model_cwd}")

# Now simulate what happens when workspace/run_dssat.py exec's src/dssat/run_dssat.py
print(f"\nInside exec'd code:")
print(f"os.getcwd(): {os.getcwd()}")
print(f"os.environ.get('PEST_OUT_DIR'): {os.environ.get('PEST_OUT_DIR', 'NOT SET')}")

def _get_pest_out_dir():
    return os.environ.get("PEST_OUT_DIR") or os.getcwd()

print(f"_get_pest_out_dir(): {_get_pest_out_dir()}")