@echo off
setlocal
set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" (
  echo Google Chrome was not found.
  pause
  exit /b 1
)
set "PROFILE=%LocalAppData%\MMC-Quotex-Chrome"
echo Starting an isolated Chrome profile with DevTools on 127.0.0.1:9222...
start "MMC Quotex Chrome" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" "https://qxbroker.com/"
echo.
echo 1. Log in to Quotex in this Chrome window.
echo 2. Open the OTC chart you want to monitor.
echo 3. Leave this Chrome window open.
echo 4. Then run tools\run_quotex_collector.bat
pause
