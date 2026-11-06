@echo off
REM T9 D1 high-dimensional joint calibration launcher.
REM Double-click or run from project root. Uses 600 realizations, noptmax=2, 8 agents.
cd /d D:\Tomato_Cal
python tools\calibration\run_t9_formal_multiseason.py
pause
