@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "APP_NAME=GachonMenu"
set "DISPLAY_NAME=Gachon Menu"
set "LEGACY_APP_NAME=GachonMealWidget"
set "LEGACY_DISPLAY_NAME=Gachon Meal Widget"
set "SOURCE_EXE=%SCRIPT_DIR%dist\%APP_NAME%.exe"
set "SOURCE_ICON=%SCRIPT_DIR%assets\images\black_logo.ico"
set "INSTALL_DIR=%LOCALAPPDATA%\Programs\%APP_NAME%"
set "TARGET_EXE=%INSTALL_DIR%\%APP_NAME%.exe"
set "TARGET_ICON=%INSTALL_DIR%\black_logo.ico"
set "LEGACY_DESKTOP_LINK=%USERPROFILE%\Desktop\%LEGACY_DISPLAY_NAME%.lnk"
set "LEGACY_START_MENU_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\%LEGACY_DISPLAY_NAME%.lnk"

echo [1/8] Building executable...
call "%SCRIPT_DIR%build_exe.bat"
if errorlevel 1 goto :fail

if not exist "%SOURCE_EXE%" (
    echo Build output missing: "%SOURCE_EXE%"
    goto :fail
)

echo [2/8] Closing running app (if any)...
taskkill /IM "%APP_NAME%.exe" /F >nul 2>&1
taskkill /IM "%LEGACY_APP_NAME%.exe" /F >nul 2>&1

echo [3/8] Preparing install directory...
if not exist "%INSTALL_DIR%" (
    mkdir "%INSTALL_DIR%"
    if errorlevel 1 goto :fail
)

echo [4/8] Copying executable...
set "COPY_OK="
for /L %%I in (1,1,5) do (
    copy /Y "%SOURCE_EXE%" "%TARGET_EXE%" >nul
    if not errorlevel 1 set "COPY_OK=1"
    if defined COPY_OK goto :copy_done
    timeout /t 1 >nul
)
:copy_done
if not defined COPY_OK goto :fail

if exist "%SOURCE_ICON%" (
    copy /Y "%SOURCE_ICON%" "%TARGET_ICON%" >nul
)

echo [5/8] Removing SmartScreen block (Mark of the Web)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -Path '%TARGET_EXE%' -Stream 'Zone.Identifier' -ErrorAction SilentlyContinue; if (Test-Path '%TARGET_ICON%') { Remove-Item -Path '%TARGET_ICON%' -Stream 'Zone.Identifier' -ErrorAction SilentlyContinue }"

echo [6/8] Adding Windows Defender exclusion...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Add-MpPreference -ExclusionPath '%INSTALL_DIR%' -ErrorAction Stop; Write-Host 'Defender exclusion added.' } catch { Write-Host 'Skipped (needs admin or Defender not active).' }"

echo [7/8] Creating desktop/start menu shortcuts...
if exist "%LEGACY_DESKTOP_LINK%" del /Q "%LEGACY_DESKTOP_LINK%"
if exist "%LEGACY_START_MENU_LINK%" del /Q "%LEGACY_START_MENU_LINK%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'; $targets = @((Join-Path $desktop '%DISPLAY_NAME%.lnk'), (Join-Path $startMenu '%DISPLAY_NAME%.lnk')); $iconPath = if (Test-Path '%TARGET_ICON%') { '%TARGET_ICON%' } else { '%TARGET_EXE%' }; foreach ($path in $targets) { $s = $ws.CreateShortcut($path); $s.TargetPath = '%TARGET_EXE%'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = ($iconPath + ',0'); $s.Save() }"
if errorlevel 1 goto :fail

echo [8/8] Refreshing taskbar pin (optional)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%pin_taskbar.ps1" -ExePath "%TARGET_EXE%"

echo Install complete.
echo You can launch "%DISPLAY_NAME%" from desktop/start menu.
start "" "%TARGET_EXE%"
exit /b 0

:fail
echo Install failed. Review the messages above.
exit /b 1
