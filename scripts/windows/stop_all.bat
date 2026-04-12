@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "BACKEND_PORT=%RAG_API_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8083"

set "FRONTEND_PORT=%RAG_WEB_PORT%"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5185"

echo ============================================
echo    RAG System Stop Services
echo ============================================
echo.

echo Stopping backend (port %BACKEND_PORT%)...
powershell -Command "Get-NetTCPConnection -LocalPort %BACKEND_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Force -Id $_ -ErrorAction SilentlyContinue }"

echo Stopping frontend (port %FRONTEND_PORT%)...
powershell -Command "Get-NetTCPConnection -LocalPort %FRONTEND_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Force -Id $_ -ErrorAction SilentlyContinue }"

echo Stopping residual window processes...
taskkill /F /FI "WINDOWTITLE eq RAG-Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq RAG-Frontend*" >nul 2>&1

echo.
echo All services stopped.
echo.
