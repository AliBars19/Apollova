@echo off
echo ================================================
echo   Apollova Uninstaller
echo ================================================
echo.
echo This removes all Apollova Python packages.
echo Your templates, audio and job folders are NOT deleted.
echo.
echo Packages to remove: pytubefix pydub librosa openai-whisper stable-ts lyricsgenius rapidfuzz colorthief Pillow requests python-dotenv torch torchaudio
echo.
set /p confirm="Continue? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo Cancelled.
    pause
    exit /b
)
echo.
echo Uninstalling...
"python" -m pip uninstall -y pytubefix pydub librosa openai-whisper stable-ts lyricsgenius rapidfuzz colorthief Pillow requests python-dotenv torch torchaudio
echo.
echo ================================================
echo   Done. You can now delete the Apollova folder.
echo ================================================
echo.
pause
