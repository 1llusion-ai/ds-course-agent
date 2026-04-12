@echo off
chcp 65001 >nul
setlocal

set "BACKEND_PORT=%RAG_API_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8083"

set "FRONTEND_PORT=%RAG_WEB_PORT%"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5185"

echo ============================================
echo    RAG System Stop Services
echo ============================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

taskkill /F /FI "WINDOWTITLE eq RAG-Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq RAG-Frontend*" >nul 2>&1

echo Done.
echo.

