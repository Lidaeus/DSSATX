@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0\..\.."
echo Launching T10 DRY-ONLY smoke (CHFPW dropped, CHPDT only; 20 reals / 1 update)...
echo Single-season (25SP + 25FA) and joint multiseason will run sequentially.
python "%~dp0run_t10_dryonly.py" --scope both --smoke %*
set "T10_EXIT_CODE=%ERRORLEVEL%"
if not "%T10_EXIT_CODE%"=="0" echo Dry-only smoke stopped with exit code %T10_EXIT_CODE%. Inspect the printed run directory and its run_status.json.
endlocal
