@echo off
title MoonTest Stop
echo ============================================
echo   MoonTest one-click stop
echo ============================================

echo [1/4] stop celery worker...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*celery*worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped PID=' + $_.ProcessId) }"

echo [2/4] stop uvicorn main...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped PID=' + $_.ProcessId) }"

echo [3/4] kill orphan reload children + port-8000 listeners...
REM uvicorn --reload 的 spawn 子进程命令行不含 uvicorn，主进程被杀后变孤儿仍占 8000
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*spawn_main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('  stopped orphan PID=' + $_.ProcessId) }"
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -Unique OwningProcess | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('  stopped port-8000 PID=' + $_.OwningProcess) }"

echo [4/4] stop vite frontend...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*vite*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped PID=' + $_.ProcessId) }"

echo ============================================
echo   app processes stopped.
echo   docker containers (redis/pgvector) keep running. full shutdown:
echo     docker stop moontest-redis moontest-pgvector
echo ============================================
pause
