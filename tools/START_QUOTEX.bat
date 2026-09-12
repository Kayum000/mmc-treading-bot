@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo MMC Quotex data-source selector
echo ================================================================
echo 1. Laptop - Quotex Windows App
 echo 2. Android phone - Wireless ADB
 echo 3. Android phone - USB ADB
 echo Q. Quit
 echo.
choice /c 123Q /n /m "Select a mode: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto usb
if errorlevel 2 goto wireless
if errorlevel 1 goto laptop

:laptop
call "%~dp0run_quotex_windows_app_collector.bat"
exit /b %errorlevel%

:wireless
call "%~dp0run_quotex_wireless_android_collector.bat"
exit /b %errorlevel%

:usb
call "%~dp0run_quotex_android_collector.bat"
exit /b %errorlevel%
