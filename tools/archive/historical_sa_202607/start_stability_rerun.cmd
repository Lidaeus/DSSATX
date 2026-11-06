@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\sa\rerun_unstable_sa.py --all
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Completed: all predeclared stability and convergence gates passed.
) else if "%RC%"=="2" (
  echo Completed: outputs were produced, but at least one gate remains unmet. Review the campaign reports.
) else (
  echo Stopped with error %RC%. No existing sensitivity result directory was overwritten.
)
pause
exit /b %RC%
