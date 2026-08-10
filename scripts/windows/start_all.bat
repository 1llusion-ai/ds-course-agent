@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem --- WSL bridge: this repo's dev deps live in WSL (.venv, linux node_modules) ---
rem --cd pins the WSL working directory so the relative script path below is
rem stable regardless of where cmd.exe's own cwd points (UNC cwd, mapped drive).

set "RAG_WSL_DISTRO=%RAG_WSL_DISTRO%"
if "%RAG_WSL_DISTRO%"=="" set "RAG_WSL_DISTRO=Ubuntu-22.04"

set "WSL_ROOT=%RAG_WSL_ROOT%"
if "%WSL_ROOT%"=="" set "WSL_ROOT=/home/xiaofan/Projects/ds-course-agent"

echo ============================================
echo    RAG System One-Click Start (WSL)
echo ============================================
echo.
echo [INFO] Distro : %RAG_WSL_DISTRO%
echo [INFO] WSL dir: %WSL_ROOT%
echo.

wsl.exe -d %RAG_WSL_DISTRO% --cd %WSL_ROOT% -- bash scripts/wsl/start.sh

if errorlevel 1 (
    echo.
    echo [ERROR] Startup failed ^(see messages above^).
    exit /b 1
)
exit /b 0
