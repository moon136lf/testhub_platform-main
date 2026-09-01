@echo off
chcp 65001 >nul
echo ============================================
echo   MoonTest 一键停止
echo ============================================

echo [1/3] 停止 Celery Worker 进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*celery*worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  已停止 PID=' + $_.ProcessId) }"

echo [2/3] 停止 uvicorn 进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  已停止 PID=' + $_.ProcessId) }"

echo [3/3] 停止 vite 前端进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*vite*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  已停止 PID=' + $_.ProcessId) }"

echo ============================================
echo   应用进程已全部停止.
echo   Docker 容器 (redis/pgvector) 保持运行 — 完全停机再运行:
echo     docker stop moontest-redis moontest-pgvector
echo ============================================
pause
