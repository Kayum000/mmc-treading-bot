@echo off
setlocal
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.11+ first.
  pause
  exit /b 1
)
set /p "SECRET=Paste the QUOTEX_INGEST_SECRET from Render: "
if "%SECRET%"=="" (
  echo Secret is required.
  pause
  exit /b 1
)
set "MMC_BOT_URL=https://mmc-treading-bot.onrender.com"
set "QUOTEX_INGEST_SECRET=%SECRET%"
echo Starting MMC Quotex local collector...
py -3 tools\quotex_local_collector.py
pause
