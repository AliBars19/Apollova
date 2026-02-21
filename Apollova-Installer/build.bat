@echo off
REM Apollova - Build Script for Windows
REM Creates standalone .exe with bundled JSX scripts

echo ========================================
echo    Apollova Build Script
echo ========================================
echo.

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous builds
echo Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "*.spec" del /q "*.spec"

REM Build the executable with bundled JSX
echo.
echo Building Apollova.exe with bundled JSX scripts...
echo.

pyinstaller --onefile ^
    --windowed ^
    --name "Apollova" ^
    --icon "assets/icon.ico" ^
    --add-data "scripts;scripts" ^
    --add-data "scripts/JSX;scripts/JSX" ^
    --hidden-import "PIL" ^
    --hidden-import "PIL.Image" ^
    --hidden-import "colorthief" ^
    --hidden-import "rapidfuzz" ^
    --hidden-import "stable_whisper" ^
    --hidden-import "librosa" ^
    --hidden-import "pydub" ^
    --hidden-import "pytubefix" ^
    apollova_gui.py

if %errorlevel% neq 0 (
    echo.
    echo Build FAILED! Check errors above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo    Build Complete!
echo ========================================
echo.

REM Create distribution folder structure
echo Creating distribution package...

set DIST_DIR=dist\Apollova
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"

REM Move exe
move "dist\Apollova.exe" "%DIST_DIR%\" >nul

REM Create required directories
mkdir "%DIST_DIR%\templates" 2>nul
mkdir "%DIST_DIR%\Apollova-Aurora\jobs" 2>nul
mkdir "%DIST_DIR%\Apollova-Mono\jobs" 2>nul
mkdir "%DIST_DIR%\Apollova-Onyx\jobs" 2>nul
mkdir "%DIST_DIR%\database" 2>nul
mkdir "%DIST_DIR%\whisper_models" 2>nul

REM Copy assets if exists
if exist "assets" xcopy /s /q "assets" "%DIST_DIR%\assets\" >nul

REM Create README
(
echo Apollova - Lyric Video Generator
echo =================================
echo.
echo SETUP:
echo 1. Install FFmpeg and add to PATH
echo 2. Place your .aep templates in the templates/ folder:
echo    - Apollova-Aurora.aep
echo    - Apollova-Mono.aep  
echo    - Apollova-Onyx.aep
echo 3. Run Apollova.exe
echo.
echo FIRST RUN:
echo - After Effects path will be auto-detected
echo - If not found, go to Settings tab and browse manually
echo - Enter your Genius API token in Settings for lyrics
echo.
echo USAGE:
echo 1. Job Creation tab: Enter song details and generate jobs
echo 2. JSX Injection tab: Launch AE and inject data
echo 3. Review comps in AE and add to render queue
echo.
echo SUPPORT: apollova.co.uk
) > "%DIST_DIR%\README.txt"

echo.
echo Distribution package created: %DIST_DIR%\
echo.
echo IMPORTANT - Before distributing:
echo   1. Add your .aep template files to templates\ folder
echo   2. Optionally add FFmpeg binaries
echo   3. Test the complete workflow
echo.

pause
