import subprocess, os, shutil
DSSAT_EXE = 'DSCSM048.EXE'
run_dir = 'd:/Tomato_Cal/workspace'
exe_path = os.path.join(run_dir, DSSAT_EXE)
print(f'exe_path: {exe_path}, exists: {os.path.exists(exe_path)}')
result = subprocess.run([exe_path, 'B', 'DSSBatch.v48'], cwd=run_dir, capture_output=True, text=True)
print(f'returncode: {result.returncode}')
print(f'stdout: {result.stdout[:200] if result.stdout else "empty"}')
print(f'stderr: {result.stderr[:200] if result.stderr else "empty"}')