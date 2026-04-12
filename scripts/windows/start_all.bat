@echo off
chcp 65001 >nul
setlocal

set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%"

set "BACKEND_PORT=%RAG_API_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8083"

set "FRONTEND_PORT=%RAG_WEB_PORT%"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5185"

set "PYTHON_EXE=%RAG_PYTHON%"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

echo ============================================
echo    RAG System One-Click Start
echo ============================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

start "RAG-Backend" cmd /k "cd /d ""%ROOT_DIR%"" && ""%PYTHON_EXE%"" scripts\run_api.py --host 127.0.0.1 --port %BACKEND_PORT% --reload"
start "RAG-Frontend" cmd /k "cd /d ""%ROOT_DIR%\frontend"" && npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%"

echo Backend:  http://127.0.0.1:%BACKEND_PORT%
echo Frontend: http://127.0.0.1:%FRONTEND_PORT%
echo.

popd

