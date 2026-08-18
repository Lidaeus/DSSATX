@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
cd /d "%~dp0\..\.."

set "SPEC=configs\experiments\specs\E02_joint54_25sp_25fa_20260729.json"
set "BOUNDS=data\parameter_registry\bounds_frozen\eggplant\eggplant_e02_joint54_v2_20260729.csv"

echo ==================================================================
echo E02 joint 25SP + 25FA shared-parameter calibration: 300 x 6
echo ==================================================================
echo Parameters: 54 shared CUL/ECO/SPE parameters; FL-VS fixed at 100
echo Inputs: moisture-corrected 25SP + 25FA
echo Authority: 25SP ADAP=21 d; both seasons PAGE=25 d, SPRL=-99
echo Phi: phenology, canopy, biomass, plant N, dry CHPDT+HPODW, soil water
echo MDAP and fresh harvest remain diagnostic-only.
echo.

if not exist "%SPEC%" (
  echo ERROR: experiment spec is missing: %SPEC%
  goto :failed
)
if not exist "%BOUNDS%" (
  echo ERROR: frozen bounds are missing: %BOUNDS%
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
  goto :failed
)

echo [2/3] Running contract preflight tests...
python -m pytest tests\test_t10_direct_harvest.py tests\test_experiment_spec.py tests\test_e02_55_weight_contract.py -q
if errorlevel 1 (
  echo ERROR: preflight tests failed. Joint calibration was not started.
  goto :failed
)

if /I "%~1"=="--check-only" (
  echo CHECK-ONLY passed. No calibration was started.
  exit /b 0
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%I"
set "RUN_DIR=workspace\runs\e02_joint54_25sp_25fa_300x6_%RUN_STAMP%"

echo [3/3] Starting joint calibration...
echo Run directory: %RUN_DIR%
python tools\calibration\run_calibration_experiment.py --spec "%SPEC%" --run-dir "%RUN_DIR%" --execute --n-agents 6
set "RUN_EXIT=%ERRORLEVEL%"
if not "%RUN_EXIT%"=="0" (
  echo Joint calibration failed with exit code %RUN_EXIT%.
  goto :failed
)

echo Joint calibration completed.
exit /b 0

:failed
echo.
echo E02 joint calibration was not successfully completed.
exit /b 1
