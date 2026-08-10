@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem --- WSL bridge: stop services started via start_all.bat ---
rem --cd pins the WSL working directory; see start_all.bat for rationale.

set "RAG_WSL_DISTRO=%RAG_WSL_DISTRO%"
if "%RAG_WSL_DISTRO%"=="" set "RAG_WSL_DISTRO=Ubuntu-22.04"

set "WSL_ROOT=%RAG_WSL_ROOT%"
if "%WSL_ROOT%"=="" set "WSL_ROOT=/home/xiaofan/Projects/ds-course-agent"

echo [INFO] Stopping RAG services (WSL)...
wsl.exe -d %RAG_WSL_DISTRO% --cd %WSL_ROOT% -- bash scripts/wsl/stop.sh
set "RC=%errorlevel%"
exit /b %RC%
