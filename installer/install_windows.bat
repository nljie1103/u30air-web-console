@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" %*
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo Installation did not complete. Review the device list and error above.
echo.
pause
exit /b %RESULT%
