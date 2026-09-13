@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "tools\run_quotex_laptop_collector.bat" (
  echo ERROR: tools\run_quotex_laptop_collector.bat was not found.
  echo Please make sure this file is in the repository root.
  pause
  exit /b 1
)

call "tools\run_quotex_laptop_collector.bat"
exit /b %errorlevel%
