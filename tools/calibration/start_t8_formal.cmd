@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\calibration\run_t8_formal_multiseason.py
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo T8 formal calibration failed with exit code %RC%.
  pause
)
exit /b %RC%
