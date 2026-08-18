@echo off
setlocal
cd /d D:\Tomato_Cal
python tools\calibration\run_e02_v2_spring_wn_20260802.py --run-id e02_v2_spring_wn_canopy_soil_150x4_20260802 --n-reals 150 --noptmax 4 --n-agents 6 --execute
if errorlevel 1 exit /b 1
endlocal
