@echo off
echo ========================================
echo   Apollova - Build All Executables
echo   Setup.exe + Apollova.exe + Uninstall.exe
echo ========================================
echo.

set PY=py -3.11

%PY% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 not found.
    echo Install from: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    pause
    exit /b 1
)

echo Found:
%PY% --version
echo.

%PY% -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo Installing PyQt6...
    %PY% -m pip install PyQt6
)

%PY% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    %PY% -m pip install pyinstaller
)

set "SCRIPT_DIR=%~dp0"
set "ICON_PATH=%SCRIPT_DIR%assets\icon.ico"
if not exist "%ICON_PATH%" set "ICON_PATH=%SCRIPT_DIR%icon.ico"
set "VERSION_FILE=%SCRIPT_DIR%version_info.txt"

echo Verifying source files...
if not exist "%SCRIPT_DIR%setup.py"            ( echo ERROR: setup.py not found in %SCRIPT_DIR% & pause & exit /b 1 )
if not exist "%SCRIPT_DIR%apollova_launcher.py" ( echo ERROR: apollova_launcher.py not found & pause & exit /b 1 )
if not exist "%SCRIPT_DIR%uninstall_gui.py"     ( echo ERROR: uninstall_gui.py not found & pause & exit /b 1 )
echo All source files present.
echo.

echo Cleaning previous builds...
rmdir /s /q build_temp 2>nul
del /q "%SCRIPT_DIR%Setup.exe" "%SCRIPT_DIR%Apollova.exe" "%SCRIPT_DIR%Uninstall.exe" 2>nul
echo.

REM Helper macro - build one exe
REM Usage: call :build_exe <script> <name>

call :build_exe "%SCRIPT_DIR%setup.py" "Setup"
if not exist "%SCRIPT_DIR%Setup.exe" ( echo FAILED: Setup.exe & pause & exit /b 1 )

call :build_exe "%SCRIPT_DIR%apollova_launcher.py" "Apollova"
if not exist "%SCRIPT_DIR%Apollova.exe" ( echo FAILED: Apollova.exe & pause & exit /b 1 )

call :build_exe "%SCRIPT_DIR%uninstall_gui.py" "Uninstall"
if not exist "%SCRIPT_DIR%Uninstall.exe" ( echo FAILED: Uninstall.exe & pause & exit /b 1 )

rmdir /s /q build_temp 2>nul

echo.
echo ========================================
echo   All 3 executables built successfully!
echo.
echo   Setup.exe      - First-time installer
echo   Apollova.exe   - Launch the main app
echo   Uninstall.exe  - Remove Apollova
echo ========================================
echo.
exit /b 0


:build_exe
echo [Building %~2.exe from %~1]
set "VER_FLAG="
if exist "%VERSION_FILE%" set "VER_FLAG=--version-file "%VERSION_FILE%""
if exist "%ICON_PATH%" (
    %PY% -m PyInstaller --onefile --windowed --name "%~2" --icon "%ICON_PATH%" %VER_FLAG% --collect-all PyQt6 --distpath "%SCRIPT_DIR%." --workpath "%SCRIPT_DIR%build_temp" --specpath "%SCRIPT_DIR%build_temp" --clean "%~1"
) else (
    %PY% -m PyInstaller --onefile --windowed --name "%~2" %VER_FLAG% --collect-all PyQt6 --distpath "%SCRIPT_DIR%." --workpath "%SCRIPT_DIR%build_temp" --specpath "%SCRIPT_DIR%build_temp" --clean "%~1"
)
echo %~2.exe done.
echo.
exit /b 0
