@echo off
echo ================================================
echo   Apollova Uninstaller
echo ================================================
echo.
echo This removes all Apollova Python packages.
echo Your templates, audio and job folders are NOT deleted.
echo.
echo Packages to remove: yt-dlp pydub librosa openai-whisper stable-ts lyricsgenius rapidfuzz colorthief Pillow requests python-dotenv torch torchaudio
echo.
set /p confirm="Continue? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo Cancelled.
    pause
    exit /b
)
echo.
set PY=py -3.11
%PY% --version >nul 2>&1
if errorlevel 1 set PY=python

echo Uninstalling...
%PY% -m pip uninstall -y yt-dlp pydub librosa openai-whisper stable-ts lyricsgenius rapidfuzz colorthief Pillow requests python-dotenv torch torchaudio
echo.
echo ================================================
echo   Done. You can now delete the Apollova folder.
echo ================================================
echo.
pause
