@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

set "RUN_ID=e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801"
set "DESIGN=configs\runs\eggplant_e02_joint61_25sp25fa_validic_n012_no_nresponse_v1_20260801.json"
set "INPUT=data\user\experiments\xxql2501_layermean_ic_valid_n012_v1_20260801"
set "POLICY=configs\runs\e02_plantn_chpdtlog_noadap_no_nresponse_v1.csv"
set "BOUNDS=eggplant_e02_wnstress_fourcorner_layermeanic_v1_20260801"

if not exist "%DESIGN%" (
  echo ERROR: missing design %DESIGN%
  exit /b 1
)
if not exist "%INPUT%\XXQL2501.TMX" (
  echo ERROR: missing valid-IC 25SP bundle %INPUT%
  exit /b 1
)
if not exist "data\user\experiments\xxql2502_layermean_ic_valid_n012_v1_20260801\XXQL2502.TMX" (
  echo ERROR: missing valid-IC 25FA bundle
  exit /b 1
)

echo Starting %RUN_ID% (Sobol initial ensemble, 200 realizations x 5 IES iterations)
python tools\calibration\run_e02_wnstress_fourcorner.py ^
  --run-id "%RUN_ID%" ^
  --n-reals 200 ^
  --noptmax 5 ^
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
