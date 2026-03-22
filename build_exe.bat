@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if exist "black_logo.png" (
    if not exist "assets\images" mkdir "assets\images"
    copy /Y "black_logo.png" "assets\images\black_logo.png" >nul
    python -c "from PIL import Image; Image.open(r'assets/images/black_logo.png').save(r'assets/images/black_logo.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
    if errorlevel 1 goto :fail
    copy /Y "assets\images\black_logo.png" "assets\images\logo.png" >nul
    copy /Y "assets\images\black_logo.ico" "assets\images\logo.ico" >nul
)

set "LOGO_PNG=assets\images\black_logo.png"
set "LOGO_ICO=assets\images\black_logo.ico"

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [1/3] Installing PyInstaller...
    python -m pip install --user pyinstaller
    if errorlevel 1 goto :fail
)

set "PYI_ADD_DATA="
if exist "%LOGO_PNG%" (
    set "PYI_ADD_DATA=%PYI_ADD_DATA% --add-data %LOGO_PNG%;assets/images"
)
if exist "%LOGO_ICO%" (
    set "PYI_ADD_DATA=%PYI_ADD_DATA% --add-data %LOGO_ICO%;assets/images"
)

set "PYI_ICON="
if exist "%LOGO_ICO%" (
    set "PYI_ICON=--icon %LOGO_ICO%"
)

echo [2/3] Building executable (without UPX)...
python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --collect-all customtkinter %PYI_ADD_DATA% %PYI_ICON% --name "GachonMenu" "gachon_meal_widget.py"
if errorlevel 1 goto :fail

echo [3/3] Done: dist\GachonMenu.exe
start "" "%SCRIPT_DIR%dist"
echo Pin dist\GachonMenu.exe to taskbar if needed.
exit /b 0

:fail
echo Build failed. Check terminal logs.
exit /b 1
