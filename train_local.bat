@echo off
setlocal
cd /d "%~dp0"
call setup_local.bat
if errorlevel 1 goto fail
".venv\Scripts\python.exe" backend\run_all.py %*
if errorlevel 1 goto fail
echo Training complete. You can now run run_local.bat.
pause
exit /b 0
:fail
echo Training failed. Check the error above.
pause
exit /b 1
