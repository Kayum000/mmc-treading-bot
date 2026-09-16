@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo This launcher is now compatibility-only.
echo Quotex Real Market + OTC ingestion runs inside the MMC Server process.
echo Starting the new one-click local server launcher...
echo.
call "%~dp0START_MMC_SERVER.bat"
