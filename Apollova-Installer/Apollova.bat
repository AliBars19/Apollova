@echo off
cd /d "%~dp0"
"python" "assets\apollova_gui.py"
if errorlevel 1 (
    echo.
    echo Apollova encountered an error.
    echo Check that all packages are installed and try again.
    pause >nul
)
