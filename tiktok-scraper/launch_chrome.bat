@echo off
echo Launching Chrome with remote debugging on port 9222...
echo.
echo Log into Aurora TikTok in the Chrome window that opens.
echo Leave it open, then run: python tiktok_scraper.py
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug-profile"
