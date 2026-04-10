@echo off
chcp 65001 >nul
title RAG System Stopper
echo ============================================
echo    RAG System Stop Services
echo ============================================
echo.

set "BACKEND_PORT=8083"
set "FRONTEND_PORT=5185"

echo [1/3] Stopping backend (port %BACKEND_PORT%)...
set "FOUND_BACK=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    echo      Killing backend PID: %%a
    taskkill /F /PID %%a >nul 2>&1
    set "FOUND_BACK=1"
)
if "%FOUND_BACK%"=="0" echo      No backend process found
echo.

echo [2/3] Stopping frontend (port %FRONTEND_PORT%)...
set "FOUND_FRONT=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    echo      Killing frontend PID: %%a
    taskkill /F /PID %%a >nul 2>&1
    set "FOUND_FRONT=1"
)
if "%FOUND_FRONT%"=="0" echo      No frontend process found
echo.

echo [3/3] Cleaning up...
taskkill /F /IM uvicorn.exe >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq RAG-Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq RAG-Frontend*" >nul 2>&1
echo      Cleanup done
echo.

echo ============================================
echo    All services stopped
echo ============================================
pause
