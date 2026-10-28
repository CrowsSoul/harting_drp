@echo off
rem ============================================================
rem  HARTING report / knowledge base launcher
rem  Double-click this file, then open the URL printed below.
rem ============================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title HARTING report workbench

rem Same one-time repair as the platform launcher: a .venv copied from another
rem machine still remembers the old Python path, so repoint it at .python.
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>nul
  if errorlevel 1 if exist "%~dp0.python\python.exe" call :repair_venv
)

set "REPORT_ENTRY=%~dp0nxdrp\checkers\report\start_report.ps1"
if not exist "%REPORT_ENTRY%" set "REPORT_ENTRY=%~dp0start_report.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPORT_ENTRY%" %*
set "REPORT_EXIT=%ERRORLEVEL%"
if not "%REPORT_EXIT%"=="0" echo 报告 launch failed. Please keep this window open and share the error above.
if not defined NXDRP_NO_PAUSE pause
exit /b %REPORT_EXIT%

:repair_venv
echo Repairing .venv for this machine, one time only...
> "%~dp0.venv\pyvenv.cfg" echo home = %~dp0.python
>>"%~dp0.venv\pyvenv.cfg" echo include-system-site-packages = false
>>"%~dp0.venv\pyvenv.cfg" echo version = 3.12.14
>>"%~dp0.venv\pyvenv.cfg" echo executable = %~dp0.python\python.exe
>>"%~dp0.venv\pyvenv.cfg" echo command = %~dp0.python\python.exe -m venv %~dp0.venv
exit /b 0
