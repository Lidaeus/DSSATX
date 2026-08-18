@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
cd /d "%~dp0\..\.."

set "BOUNDS_ID=eggplant_e02_sobol23_e01review_laisafe_v4_20260728"
set "BOUNDS_FILE=data\parameter_registry\bounds_frozen\eggplant\%BOUNDS_ID%.csv"

echo ==================================================================
echo E02 formal single-season conditional calibration: 200 x 4
echo ==================================================================
echo Bounds: %BOUNDS_ID%
echo Agents: 4
echo Seasons: 25SP, 25FA, 26SP (sequential; 8 treatments each)
echo 26SP is a model-development diagnostic, not independent validation.
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

echo [1/3] Checking for an existing calibration process...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$busy = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'pestpp-ies|DSCSM048|python' -and $_.CommandLine -match 'Tomato_Cal.*(run_parallel|run_calibration_experiment|pestpp-ies)' }; if ($busy) { $busy | Select-Object ProcessId,Name,CommandLine | Format-List; exit 2 }"
if errorlevel 1 (
  echo ERROR: a PEST++/DSSAT calibration process appears to be active.
  echo Wait for it to finish or verify it manually before retrying.
  goto :failed
)

echo [2/3] Running harvest-reader and experiment-contract preflight tests...
python -m pytest tests\test_t10_direct_harvest.py tests\test_experiment_spec.py -q
if errorlevel 1 (
  echo ERROR: preflight tests failed. E02 was not started.
  goto :failed
)

if /I "%~1"=="--check-only" (
  echo.
  echo CHECK-ONLY passed. No calibration was started.
  exit /b 0
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%I"
set "RUN_PREFIX=e02_formal_200x4_%RUN_STAMP%"
set "LAUNCH_LOG=workspace\runs\%RUN_PREFIX%_launcher.log"

echo [3/3] Starting formal E02 sequentially...
echo Run prefix: %RUN_PREFIX%
echo Launcher log: %LAUNCH_LOG%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$runs=@(@{s='25sp';spec='configs/experiments/specs/E02_single23_25sp.json'},@{s='25fa';spec='configs/experiments/specs/E02_single23_25fa.json'},@{s='26sp';spec='configs/experiments/specs/E02_single23_26sp.json'});" ^
  "foreach($r in $runs) {" ^
  "  Write-Host ('=== E02 ' + $r.s + ' ===');" ^
  "  & python tools/calibration/run_calibration_experiment.py --spec $r.spec --run-dir ('workspace/runs/%RUN_PREFIX%_' + $r.s) --execute --n-agents 4;" ^
  "  if($LASTEXITCODE -ne 0){ throw ('E02 ' + $r.s + ' failed with exit code ' + $LASTEXITCODE) }" ^
  "} 2>&1 | Tee-Object -FilePath '%LAUNCH_LOG%'; exit $LASTEXITCODE"

set "E02_EXIT_CODE=%ERRORLEVEL%"
if not "%E02_EXIT_CODE%"=="0" (
  echo.
  echo E02 stopped with exit code %E02_EXIT_CODE%.
  echo Inspect %LAUNCH_LOG% and the relevant run_status.json.
  goto :failed
)

echo.
echo E02 formal runs completed.
exit /b 0

:failed
echo.
echo E02 formal calibration was not successfully completed.
exit /b 1
