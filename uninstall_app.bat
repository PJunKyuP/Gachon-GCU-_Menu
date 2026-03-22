@echo off
setlocal

set "APP_NAME=GachonMenu"
set "DISPLAY_NAME=Gachon Menu"
set "LEGACY_APP_NAME=GachonMealWidget"
set "LEGACY_DISPLAY_NAME=Gachon Meal Widget"
set "INSTALL_DIR=%LOCALAPPDATA%\Programs\%APP_NAME%"
set "LEGACY_INSTALL_DIR=%LOCALAPPDATA%\Programs\%LEGACY_APP_NAME%"
set "DESKTOP_LINK=%USERPROFILE%\Desktop\%DISPLAY_NAME%.lnk"
set "START_MENU_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\%DISPLAY_NAME%.lnk"
set "LEGACY_DESKTOP_LINK=%USERPROFILE%\Desktop\%LEGACY_DISPLAY_NAME%.lnk"
set "LEGACY_START_MENU_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\%LEGACY_DISPLAY_NAME%.lnk"

echo [1/3] Closing running app (if any)...
taskkill /IM "%APP_NAME%.exe" /F >nul 2>&1
taskkill /IM "%LEGACY_APP_NAME%.exe" /F >nul 2>&1

echo [2/3] Removing shortcuts...
if exist "%DESKTOP_LINK%" del /Q "%DESKTOP_LINK%"
if exist "%START_MENU_LINK%" del /Q "%START_MENU_LINK%"
if exist "%LEGACY_DESKTOP_LINK%" del /Q "%LEGACY_DESKTOP_LINK%"
if exist "%LEGACY_START_MENU_LINK%" del /Q "%LEGACY_START_MENU_LINK%"

echo [3/3] Removing installed files...
if exist "%INSTALL_DIR%" rmdir /S /Q "%INSTALL_DIR%"
if exist "%LEGACY_INSTALL_DIR%" rmdir /S /Q "%LEGACY_INSTALL_DIR%"

echo Uninstall complete.
exit /b 0
