@echo off
setlocal
cd /d "%~dp0"
call where.exe npm.cmd >nul 2>&1
if errorlevel 1 (
    echo Install Node.js with npm and add it to PATH.
    goto fail
)
call setup_local.bat
if errorlevel 1 goto fail
pushd frontend
call npm.cmd install
if errorlevel 1 (
    popd
    goto fail
)
popd
set "DATA_BASE_URL="
set "VITE_API_BASE="
set "ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173"
if not exist data\index.json echo No forecast data found. Run train_local.bat first.
start "Stock Forecast API" /D "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
start "" "http://localhost:5173"
cd frontend
echo Open http://localhost:5173 after Vite is ready.
echo Close the API window and press Ctrl+C here to stop the services.
call npm.cmd run dev -- --host localhost --port 5173 --strictPort
if errorlevel 1 goto fail
exit /b 0
:fail
echo Local startup failed. Check the error above.
pause
exit /b 1
