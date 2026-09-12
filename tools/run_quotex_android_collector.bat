@echo off
setlocal
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.11+ first.
  pause
  exit /b 1
)
where adb >nul 2>&1
if errorlevel 1 (
  echo adb was not found. Install Android SDK Platform Tools and add adb to PATH.
  pause
  exit /b 1
)
set /p "SECRET=Paste the QUOTEX_INGEST_SECRET from Render: "
if "%SECRET%"=="" (
  echo Secret is required.
  pause
  exit /b 1
)
set /p "ASSET=Quotex OTC asset [USDARS_otc]: "
if "%ASSET%"=="" set "ASSET=USDARS_otc"
set "MMC_BOT_URL=https://mmc-treading-bot.onrender.com"
set "QUOTEX_INGEST_SECRET=%SECRET%"
set "QUOTEX_ANDROID_ASSET=%ASSET%"
set "QUOTEX_SCREEN_FPS=2"
echo Starting MMC Quotex Android screen collector for %ASSET%...
py -3 -m pip install -r tools\requirements-android.txt
if errorlevel 1 (
  echo Failed to install local Python dependencies.
  pause
  exit /b 1
)
py -3 tools\quotex_android_screen_collector.py
pause
