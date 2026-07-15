"""Stub entry point - redirects to the actual run_dssat.py implementation.

When PEST++ calls this from a run directory (workspace/runs/<case>/),
the stub detects it and sets PEST_OUT_DIR so the model writes pest
output files back to the PEST++ run directory.

The DSSAT model and inputs are found relative to the project workspace,
so the actual model still runs from the workspace directory.
"""
import os
import sys
import subprocess

_this_file = __file__
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(_this_file))))
_workspace_run_dssat = os.path.join(_project_root, "workspace", "run_dssat.py")

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

result = subprocess.run(
    [sys.executable, _workspace_run_dssat] + sys.argv[1:],
    cwd=model_cwd,
    env=env
)
sys.exit(result.returncode)
