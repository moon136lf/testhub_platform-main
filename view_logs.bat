@echo off
chcp 65001 >nul
title MoonTest Logs
echo ============================================
echo   MoonTest log viewer
echo   1 = API log   (backend\logs\app.log)
echo   2 = Worker log (backend\logs\app-worker.log)
echo   3 = both, live tail (two windows)
echo   4 = open both in notepad
echo ============================================
set /p choice=Select [1-4, Enter=default 3]:

REM 日志文件为 UTF-8: PowerShell 输出必须先 [Console]::OutputEncoding 设为 UTF8,
REM 否则控制台按 GBK 解读 UTF-8 字节 → 中文乱码。

if "%choice%"=="1" (
    powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Content 'D:\MoonTest\backend\logs\app.log' -Tail 50 -Wait -Encoding UTF8"
) else if "%choice%"=="2" (
    powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Content 'D:\MoonTest\backend\logs\app-worker.log' -Tail 50 -Wait -Encoding UTF8"
) else if "%choice%"=="4" (
    start notepad D:\MoonTest\backend\logs\app.log
    start notepad D:\MoonTest\backend\logs\app-worker.log
) else (
    start "MoonTest-API-Log" powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Content 'D:\MoonTest\backend\logs\app.log' -Tail 30 -Wait -Encoding UTF8"
    start "MoonTest-Worker-Log" powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Content 'D:\MoonTest\backend\logs\app-worker.log' -Tail 30 -Wait -Encoding UTF8"
)
