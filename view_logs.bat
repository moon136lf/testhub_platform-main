@echo off
title MoonTest Logs
echo ============================================
echo   MoonTest log viewer
echo   1 = API log   (backend\logs\app.log)
echo   2 = Worker log (backend\logs\app-worker.log)
echo   3 = both, live tail (two windows)
echo   4 = open both in notepad
echo ============================================
set /p choice=Select [1-4, Enter=default 3]:

if "%choice%"=="1" (
    powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app.log' -Tail 50 -Wait"
) else if "%choice%"=="2" (
    powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app-worker.log' -Tail 50 -Wait"
) else if "%choice%"=="4" (
    start notepad D:\MoonTest\backend\logs\app.log
    start notepad D:\MoonTest\backend\logs\app-worker.log
) else (
    start "MoonTest-API-Log" powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app.log' -Tail 30 -Wait"
    start "MoonTest-Worker-Log" powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app-worker.log' -Tail 30 -Wait"
)
