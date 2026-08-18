@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0\..\.."
echo Launching matched 25SP then 25FA single-season T10 diagnostic calibrations...
python "%~dp0run_t10_single_season_diagnostic.py" %*
set "T10_EXIT_CODE=%ERRORLEVEL%"
if not "%T10_EXIT_CODE%"=="0" echo Diagnostic launch stopped with exit code %T10_EXIT_CODE%. Inspect the printed run directory and its run_status.json.
endlocal
