@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
python tools\calibration\run_e02_v2_joint25sp26sp_nosoil_nresp_20260802.py --run-id e02_v2_joint25sp26sp_nosoil_nresp_200x4_20260802 --n-reals 200 --noptmax 4 --n-agents 6 --execute
if errorlevel 1 exit /b 1
endlocal
