@echo off
rem ============================================================
rem  HARTING design review platform - one click launcher
rem  Double-click this file. It starts the platform and opens
rem  the browser by itself. Keep the window open while you use it.
rem ============================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title HARTING design review platform
set "ROOT=%~dp0"
set "PYEXE="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Report generator: turns on the "generate PDF / Word" buttons.
set "NXDRP_REPORT_PROVIDER=nxdrp.checkers.report:generate_report"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "VENV_SP=%ROOT%.venv\Lib\site-packages"
set "BASE_PY=%ROOT%.python\python.exe"

echo.
echo   HARTING design review platform
echo   Folder: %ROOT%
echo.

if not exist "%ROOT%nxdrp\checkers\__init__.py" goto :missing_project

rem ---------- 1) the bundled .venv (normal case) ----------
rem If the folder was copied from another machine the .venv still
rem remembers the old Python path; repoint it at .python\python.exe.
if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import sys" >nul 2>nul
  if errorlevel 1 call :repair_venv
)
if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import fastapi, uvicorn" >nul 2>nul
  if not errorlevel 1 set "PYEXE=%VENV_PY%"
)

rem ---------- 2) bundled base runtime + the .venv packages ----------
if not defined PYEXE if exist "%BASE_PY%" (
  set "PYTHONPATH=%VENV_SP%"
  "%BASE_PY%" -c "import fastapi, uvicorn" >nul 2>nul
  if not errorlevel 1 set "PYEXE=%BASE_PY%"
)

rem ---------- 3) python on PATH, must be 3.12+ ----------
if not defined PYEXE (
  python -c "import sys;raise SystemExit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)

rem ---------- 4) py launcher ----------
if not defined PYEXE (
  for %%V in (3.13 3.12) do if not defined PYEXE (
    for /f "delims=" %%P in ('py -%%V -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
  )
)

rem ---------- 5) usual install locations ----------
if not defined PYEXE (
  for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
  ) do if not defined PYEXE if exist %%D set "PYEXE=%%~D"
)

if not defined PYEXE goto :no_python

echo   Python: %PYEXE%
echo.
"%PYEXE%" "%ROOT%tools\launch_platform.py" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo   [ERROR] The platform exited with code %CODE%.
  echo   Keep this window open and send the text above.
  pause
)
exit /b %CODE%

rem ============================================================
rem  helpers
rem ============================================================
:repair_venv
echo   Repairing .venv for this machine, one time only...
> "%ROOT%.venv\pyvenv.cfg" echo home = %ROOT%.python
>>"%ROOT%.venv\pyvenv.cfg" echo include-system-site-packages = false
>>"%ROOT%.venv\pyvenv.cfg" echo version = 3.12.14
>>"%ROOT%.venv\pyvenv.cfg" echo executable = %BASE_PY%
>>"%ROOT%.venv\pyvenv.cfg" echo command = %BASE_PY% -m venv %ROOT%.venv
exit /b 0

:missing_project
echo   [ERROR] Project files are missing next to this .cmd.
echo   This normally means the file was double-clicked INSIDE the ZIP archive.
echo   Extract the whole ZIP to a normal folder first, then run this .cmd there.
echo   Current folder: %ROOT%
echo.
pause
exit /b 1

:no_python
echo   [ERROR] No usable Python 3.12 environment found.
echo   Expected one of these two to start:
echo     %VENV_PY%
echo     %BASE_PY%
echo   Neither works, so the folder is incomplete. Re-extract the whole
echo   package to a normal folder and double-click this file again.
echo.
pause
exit /b 1
