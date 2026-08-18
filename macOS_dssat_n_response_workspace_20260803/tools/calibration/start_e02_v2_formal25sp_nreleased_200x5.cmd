@echo off
setlocal
cd /d D:\Tomato_Cal
python tools\calibration\run_e02_v2_formal25sp_20260802.py --run-id e02_v2_formal25sp_nreleased_200x5_20260802 --n-reals 200 --noptmax 5 --n-agents 6 --execute
if errorlevel 1 exit /b 1
endlocal
