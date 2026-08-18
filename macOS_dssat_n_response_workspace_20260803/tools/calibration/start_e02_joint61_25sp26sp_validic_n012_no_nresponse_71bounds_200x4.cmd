@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

set "RUN_ID=e02_joint61_25sp26sp_validic_n012_no_nresponse_formal_200x4_71bounds_20260801"
set "DESIGN=configs\runs\eggplant_e02_joint61_25sp26sp_layermeanic_n012_no_nresponse_v1_20260801.json"
set "INPUT=data\user\experiments\xxql2501_layermean_ic_valid_n012_v1_20260801"
set "POLICY=configs\runs\e02_plantn_chpdtlog_noadap_no_nresponse_v1.csv"
set "BOUNDS=eggplant_e02_wnstress_fourcorner_v1_20260801"

if not exist "%DESIGN%" (
  echo ERROR: missing design %DESIGN%
  exit /b 1
)
if not exist "%INPUT%\XXQL2501.TMX" (
  echo ERROR: missing validated-IC 25SP bundle %INPUT%
  exit /b 1
)
if not exist "data\user\experiments\xxql2601_layermean_ic_valid_n012_v1_20260801\XXQL2601.TMX" (
  echo ERROR: missing validated-IC 26SP bundle
  exit /b 1
)
if not exist "data\parameter_registry\bounds_frozen\eggplant\%BOUNDS%.csv" (
  echo ERROR: missing frozen bounds file %BOUNDS%
  exit /b 1
)

echo Starting %RUN_ID% (Sobol initial ensemble, 200 realizations x 4 IES iterations)
echo Frozen bounds: %BOUNDS% (71 active rows; spring design applies 64 shared rows)
echo Calibration seasons: 25SP + 26SP; treatments N0/N1/N2 only; N3 excluded
python tools\calibration\run_e02_wnstress_fourcorner.py ^
  --run-id "%RUN_ID%" ^
  --n-reals 200 ^
  --noptmax 4 ^
  --n-agents 6 ^
  --random-seed 20260801 ^
  --bounds-id "%BOUNDS%" ^
  --design "%DESIGN%" ^
  --input-dir "%INPUT%" ^
  --observation-policy-csv "%POLICY%" ^
  --execute
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo Formal calibration failed with exit code %RC%.
  exit /b %RC%
)
echo Formal calibration completed: workspace\runs\%RUN_ID%
endlocal
