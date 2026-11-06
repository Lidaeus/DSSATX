@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\calibration\run_e02_three_season_defaultn_replan.py --n-reals 150 --noptmax 5 --n-agents 6 --response-target observed_shape --execute
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo Calibration failed with exit code %EXITCODE%.
) else (
  echo Calibration completed and passed the engineering gate.
)
exit /b %EXITCODE%
