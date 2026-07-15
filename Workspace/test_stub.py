import os, sys, subprocess, shutil

_project_root = 'd:/Tomato_Cal'
_workspace_run_dssat = os.path.join(_project_root, 'workspace', 'run_dssat.py')

pest_run_dir = os.getcwd()
runs_marker = os.path.join(_project_root, 'workspace', 'runs')
model_cwd = os.path.join(_project_root, 'workspace')

print('pest_run_dir:', pest_run_dir)
print('runs_marker:', runs_marker)
print('startswith:', pest_run_dir.startswith(runs_marker))
print('basename:', os.path.basename(pest_run_dir))
print('model_cwd:', model_cwd)
print('CWD of stub:', os.getcwd())

exe_path = os.path.join(model_cwd, 'DSCSM048.EXE')
print('exe_path:', exe_path, 'exists:', os.path.exists(exe_path))

result = subprocess.run([exe_path, 'B', 'DSSBatch.v48'], cwd=model_cwd, capture_output=True, text=True)
print('returncode:', result.returncode)
print('stdout:', result.stdout[:200] if result.stdout else 'empty')
print('stderr:', result.stderr[:200] if result.stderr else 'empty')