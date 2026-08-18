@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0\..\.."
echo ==================================================================
echo E01 sub-domain pre-calibration FORMAL run (200 reals / 4 updates)
echo ==================================================================
echo 7 sub-trials will run sequentially (25SP/25FA x pheno/organ/yield/yield-strict).
echo 25FA pheno is skipped (no valid ADAP observations per matrix section 3).
echo Each sub-trial: 200 realizations, 4 IES updates, 8 agents, seed 20260723.
echo This is a long run (hours). Press Ctrl+C to abort.
echo.
echo Review the sub-trial list in tools/calibration/run_e01_formal.py before launching.
echo To run a subset: python tools/calibration/run_e01_formal.py --only yield_strict_25sp yield_strict_25fa
echo.
python "%~dp0run_e01_formal.py" %*
set "E01_EXIT_CODE=%ERRORLEVEL%"
if not "%E01_EXIT_CODE%"=="0" echo E01 formal run stopped with exit code %E01_EXIT_CODE%. Inspect the printed run directories and their run_status.json.
endlocal
