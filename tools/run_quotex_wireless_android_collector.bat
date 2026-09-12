@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

set "ADB_DIR=%~dp0platform-tools"
set "ADB_EXE=%ADB_DIR%\adb.exe"
set "COLLECTOR_URL=https://raw.githubusercontent.com/Kayum000/mmc-treading-bot/main/tools/quotex_android_screen_collector.py"
set "COLLECTOR=%~dp0quotex_android_screen_collector.py"

if not exist "%ADB_EXE%" (
  where adb >nul 2>&1
  if not errorlevel 1 set "ADB_EXE=adb"
)
if not exist "%ADB_EXE%" if /I not "%ADB_EXE%"=="adb" (
  echo ADB is not installed. Run run_quotex_android_collector.bat once with USB,
  echo or install the official Android Platform Tools in tools\platform-tools.
  pause
  exit /b 1
)

set "PATH=%ADB_DIR%;%PATH%"

rem Refresh the same proven Android screen collector; only the transport changes.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='%COLLECTOR_URL%'; Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%COLLECTOR%'"
if errorlevel 1 (
  echo Could not download the latest Android collector.
  pause
  exit /b 1
)

"%ADB_EXE%" start-server >nul 2>&1

echo ================================================================
echo MMC Quotex Wireless Android Collector
 echo ================================================================
echo Phone and laptop must be on the same Wi-Fi network.
echo This uses ADB over Wi-Fi; it does not automate orders.
echo.
echo IMPORTANT: On the phone enable Developer options ^> Wireless debugging.
echo Android 11+: use ^"Pair device with pairing code^" the first time.
echo.

set /p "PAIR=Wireless pairing address (host:port), or leave blank if already paired: "
if not "%PAIR%"=="" (
  set /p "PAIRCODE=6-digit pairing code shown on the phone: "
  if "%PAIRCODE%"=="" (
    echo Pairing code is required.
    pause
    exit /b 1
  )
  echo Pairing with %PAIR%...
  "%ADB_EXE%" pair %PAIR% %PAIRCODE%
  if errorlevel 1 (
    echo Wireless pairing failed. Check the IP, pairing port and code on the phone.
    pause
    exit /b 1
  )
)

set /p "DEVICE=Wireless device address (host:port), e.g. 192.168.1.20:5555: "
if "%DEVICE%"=="" (
  echo Device address is required.
  pause
  exit /b 1
)

echo Connecting to %DEVICE%...
"%ADB_EXE%" connect %DEVICE%
if errorlevel 1 (
  echo ADB could not connect to the phone.
  pause
  exit /b 1
)

:check
set "FOUND="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_EXE%" devices 2^>nul') do (
  if /I "%%A"=="%DEVICE%" set "FOUND=%%B"
)
if /I not "%FOUND%"=="device" (
  echo.
  echo Phone is not authorized/online yet.
  "%ADB_EXE%" devices
  echo On the phone, approve any debugging prompt and keep Wireless debugging ON.
  choice /c RQ /n /m "Press R to retry, or Q to quit: "
  if errorlevel 2 exit /b 1
  "%ADB_EXE%" connect %DEVICE% >nul
  goto check
)

set /p "SECRET=Paste the QUOTEX_INGEST_SECRET from Render (do not send it to ChatGPT): "
if "%SECRET%"=="" (
  echo Secret is required.
  pause
  exit /b 1
)
set /p "ASSET=Quotex OTC asset [AUDUSD_otc]: "
if "%ASSET%"=="" set "ASSET=AUDUSD_otc"

set "MMC_BOT_URL=https://mmc-treading-bot.onrender.com"
set "QUOTEX_INGEST_SECRET=%SECRET%"
set "QUOTEX_ANDROID_ASSET=%ASSET%"
set "QUOTEX_SCREEN_FPS=2"

echo.
echo Installing/checking local collector packages...
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.11+ first.
  pause
  exit /b 1
)
py -3 -m pip install --upgrade opencv-python-headless numpy requests
if errorlevel 1 (
  echo Failed to install local Python dependencies.
  pause
  exit /b 1
)

echo.
echo Starting wireless Android collector for %ASSET%...
echo Keep Quotex visible on the 1-minute OTC chart.
echo Press Ctrl+C to stop.
echo.
py -3 "%COLLECTOR%"
pause
