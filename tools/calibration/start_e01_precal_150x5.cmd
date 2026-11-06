@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
cd /d "%~dp0\..\.."

set "BOUNDS_ID=eggplant_e01_lai_safe_v1_20260728"
set "BOUNDS_FILE=data\parameter_registry\bounds_frozen\eggplant\%BOUNDS_ID%.csv"

echo ==================================================================
echo E01 compact formal pre-calibration: 150 realizations x 5 updates
echo ==================================================================
echo Bounds: %BOUNDS_ID%
echo Agents: 4
echo Trials: 25SP/25FA organ, yield-full, and CHPDT-strict
echo Phenology-only is intentionally excluded because it has no usable
echo independent information for this formal pre-calibration stage.
echo.

if not exist "%BOUNDS_FILE%" (
  echo ERROR: frozen bounds file is missing:
  echo   %BOUNDS_FILE%
  goto :failed
)

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: python is not available on PATH.
  goto :failed
)

echo [1/3] Checking for an existing project calibration process...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$busy = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'pestpp-ies|DSCSM048|python' -and $_.CommandLine -match 'Tomato_Cal.*(run_parallel|run_e01_formal|pestpp-ies)' }; if ($busy) { $busy | Select-Object ProcessId,Name,CommandLine | Format-List; exit 2 }"
if errorlevel 1 (
  echo ERROR: an E01/PEST++/DSSAT process appears to be active.
  echo Wait for it to finish or verify it manually before retrying.
  goto :failed
)

echo [2/3] Validating the observation-noise fix and E01 contracts...
python -m pytest ^
  tests\test_p2_n1_n3.py::test_observation_noise_contract_is_explicit_and_reproducible ^
  tests\test_e01_subtrial_policies.py -q
if errorlevel 1 (
  echo ERROR: preflight tests failed. Formal pre-calibration was not started.
  goto :failed
)

if /I "%~1"=="--check-only" (
  echo.
  echo CHECK-ONLY passed. No calibration was started.
  exit /b 0
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%I"
set "RUN_PREFIX=e01_precal_formal_150x5_%RUN_STAMP%"
set "LAUNCH_LOG=workspace\runs\%RUN_PREFIX%_launcher.log"

echo [3/3] Starting formal pre-calibration...
echo Run prefix: %RUN_PREFIX%
echo Launcher log: %LAUNCH_LOG%
echo This is a long sequential run. Do not launch this script a second time.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "& python tools\calibration\run_e01_formal.py --run-prefix '%RUN_PREFIX%' --ies-num-reals 150 --noptmax 5 --n-agents 4 --only organ_25sp organ_25fa yield_full_25sp yield_full_25fa yield_strict_25sp yield_strict_25fa 2>&1 | Tee-Object -FilePath '%LAUNCH_LOG%'; exit $LASTEXITCODE"
set "E01_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%E01_EXIT_CODE%"=="0" (
  echo E01 launcher stopped with exit code %E01_EXIT_CODE%.
  echo Inspect %LAUNCH_LOG% and each run_status.json.
  goto :failed
)

echo E01 launcher completed.
echo Inspect the six run_status.json files and ies_quality reports before
echo extracting posterior bounds.
exit /b 0

:failed
echo.
echo Formal pre-calibration was not successfully completed.
exit /b 1
