@echo off
title RAG System Launcher
echo ============================================
echo    RAG System One-Click Start
echo ============================================
echo.

set "BACKEND_PORT=8083"
set "FRONTEND_PORT=5185"
set "CONDA_PYTHON=D:\Anaconda\envs\RAG\python.exe"

echo [Step 1/4] Stopping old processes...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    echo      Killing backend process PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    echo      Killing frontend process PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)

echo      Done
echo.
timeout /t 2 /nobreak >nul

echo [Step 2/4] Checking environment...

if not exist "%CONDA_PYTHON%" (
    echo [ERROR] Python not found: %CONDA_PYTHON%
    pause
    exit /b 1
)

echo      Python OK
echo.

echo [Step 3/4] Starting backend...
cd /d "F:\Projects\RAG_System\backend"
start "RAG-Backend" cmd /k "%CONDA_PYTHON% -m uvicorn app.main:app --host 127.0.0.1 --port 8083 --reload"

echo      Backend started at http://127.0.0.1:8083
echo.
timeout /t 3 /nobreak >nul

echo [Step 4/4] Starting frontend...
cd /d "F:\Projects\RAG_System\frontend"
start "RAG-Frontend" cmd /k "npm run dev"

echo      Frontend started at http://localhost:5185
echo.

echo ============================================
echo    All services started!
echo ============================================
echo.
pause
