@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0\..\.."
echo Launching T10 DRY-ONLY FORMAL calibration (CHFPW dropped, CHPDT only; 200 reals / 4 updates)...
echo Single-season (25SP + 25FA) and joint multiseason will run sequentially.
echo Review assumption_based_sigma_v5_dryonly.csv (CHPDT sigma=200) and the dry-only
echo group policy (HARVEST_FRESH removed) before launching. This is a long run.
python "%~dp0run_t10_dryonly.py" --scope both %*
set "T10_EXIT_CODE=%ERRORLEVEL%"
if not "%T10_EXIT_CODE%"=="0" echo Dry-only formal launch stopped with exit code %T10_EXIT_CODE%. Inspect the printed run directory and its run_status.json.
endlocal
