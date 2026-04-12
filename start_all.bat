@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
call "%ROOT_DIR%scripts\windows\start_all.bat"
