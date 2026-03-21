@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "APP_NAME=GachonMealWidget"
set "DISPLAY_NAME=Gachon Meal Widget"
set "SOURCE_EXE=%SCRIPT_DIR%dist\%APP_NAME%.exe"
set "INSTALL_DIR=%LOCALAPPDATA%\Programs\%APP_NAME%"
set "TARGET_EXE=%INSTALL_DIR%\%APP_NAME%.exe"

echo [1/6] Building executable...
call "%SCRIPT_DIR%build_exe.bat"
if errorlevel 1 goto :fail

if not exist "%SOURCE_EXE%" (
    echo Build output missing: "%SOURCE_EXE%"
    goto :fail
)

echo [2/6] Closing running app (if any)...
taskkill /IM "%APP_NAME%.exe" /F >nul 2>&1

echo [3/6] Preparing install directory...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if errorlevel 1 goto :fail

echo [4/6] Copying executable...
copy /Y "%SOURCE_EXE%" "%TARGET_EXE%" >nul
if errorlevel 1 goto :fail

echo [5/6] Creating desktop/start menu shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'; $targets = @((Join-Path $desktop '%DISPLAY_NAME%.lnk'), (Join-Path $startMenu '%DISPLAY_NAME%.lnk')); foreach ($path in $targets) { $s = $ws.CreateShortcut($path); $s.TargetPath = '%TARGET_EXE%'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = '%TARGET_EXE%,0'; $s.Save() }"
if errorlevel 1 goto :fail

echo [6/6] Refreshing taskbar pin (optional)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%pin_taskbar.ps1" -ExePath "%TARGET_EXE%"

echo Install complete.
echo You can launch "%DISPLAY_NAME%" from desktop/start menu.
start "" "%TARGET_EXE%"
exit /b 0

:fail
echo Install failed. Review the messages above.
exit /b 1
