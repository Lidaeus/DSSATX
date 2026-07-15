import os, sys, subprocess

# This simulates what the stub does
_project_root = "d:/Tomato_Cal"
_workspace_run_dssat = os.path.join(_project_root, "workspace", "run_dssat.py")

pest_run_dir = os.getcwd()  # run directory
runs_marker = os.path.join(_project_root, "workspace", "runs")
pest_run_dir_norm = os.path.normpath(os.path.normcase(pest_run_dir))
runs_marker_norm = os.path.normpath(os.path.normcase(runs_marker))
in_runs = pest_run_dir_norm.startswith(runs_marker_norm) and os.path.basename(pest_run_dir_norm) != "runs"
print(f"Stub: in_runs={in_runs}, pest_run_dir={pest_run_dir}")

if in_runs:
    env = os.environ.copy()
    env["PEST_OUT_DIR"] = pest_run_dir
    model_cwd = os.path.join(_project_root, "workspace")
else:
    env = os.environ.copy()
    model_cwd = None

print(f"Stub: PEST_OUT_DIR will be set to: {env.get('PEST_OUT_DIR', 'NOT SET')}")
print(f"Stub: model_cwd: {model_cwd}")

# Run workspace/run_dssat.py with the environment
result = subprocess.run(
    [sys.executable, _workspace_run_dssat, "--param-csv", "test.csv", "--batch", "DSSBatch.v48", "--harvest-var", "CHPDT"],
    cwd=model_cwd,
    env=env,
    capture_output=True,
    text=True
)
print(f"\nReturn code: {result.returncode}")
print(f"Stdout: {result.stdout[:500] if result.stdout else 'empty'}")
print(f"Stderr: {result.stderr[:500] if result.stderr else 'empty'}")