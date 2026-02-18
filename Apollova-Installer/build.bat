@echo off
REM Apollova GUI - Build Script for Windows
REM Creates a standalone .exe using PyInstaller

echo ========================================
echo    Apollova GUI - Build Script
echo ========================================
echo.

REM Check if PyInstaller is installed
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

REM Build the executable
echo.
echo Building Apollova.exe...
echo.

pyinstaller --onefile ^
    --windowed ^
    --name "Apollova" ^
    --icon "assets/icon.ico" ^
    --add-data "scripts;scripts" ^
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
    echo ❌ Build failed! Check the errors above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo    Build Complete!
echo ========================================
echo.
echo Output: dist\Apollova.exe
echo.

REM Create distribution folder
echo Creating distribution package...
if not exist "dist\Apollova" mkdir "dist\Apollova"
move "dist\Apollova.exe" "dist\Apollova\" >nul

REM Copy additional files
if exist "assets" xcopy /s /q "assets" "dist\Apollova\assets\" >nul
mkdir "dist\Apollova\database" 2>nul
mkdir "dist\Apollova\jobs" 2>nul
mkdir "dist\Apollova\whisper_models" 2>nul

REM Create .env template
echo GENIUS_API_TOKEN=your_token_here> "dist\Apollova\.env.example"
echo WHISPER_MODEL=small>> "dist\Apollova\.env.example"

REM Create README
echo Apollova - Lyric Video Job Generator> "dist\Apollova\README.txt"
echo.>> "dist\Apollova\README.txt"
echo SETUP:>> "dist\Apollova\README.txt"
echo 1. Install FFmpeg and add to PATH>> "dist\Apollova\README.txt"
echo 2. Rename .env.example to .env>> "dist\Apollova\README.txt"
echo 3. Add your Genius API token to .env>> "dist\Apollova\README.txt"
echo 4. Run Apollova.exe>> "dist\Apollova\README.txt"
echo.>> "dist\Apollova\README.txt"
echo USAGE:>> "dist\Apollova\README.txt"
echo 1. Enter song details and generate jobs>> "dist\Apollova\README.txt"
echo 2. Open After Effects template>> "dist\Apollova\README.txt"
echo 3. Run JSX automation script>> "dist\Apollova\README.txt"
echo 4. Select jobs folder>> "dist\Apollova\README.txt"
echo 5. Render!>> "dist\Apollova\README.txt"

echo.
echo Distribution package created: dist\Apollova\
echo.
echo Don't forget to:
echo   1. Add FFmpeg to the package (ffmpeg.exe, ffprobe.exe)
echo   2. Pre-download Whisper model (optional, for faster first run)
echo.

pause
