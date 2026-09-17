@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "MMC_LOCAL_SERVER=1"
set "MMC_BOT_URL=http://127.0.0.1:5000"
set "CHROME_CDP_URL=http://127.0.0.1:9222"
set "QUOTEX_DEBUG_VERBOSE=0"
set "SECRET_FILE=%~dp0.quotex_test_secret"
set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
set "PROFILE=%LocalAppData%\MMC-Quotex-Chrome"

if not exist "%SECRET_FILE%" (
  echo Missing local Quotex secret file: %SECRET_FILE%
  pause
  exit /b 1
)
if not exist "%CHROME_EXE%" (
  echo Google Chrome was not found.
  pause
  exit /b 1
)
where py >nul 2>&1 || (echo Python launcher py was not found.&pause&exit /b 1)
set /p "QUOTEX_INGEST_SECRET="<"%SECRET_FILE%"
if "%QUOTEX_INGEST_SECRET%"=="" (echo Secret file is empty.&pause&exit /b 1)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Starting isolated Quotex Chrome...
  start "MMC Quotex Chrome" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" "https://market-qx.info/en/demo-trade"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i-lt30;$i++){try{Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 1|Out-Null;exit 0}catch{Start-Sleep -Seconds 1}};exit 1"
  if errorlevel 1 (echo Chrome CDP did not start.&pause&exit /b 1)
)

echo Starting MMC Server on http://127.0.0.1:5000 ...
echo Quotex Real Market + OTC collector will run inside this same Python server process.
py -3 main.py
pause
