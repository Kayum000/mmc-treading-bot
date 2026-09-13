@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

rem Use the local collector file. Do NOT overwrite it from GitHub at startup.
set "COLLECTOR_FILE=%~dp0quotex_windows_app_screen_collector.py"

rem Find a real Python installation; avoid the Microsoft Store alias.
set "PYTHON_EXE="
set "PYTHON_KIND="
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
set /p "SECRET=Paste the NEW QUOTEX_INGEST_SECRET from Render (do not send it to ChatGPT): "
if "%SECRET%"=="" (
  echo Secret is required.
  pause
  exit /b 1
)

set "MMC_BOT_URL=https://mmc-treading-bot.onrender.com"
set "QUOTEX_INGEST_SECRET=%SECRET%"
set "QUOTEX_WINDOWS_FPS=2"

rem Install only the packages used by the Windows screen collector.
echo.
echo Installing local Python packages for the Windows App collector...
if defined PYTHON_KIND (
  py -3 -m pip install --upgrade pip
  py -3 -m pip install --upgrade -r "%~dp0requirements-windows-app.txt"
) else (
  "%PYTHON_EXE%" -m pip install --upgrade pip
  "%PYTHON_EXE%" -m pip install --upgrade -r "%~dp0requirements-windows-app.txt"
)
if errorlevel 1 (
  echo Failed to install local Python dependencies.
  pause
  exit /b 1
)

echo.
echo Starting MMC Quotex Windows App screen collector...
echo Keep the Quotex App open on the 1-minute OTC chart.
echo The OTC market will be detected automatically from the open chart.
echo No market name input is required. No orders are automated.
echo Press Ctrl+C to stop.
echo.
if defined PYTHON_KIND (
  py -3 "%COLLECTOR_FILE%"
) else (
  "%PYTHON_EXE%" "%COLLECTOR_FILE%"
)
pause
