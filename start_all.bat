@echo off
chcp 65001 >nul
echo ============================================
echo   MoonTest 一键启动
echo ============================================

REM 1. 确认 Docker 容器 (Redis + PostgreSQL) 活着, 没起就拉起
echo [1/5] 检查 Docker 容器...
docker ps --format "{{.Names}}" | findstr /C:"moontest-redis" >nul 2>&1
if errorlevel 1 (
    echo   moontest-redis 未运行, 启动中...
    docker start moontest-redis 2>nul || docker run -d --name moontest-redis --restart unless-stopped -p 6379:6379 redis:7
) else (
    echo   moontest-redis OK
)
docker ps --format "{{.Names}}" | findstr /C:"moontest-pgvector" >nul 2>&1
if errorlevel 1 (
    echo   moontest-pgvector 未运行, 启动中...
    docker start moontest-pgvector
) else (
    echo   moontest-pgvector OK
)

REM 2. 清理残留的 Celery 进程 (避免双 worker 抢任务)
echo [2/5] 清理残留 Celery 进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*celery*worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  已停止残留进程 PID=' + $_.ProcessId) }"

REM 3. 拉起后端 API
echo [3/5] 启动后端 API (端口 8000)...
start "MoonTest-API" cmd /k "cd /d D:\MoonTest\backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

REM 4. 拉起 Celery Worker
echo [4/5] 启动 Celery Worker...
start "MoonTest-Worker" cmd /k "cd /d D:\MoonTest\backend && celery -A app.tasks.celery_app worker --pool=solo -l info --concurrency=1"

REM 5. 拉起前端
echo [5/5] 启动前端 (端口 3000)...
start "MoonTest-Frontend" cmd /k "cd /d D:\MoonTest\frontend && npm run dev"

echo ============================================
echo   全部服务已拉起!
echo   - 前端:   http://localhost:3000
echo   - 后端:   http://localhost:8000/docs
echo   停止服务 = 关闭对应窗口 (或运行 stop_all.bat)
echo ============================================
pause
