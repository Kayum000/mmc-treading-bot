@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

set "ADB_DIR=%~dp0platform-tools"
set "ADB_EXE=%ADB_DIR%\adb.exe"

rem --- Find or install ADB automatically ---
if exist "%ADB_EXE%" (
  set "PATH=%ADB_DIR%;%PATH%"
  goto adb_ready
)
where adb >nul 2>&1
if not errorlevel 1 (
  set "ADB_EXE=adb"
  goto adb_ready
)

echo Android Platform Tools are not installed locally.
echo Downloading the official Google Platform Tools package...
if not exist "%ADB_DIR%" mkdir "%ADB_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='https://dl.google.com/android/repository/platform-tools-latest-windows.zip'; $z=Join-Path $env:TEMP 'platform-tools-latest-windows.zip'; Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $z; Expand-Archive -Force $z -DestinationPath '%~dp0'; Remove-Item $z -Force"
if errorlevel 1 (
  echo Could not download Platform Tools automatically.
  echo Please install Google's Android SDK Platform Tools and run this file again.
  pause
  exit /b 1
)

if exist "%ADB_EXE%" (
  set "PATH=%ADB_DIR%;%PATH%"
  goto adb_ready
)

echo ADB was not found after the download.
pause
exit /b 1

:adb_ready
rem --- Find a real Python executable; avoid the Microsoft Store alias ---
set "PYTHON_EXE="
where py >nul 2>&1
if not errorlevel 1 (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PYTHON_KIND=PYLAUNCHER"
)

if not defined PYTHON_KIND if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_KIND if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_KIND if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PYTHON_KIND if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON_EXE=%ProgramFiles%\Python311\python.exe"
if not defined PYTHON_KIND if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON_EXE=%ProgramFiles%\Python312\python.exe"
if not defined PYTHON_KIND if exist "%ProgramFiles%\Python313\python.exe" set "PYTHON_EXE=%ProgramFiles%\Python313\python.exe"

if defined PYTHON_KIND goto python_ready
if defined PYTHON_EXE goto python_ready

echo A real Python installation was not found.
echo Trying to install Python 3.11 with Windows Package Manager...
where winget >nul 2>&1
if errorlevel 1 (
  echo Windows Package Manager ^(winget^) is not available.
  echo Please install Python 3.11+ once, then run this file again.
  pause
  exit /b 1
)
winget install --id Python.Python.3.11 --exact --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo Python installation failed.
  pause
  exit /b 1
)

if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON_EXE=%ProgramFiles%\Python311\python.exe"
if not defined PYTHON_EXE (
  echo Python was installed, but its executable was not found yet.
  echo Close this window, open a new one, and run this file again.
  pause
  exit /b 1
)

:python_ready
rem --- Start ADB and diagnose the USB connection ---
"%ADB_EXE%" kill-server >nul 2>&1
"%ADB_EXE%" start-server >nul 2>&1

:device_check
set "DEVICE_STATE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_EXE%" devices 2^>nul') do (
  if not "%%A"=="" set "DEVICE_STATE=%%B"
)

if /I "!DEVICE_STATE!"=="device" goto device_ready
if /I "!DEVICE_STATE!"=="unauthorized" goto unauthorized
if /I "!DEVICE_STATE!"=="offline" goto offline

echo.
echo ================================================================
echo Android phone is not visible to ADB yet.
echo.
echo On the phone:
echo   1. Keep the phone UNLOCKED.
echo   2. Keep USB debugging ON in Developer options.
echo   3. In USB Preferences choose ^"File transfer^" instead of ^"No data transfer^".
echo   4. Unplug/replug the USB cable. Use a DATA cable, not charge-only.
echo   5. If ^"Allow USB debugging?^" appears, tap ALLOW.
echo.
echo Current ADB devices:
"%ADB_EXE%" devices
 echo.
echo Press R to check again, or Q to quit.
choice /c RQ /n /m "Choice: "
if errorlevel 2 exit /b 1
"%ADB_EXE%" start-server >nul 2>&1
goto device_check

:unauthorized
echo.
echo The phone is connected but USB debugging is NOT authorized.
echo Look at the phone screen and tap ALLOW on ^"Allow USB debugging?^".
echo If no prompt appears: Developer options ^> Revoke USB debugging authorizations,
echo then unplug/replug the cable and tap ALLOW when prompted.
echo.
"%ADB_EXE%" devices
choice /c RQ /n /m "Press R to check again, or Q to quit: "
if errorlevel 2 exit /b 1
goto device_check

:offline
echo.
echo The phone is visible but ADB reports OFFLINE.
echo Keep it unlocked, set USB mode to File transfer, then unplug/replug the cable.
echo.
"%ADB_EXE%" devices
choice /c RQ /n /m "Press R to check again, or Q to quit: "
if errorlevel 2 exit /b 1
"%ADB_EXE%" kill-server >nul 2>&1
"%ADB_EXE%" start-server >nul 2>&1
goto device_check

:device_ready
echo.
echo Android device is connected and authorized.
"%ADB_EXE%" devices

set /p "SECRET=Paste the NEW QUOTEX_INGEST_SECRET from Render (do not send it to ChatGPT): "
if "%SECRET%"=="" (
  echo Secret is required.
  pause
  exit /b 1
)
set /p "ASSET=Quotex OTC asset [USDARS_otc]: "
if "%ASSET%"=="" set "ASSET=USDARS_otc"

set "MMC_BOT_URL=https://mmc-treading-bot.onrender.com"
set "QUOTEX_INGEST_SECRET=%SECRET%"
set "QUOTEX_ANDROID_ASSET=%ASSET%"
set "QUOTEX_SCREEN_FPS=2"

if defined PYTHON_KIND (
  py -3 -m pip install -r tools\requirements-android.txt
) else (
  "%PYTHON_EXE%" -m pip install -r tools\requirements-android.txt
)
if errorlevel 1 (
  echo Failed to install local Python dependencies.
  pause
  exit /b 1
)

echo.
echo Starting MMC Quotex Android screen collector for %ASSET%...
echo Keep Quotex visible on the 1-minute OTC chart.
echo No orders are automated. Press Ctrl+C to stop.
echo.
if defined PYTHON_KIND (
  py -3 tools\quotex_android_screen_collector.py
) else (
  "%PYTHON_EXE%" tools\quotex_android_screen_collector.py
)
pause
