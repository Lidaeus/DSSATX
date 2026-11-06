@echo off
setlocal
cd /d D:\Tomato_Cal

echo [1/3] Building/checking layer-mean initial-condition bundles...
if exist data\user\experiments\xxql2501_layermean_ic_v1_20260801\input_manifest.json if exist data\user\experiments\xxql2601_layermean_ic_v1_20260801\input_manifest.json (
  echo Bundles already exist; preserving immutable derived inputs.
) else (
  python tools\experiments\derive_layermean_initial_conditions_bundles_20260801.py
  if errorlevel 1 exit /b %errorlevel%
)

echo [2/3] Launching 200x5 four-corner calibration with reopened bounds...
python tools\calibration\run_e02_wnstress_fourcorner.py ^
  --run-id e02_wnstress_fourcorner_layermeanic_formal_200x5_20260801 ^
  --bounds-id eggplant_e02_wnstress_fourcorner_layermeanic_v1_20260801 ^
  --design D:\Tomato_Cal\configs\runs\eggplant_e02_wnstress_fourcorner_layermeanic_design_v1_20260801.json ^
  --input-dir D:\Tomato_Cal\data\user\experiments\xxql2501_layermean_ic_v1_20260801 ^
  --n-reals 200 --noptmax 5 --n-agents 6 --random-seed 20260801 --execute
if errorlevel 1 exit /b %errorlevel%

echo [3/3] Calibration completed and engineering gate passed.
endlocal
