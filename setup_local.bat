@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
python -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt -r backend\requirements-train.txt
if errorlevel 1 goto fail
exit /b 0
:fail
echo Setup failed. Install Python 3.10 or newer with pip and add it to PATH.
exit /b 1
