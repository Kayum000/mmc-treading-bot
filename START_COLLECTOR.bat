@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================
echo MMC QUOTEX COLLECTOR - MANUAL START
echo ================================================================
echo This starts only the local Quotex collector.
echo To stop it, run STOP_COLLECTOR.bat.
echo.

if not exist "tools\run_quotex_collector.bat" (
  echo ERROR: tools\run_quotex_collector.bat was not found.
  pause
  exit /b 1
)

call "tools\run_quotex_collector.bat"
