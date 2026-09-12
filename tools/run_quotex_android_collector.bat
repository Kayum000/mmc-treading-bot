@echo off
setlocal EnableExtensions
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
rem --- Find Python launcher ---
where py >nul 2>&1
if not errorlevel 1 goto python_ready
where python >nul 2>&1
if not errorlevel 1 goto python_command

echo Python is not installed. Trying to install Python 3.11 with winget...
where winget >nul 2>&1
if errorlevel 1 (
  echo Windows Package Manager (winget) is not available.
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
where py >nul 2>&1
if not errorlevel 1 goto python_ready
where python >nul 2>&1
if not errorlevel 1 goto python_command

echo Python was installed, but Windows has not refreshed PATH yet.
echo Close this window, open a new one, and run this file again.
pause
exit /b 1

:python_ready
set "PYTHON_CMD=py -3"
goto deps

:python_command
set "PYTHON_CMD=python"

:deps
rem --- Check/authorize Android device ---
"%ADB_EXE%" start-server >nul 2>&1
"%ADB_EXE%" get-state 2>nul | findstr /r /c:"device" >nul
if errorlevel 1 (
  echo.
  echo ================================================================
  echo Connect the Android phone by USB and enable USB debugging.
  echo If the phone asks to allow USB debugging, tap ALLOW.
  echo Then press any key here.
  echo ================================================================
  pause >nul
  "%ADB_EXE%" get-state 2>nul | findstr /r /c:"device" >nul
  if errorlevel 1 (
    echo No authorized Android device was detected.
    echo Keep the phone unlocked and approve the USB debugging prompt.
    pause
    exit /b 1
  )
)

set /p "SECRET=Paste the QUOTEX_INGEST_SECRET from Render (do not send it to ChatGPT): "
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

%PYTHON_CMD% -m pip install -r tools\requirements-android.txt
if errorlevel 1 (
  echo Failed to install local Python dependencies.
  pause
  exit /b 1
)

echo.
echo Starting MMC Quotex Android screen collector for %ASSET%...
echo Keep Quotex visible on the 1-minute OTC chart.
echo Press Ctrl+C to stop.
echo.
%PYTHON_CMD% tools\quotex_android_screen_collector.py
pause
