@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "PYTHONPATH=%CD%;%PYTHONPATH%"
set "BOT_URL=https://mmc-treading-bot.onrender.com"
set "SECRET_FILE=%~dp0.quotex_test_secret"
set "COLLECTOR=%~dp0quotex_local_collector.py"
set "COLLECTOR_URL=https://raw.githubusercontent.com/Kayum000/mmc-treading-bot/main/tools/quotex_local_collector.py"
set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
set "PROFILE=%LocalAppData%\MMC-Quotex-Chrome"

if not exist "%SECRET_FILE%" (
  echo Missing %SECRET_FILE%
  echo Put the Render QUOTEX_INGEST_SECRET in this file once, then rerun.
  pause
  exit /b 1
)
if not exist "%CHROME_EXE%" (
  echo Google Chrome was not found.
  pause
  exit /b 1
)

where py >nul 2>&1 || (echo Python launcher py was not found.&pause&exit /b 1)

if exist "%COLLECTOR%" del /q "%COLLECTOR%" >nul 2>&1
where curl >nul 2>&1
if not errorlevel 1 (
  curl -L --fail --silent --show-error "%COLLECTOR_URL%" -o "%COLLECTOR%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='%COLLECTOR_URL%'; Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%COLLECTOR%'"
)
if errorlevel 1 (echo Could not download the current collector.&pause&exit /b 1)

set /p "SECRET="<"%SECRET_FILE%"
if "%SECRET%"=="" (echo Secret file is empty.&pause&exit /b 1)
set "MMC_BOT_URL=%BOT_URL%"
set "QUOTEX_INGEST_SECRET=%SECRET%"
set "CHROME_CDP_URL=http://127.0.0.1:9222"

py -3 -m pip install --disable-pip-version-check requests websockets >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Starting isolated Quotex Chrome...
  start "MMC Quotex Chrome" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" "https://market-qx.info/en/demo-trade"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i -lt 30;$i++){try{Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 1|Out-Null;exit 0}catch{Start-Sleep -Seconds 1}};exit 1"
  if errorlevel 1 (echo Chrome CDP did not start.&pause&exit /b 1)
)

echo ================================================================
echo MMC Quotex AUTO mode is running.
echo Keep this window open. Collector self-reconnects and self-recovers.
echo The MMC OTC selector can auto-use the detected Quotex OTC pair.
echo ================================================================
echo.
:LOOP
py -3 "%COLLECTOR%"
echo Collector stopped; restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto LOOP
