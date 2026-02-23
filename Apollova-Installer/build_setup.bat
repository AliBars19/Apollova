@echo off
echo Building Apollova Setup.exe...
echo.

REM Check if PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

REM Clean up any previous build artifacts first
echo Cleaning previous build files...
rmdir /s /q build_temp 2>nul
del /q Setup.spec 2>nul
del /q Setup.exe 2>nul

REM Get absolute path to icon
set "SCRIPT_DIR=%~dp0"
set "ICON_PATH=%SCRIPT_DIR%assets\icon.ico"

REM Check if icon exists and build command accordingly
if exist "%ICON_PATH%" (
    echo Found icon: %ICON_PATH%
    echo Building Setup.exe with icon...
    python -m PyInstaller ^
        --onefile ^
        --windowed ^
        --name "Setup" ^
        --icon "%ICON_PATH%" ^
        --distpath "%SCRIPT_DIR%." ^
        --workpath "%SCRIPT_DIR%build_temp" ^
        --specpath "%SCRIPT_DIR%build_temp" ^
        --clean ^
        "%SCRIPT_DIR%setup.py"
) else (
    echo No icon found at %ICON_PATH%, building without icon...
    python -m PyInstaller ^
        --onefile ^
        --windowed ^
        --name "Setup" ^
        --distpath "%SCRIPT_DIR%." ^
        --workpath "%SCRIPT_DIR%build_temp" ^
        --specpath "%SCRIPT_DIR%build_temp" ^
        --clean ^
        "%SCRIPT_DIR%setup.py"
)

REM Cleanup
echo Cleaning up build files...
rmdir /s /q build_temp 2>nul

echo.
if exist "Setup.exe" (
    echo ========================================
    echo Setup.exe has been created successfully!
    echo ========================================
) else (
    echo ========================================
    echo ERROR: Setup.exe was not created
    echo Check the error messages above
    echo ========================================
)
echo.
pause