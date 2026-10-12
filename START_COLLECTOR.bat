@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================
echo MMC QUOTEX COLLECTOR - MANUAL START
echo ================================================================
echo This starts only the local Quotex collector.
echo To stop it, run STOP_COLLECTOR.bat.
echo.

if exist "%~dp0tools\run_quotex_collector.bat" (
  call "%~dp0tools\run_quotex_collector.bat"
) else (
  echo ERROR: tools\run_quotex_collector.bat was not found.
  pause
  exit /b 1
)
