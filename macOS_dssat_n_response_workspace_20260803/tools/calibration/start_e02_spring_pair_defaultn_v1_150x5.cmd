@echo off
setlocal
cd /d "%~dp0\..\.."

echo [1/3] Ensuring PAGE25 default-N bundles...
if exist data\user\experiments\xxql2501_special_defaultn_page25_v1_20260730 if exist data\user\experiments\xxql2601_special_defaultn_page25_v1_20260730 (
  echo Bundles already exist, skip derivation.
) else (
  python tools\experiments\derive_two_spring_defaultn_page25_bundles_20260730.py
  if errorlevel 1 exit /b %errorlevel%
)

echo [2/3] Preparing and freezing bounds...
python tools\calibration\prepare_e02_spring_pair_defaultn_v1_bounds.py
if errorlevel 1 exit /b %errorlevel%
if exist data\parameter_registry\bounds_frozen\eggplant\eggplant_e02_spring_pair_defaultn_v1_20260730.csv (
  echo Frozen bounds already exist, skip freeze.
) else (
  python tools\freeze_bounds.py ^
    --proposal data\parameter_registry\bounds_proposals\eggplant_e02_spring_pair_defaultn_v1_20260730.csv ^
    --crop eggplant ^
    --bounds-id eggplant_e02_spring_pair_defaultn_v1_20260730 ^
    --notes "两个春季默认硝态氮铵态氮率定v1：restore stage4_full_v12 legacy ranges where available; keep current safe skeleton for constrained rows; FL-VS fixed 120; SOIL_SLPF 0.90-0.96"
  if errorlevel 1 exit /b %errorlevel%
)

echo [3/3] Launching formal 150x5 calibration with 7 agents...
python tools\calibration\run_e02_spring_pair_defaultn_v1.py --n-reals 150 --noptmax 5 --n-agents 7 --execute
exit /b %errorlevel%
