@echo off
chcp 65001 >nul
echo ============================================
echo   MoonTest one-click stop
echo ============================================

echo [1/3] stop celery worker...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*celery*worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped PID=' + $_.ProcessId) }"

echo [2/3] stop uvicorn...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped PID=' + $_.ProcessId) }"

echo [3/3] stop vite frontend...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*vite*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped PID=' + $_.ProcessId) }"

echo ============================================
echo   app processes stopped.
echo   docker containers (redis/pgvector) keep running. full shutdown:
echo     docker stop moontest-redis moontest-pgvector
echo ============================================
pause
