@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

call "%SCRIPT_DIR%build_exe.bat"
if errorlevel 1 exit /b 1

powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%pin_taskbar.ps1"

echo Completed. If pinning failed, pin dist\GachonMealWidget.exe manually.
exit /b 0
