@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%"

set "BACKEND_PORT=%RAG_API_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8084"

set "FRONTEND_PORT=%RAG_WEB_PORT%"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5185"

set "PYTHON_EXE=%RAG_PYTHON%"
if "%PYTHON_EXE%"=="" (
    if exist "%USERPROFILE%\anaconda3\envs\RAG\python.exe" (
        set "PYTHON_EXE=%USERPROFILE%\anaconda3\envs\RAG\python.exe"
    ) else if exist "C:\ProgramData\anaconda3\envs\RAG\python.exe" (
        set "PYTHON_EXE=C:\ProgramData\anaconda3\envs\RAG\python.exe"
    ) else if exist "D:\Anaconda\envs\RAG\python.exe" (
        set "PYTHON_EXE=D:\Anaconda\envs\RAG\python.exe"
    ) else (
        set "PYTHON_EXE=python"
    )
)

set "API_RELOAD=%RAG_API_RELOAD%"
set "BACKEND_EXTRA_ARGS="
if /I "%API_RELOAD%"=="1" set "BACKEND_EXTRA_ARGS=--reload"
if /I "%API_RELOAD%"=="true" set "BACKEND_EXTRA_ARGS=--reload"

set "NPM_CMD=%RAG_NPM%"
if "%NPM_CMD%"=="" (
    for /f "delims=" %%I in ('where npm.cmd 2^>nul') do if not defined NPM_CMD set "NPM_CMD=%%I"
)
if "%NPM_CMD%"=="" set "NPM_CMD=npm.cmd"

echo ============================================
echo    RAG System One-Click Start
echo ============================================
echo.

if not "%CONDA_DEFAULT_ENV%"=="RAG" (
    echo [INFO] Activating conda environment 'RAG'...
    call conda activate RAG 2>nul
    if not "%CONDA_DEFAULT_ENV%"=="RAG" (
        echo [WARN] Could not auto-activate 'RAG' environment.
        echo        Make sure conda is initialized for cmd.exe.
    )
)

echo Stopping existing services...
powershell -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'scripts\\run_api.py' -and $_.CommandLine -match '--port %BACKEND_PORT%' } | ForEach-Object { Stop-Process -Force -Id $_.ProcessId -ErrorAction SilentlyContinue }"
powershell -Command "Get-NetTCPConnection -LocalPort %BACKEND_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Force -Id $_ -ErrorAction SilentlyContinue }"
powershell -Command "Get-NetTCPConnection -LocalPort %FRONTEND_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Force -Id $_ -ErrorAction SilentlyContinue }"
taskkill /F /FI "WINDOWTITLE eq RAG-Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq RAG-Frontend*" >nul 2>&1

echo Waiting for port release...
timeout /t 2 /nobreak >nul

echo Starting backend on port %BACKEND_PORT%...
start "RAG-Backend" /D "%ROOT_DIR%" "%PYTHON_EXE%" scripts\run_api.py --host 127.0.0.1 --port %BACKEND_PORT% %BACKEND_EXTRA_ARGS%

echo Starting frontend on port %FRONTEND_PORT%...
start "RAG-Frontend" /D "%ROOT_DIR%\frontend" "%NPM_CMD%" run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%

echo.
echo Backend:  http://127.0.0.1:%BACKEND_PORT%
echo Frontend: http://127.0.0.1:%FRONTEND_PORT%
echo.
echo Press any key to exit...
popd
pause >nul
