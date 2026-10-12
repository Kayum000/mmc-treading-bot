@echo off
setlocal EnableExtensions
set "TASK=MMC Quotex Auto Collector"

echo Removing the old automatic startup task, if it exists...
schtasks /Delete /TN "%TASK%" /F >nul 2>&1

echo.
echo Automatic startup is disabled.
echo Use START_COLLECTOR.bat to start the local collector manually.
echo Use STOP_COLLECTOR.bat to stop it manually.
echo.
pause
