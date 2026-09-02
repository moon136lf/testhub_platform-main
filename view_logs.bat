@echo off
chcp 65001 >nul
title MoonTest Logs
echo ============================================
echo   MoonTest log viewer
echo   1 = API 日志   (backend\logs\app.log)
echo   2 = Worker 日志 (backend\logs\app-worker.log)
echo   3 = 两者实时滚动 (PowerShell -Wait)
echo   4 = 用记事本打开两者
echo ============================================
set /p choice=选择 [1-4, 回车默认3]:

if "%choice%"=="1" (
    powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app.log' -Tail 50 -Wait"
) else if "%choice%"=="2" (
    powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app-worker.log' -Tail 50 -Wait"
) else if "%choice%"=="4" (
    start notepad D:\MoonTest\backend\logs\app.log
    start notepad D:\MoonTest\backend\logs\app-worker.log
) else (
    echo === API 日志 (左) ===
    start "MoonTest-API-Log" powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app.log' -Tail 30 -Wait"
    echo === Worker 日志 ===
    powershell -NoProfile -Command "Get-Content 'D:\MoonTest\backend\logs\app-worker.log' -Tail 30 -Wait"
)
