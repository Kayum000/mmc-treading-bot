@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "STARTER=%~dp0start_mmc_quotex_auto.bat"
if not exist "%STARTER%" (
  echo Auto launcher not found.
  pause
  exit /b 1
)
set "TASK=MMC Quotex Auto Collector"

schtasks /Create /TN "%TASK%" /SC ONLOGON /TR "\"%STARTER%\"" /RL LIMITED /F
if errorlevel 1 (
  echo Could not create the Windows startup task.
  echo Run this file as Administrator if Windows requests it.
  pause
  exit /b 1
)

echo.
echo Installed: %TASK%
echo It will start automatically when you sign in to Windows.
echo The first run will open the isolated Chrome profile.
echo Log in to Quotex once and keep that profile available.
echo.
pause
