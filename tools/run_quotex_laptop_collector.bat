@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "COLLECTOR_URL=https://raw.githubusercontent.com/Kayum000/mmc-treading-bot/main/tools/quotex_local_collector.py"
set "COLLECTOR=%~dp0quotex_local_collector.py"

echo ================================================================
echo MMC Quotex Laptop Collector
echo ================================================================
echo This mode uses a Quotex browser tab on THIS laptop.
echo No phone, ADB, password/SSID collection, or order automation.
echo.

where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.11+ first.
  pause
  exit /b 1
)

where curl >nul 2>&1
if not errorlevel 1 (
  curl -L --fail --silent --show-error "%COLLECTOR_URL%" -o "%COLLECTOR%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='%COLLECTOR_URL%'; Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%COLLECTOR%'"
)
if errorlevel 1 (
  echo Could not sync the latest laptop collector from GitHub.
  pause
  exit /b 1
)

set /p "SECRET=Paste the QUOTEX_INGEST_SECRET from Render (do not send it to ChatGPT): "
if "%SECRET%"=="" (
  echo Secret is required.
  pause
  exit /b 1
)

set "MMC_BOT_URL=https://mmc-treading-bot.onrender.com"
set "QUOTEX_INGEST_SECRET=%SECRET%"
set "CHROME_CDP_URL=http://127.0.0.1:9222"

py -3 -m pip install --upgrade requests websockets
if errorlevel 1 (
  echo Failed to install the laptop collector dependencies.
  pause
  exit /b 1
)

echo.
echo Checking Chrome DevTools on port 9222...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Chrome CDP is not running.
  echo.
  echo First run:
  echo   tools\start_quotex_debug_chrome.bat
  echo Then log in and open the 1-minute OTC chart in that Chrome window.
  echo Finally run this file again.
  pause
  exit /b 1
)

echo.
echo Starting laptop-only OTC data collector...
echo Keep the isolated Chrome window open on the 1-minute OTC chart.
echo Press Ctrl+C to stop.
echo.
py -3 "%COLLECTOR%"
pause
