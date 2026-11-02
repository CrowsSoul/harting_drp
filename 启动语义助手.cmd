@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "%ROOT%release\HartingDRP_NX.exe" (
  start "" "%ROOT%release\HartingDRP_NX.exe"
  exit /b 0
)
if not exist "%ROOT%.desktop-venv\Scripts\python.exe" goto setup
if not exist "%ROOT%nxdrp\checkers\platform_web\frontend\dist\index.html" goto setup
"%ROOT%.desktop-venv\Scripts\python.exe" "%ROOT%desktop.py" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%
:setup
echo 请先按 docs\DEVELOPMENT.md 安装环境并运行 build_desktop.ps1。
echo 本入口打开主平台，登录后选择“语义指令”；不会自动安装依赖。
pause
exit /b 1
