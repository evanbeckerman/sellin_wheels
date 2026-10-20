@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 launch.py
goto finished
:use_python
python launch.py
:finished
if errorlevel 1 (
  echo.
  echo If Python was not found, install Python 3.11 or newer from python.org.
  echo Enable "Add python.exe to PATH" during installation, then try again.
  pause
)
