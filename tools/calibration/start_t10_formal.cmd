@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0\..\.."
echo Launching repaired T10 M0 joint calibration (XFINT 0.08-0.50; advisory-only safety checks; one DSSAT retry)...
python "%~dp0run_t10_formal_multiseason.py" %*
set "T10_EXIT_CODE=%ERRORLEVEL%"
if not "%T10_EXIT_CODE%"=="0" echo T10 launch stopped with exit code %T10_EXIT_CODE%. Inspect the printed run directory and its run_status.json.
endlocal
