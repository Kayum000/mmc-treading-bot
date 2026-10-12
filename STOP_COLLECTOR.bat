@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================
echo MMC QUOTEX COLLECTOR - MANUAL STOP
echo ================================================================
echo Stopping only this repository's local Quotex collector...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root=(Resolve-Path '.').Path; $matches=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'quotex_local_collector\.py' -and $_.CommandLine -like ('*' + $root + '*') }; if ($matches) { $matches | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 500; $left=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'quotex_local_collector\.py' -and $_.CommandLine -like ('*' + $root + '*') }; if ($left) { Write-Output 'WARNING: Some matching processes remain.'; exit 1 } else { Write-Output 'Collector stopped.' } } else { Write-Output 'Collector is already off.' }"
if errorlevel 1 (
  echo.
  echo Could not verify that every collector process stopped.
  pause
  exit /b 1
)
echo.
pause
