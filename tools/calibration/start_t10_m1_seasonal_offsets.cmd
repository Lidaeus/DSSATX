@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0\..\.."
echo Launching T10 M1: shared spring parameters plus declared autumn offsets...
python "%~dp0run_t10_m1_seasonal_offsets.py" %*
set "T10_EXIT_CODE=%ERRORLEVEL%"
if not "%T10_EXIT_CODE%"=="0" echo T10 M1 launch stopped with exit code %T10_EXIT_CODE%. Inspect the printed run directory and its run_status.json.
endlocal
