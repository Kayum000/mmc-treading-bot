@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================
echo MMC Quotex Android Collector - updater/launcher
echo ================================================================
echo.

if not exist "tools" mkdir "tools"

where git >nul 2>&1
if not errorlevel 1 if exist ".git" (
  echo Updating the local bot from GitHub...
  git pull --ff-only
  if errorlevel 1 echo Git update was not available; continuing with the official GitHub files.
)

set "RAW=https://raw.githubusercontent.com/Kayum000/mmc-treading-bot/main/tools"
echo Syncing collector files from GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $base='%RAW%'; $dest=Join-Path (Get-Location) 'tools'; foreach($f in @('run_quotex_android_collector.bat','quotex_android_screen_collector.py','requirements-android.txt')) { Invoke-WebRequest -UseBasicParsing -Uri ($base+'/'+$f) -OutFile (Join-Path $dest $f) }"
if errorlevel 1 (
  echo.
  echo Could not download the latest collector files.
  echo Check your internet connection and try again.
  pause
  exit /b 1
)

echo.
echo Latest Android collector files are ready.
echo Starting the collector...
echo.
call "tools\run_quotex_android_collector.bat"
exit /b %errorlevel%
