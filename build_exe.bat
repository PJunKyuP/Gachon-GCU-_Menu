@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [1/3] Installing PyInstaller...
    python -m pip install --user pyinstaller
    if errorlevel 1 goto :fail
)

set "PYI_ADD_DATA="
if exist "logo.png" (
    set "PYI_ADD_DATA=%PYI_ADD_DATA% --add-data logo.png;."
)
if exist "logo.ico" (
    set "PYI_ADD_DATA=%PYI_ADD_DATA% --add-data logo.ico;."
)

set "PYI_ICON="
if exist "logo.ico" (
    set "PYI_ICON=--icon logo.ico"
)

echo [2/3] Building executable...
python -m PyInstaller --noconfirm --clean --onefile --windowed %PYI_ADD_DATA% %PYI_ICON% --name "GachonMealWidget" "gachon_meal_widget.py"
if errorlevel 1 goto :fail

echo [3/3] Done: dist\GachonMealWidget.exe
start "" "%SCRIPT_DIR%dist"
echo Pin dist\GachonMealWidget.exe to taskbar if needed.
exit /b 0

:fail
echo Build failed. Check terminal logs.
exit /b 1
