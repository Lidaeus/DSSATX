@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
cd /d "%~dp0\..\.."

echo ==================================================================
echo E02 joint M1 calibration: 54 shared + 7 autumn offsets, 300 x 6
echo ==================================================================
echo 25SP uses shared parameters.
echo 25FA uses documented effective offsets for LFMAX, SLAVR, XFRT,
echo SFDUR, TB1, TB2, and TB3.
echo Offsets are conditional seasonal corrections, not genetic coefficients.
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: python is not available on PATH.
  exit /b 1
)

echo [1/2] Running seasonal-offset and safety tests...
python -m pytest tests\test_seasonal_parameters.py tests\test_t10_m1_stability.py tests\test_bounds_injection_preflight.py tests\test_e02_55_weight_contract.py -q
if errorlevel 1 (
  echo ERROR: preflight tests failed.
  exit /b 1
)

if /I "%~1"=="--check-only" (
  echo CHECK-ONLY passed. No calibration was started.
  exit /b 0
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%I"
set "RUN_ID=e02_joint61_m1_offsets_300x6_%RUN_STAMP%"

echo [2/2] Starting formal M1 calibration...
echo Run ID: %RUN_ID%
python tools\calibration\run_e02_joint61_m1_offsets.py --run-id "%RUN_ID%" --n-reals 300 --noptmax 6 --n-agents 6 --random-seed 20260730 --execute
set "RUN_EXIT=%ERRORLEVEL%"
if not "%RUN_EXIT%"=="0" (
  echo ERROR: M1 calibration stopped with exit code %RUN_EXIT%.
  exit /b %RUN_EXIT%
)

echo E02 joint M1 calibration completed.
exit /b 0
