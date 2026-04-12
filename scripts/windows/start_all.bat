@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%"

set "BACKEND_PORT=%RAG_API_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8083"

set "FRONTEND_PORT=%RAG_WEB_PORT%"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5185"

set "PYTHON_EXE=%RAG_PYTHON%"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

set "NPM_CMD=%RAG_NPM%"
if "%NPM_CMD%"=="" (
    for /f "delims=" %%I in ('where npm.cmd 2^>nul') do if not defined NPM_CMD set "NPM_CMD=%%I"
)
if "%NPM_CMD%"=="" set "NPM_CMD=npm.cmd"

echo ============================================
echo    RAG System One-Click Start
echo ============================================
echo.

echo Stopping existing services...
powershell -Command "Get-NetTCPConnection -LocalPort %BACKEND_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Force -Id $_ -ErrorAction SilentlyContinue }"
powershell -Command "Get-NetTCPConnection -LocalPort %FRONTEND_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Force -Id $_ -ErrorAction SilentlyContinue }"

echo Waiting for port release...
timeout /t 2 /nobreak >nul

echo Starting backend on port %BACKEND_PORT%...
start "RAG-Backend" /D "%ROOT_DIR%" "%PYTHON_EXE%" scripts\run_api.py --host 127.0.0.1 --port %BACKEND_PORT% --reload

echo Starting frontend on port %FRONTEND_PORT%...
start "RAG-Frontend" /D "%ROOT_DIR%\frontend" "%NPM_CMD%" run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%

echo.
echo Backend:  http://127.0.0.1:%BACKEND_PORT%
echo Frontend: http://127.0.0.1:%FRONTEND_PORT%
echo.
echo Press any key to exit...
popd
pause >nul
