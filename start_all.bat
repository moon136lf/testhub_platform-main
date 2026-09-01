@echo off
chcp 65001 >nul
echo ============================================
echo   MoonTest one-click start
echo ============================================

REM 1. docker containers (redis + postgres)
echo [1/5] check docker containers...
docker ps --format "{{.Names}}" | findstr /C:"moontest-redis" >nul 2>&1
if errorlevel 1 (
    echo   moontest-redis not running, starting...
    docker start moontest-redis 2>nul || docker run -d --name moontest-redis --restart unless-stopped -p 6379:6379 redis:7
) else (
    echo   moontest-redis OK
)
docker ps --format "{{.Names}}" | findstr /C:"moontest-pgvector" >nul 2>&1
if errorlevel 1 (
    echo   moontest-pgvector not running, starting...
    docker start moontest-pgvector
) else (
    echo   moontest-pgvector OK
)

REM 2. kill stale celery processes (avoid double-worker task stealing)
echo [2/5] kill stale celery processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*celery*worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped stale PID=' + $_.ProcessId) }"

REM 3. backend api
echo [3/5] start backend api (port 8000)...
start "MoonTest-API" cmd /k "cd /d D:\MoonTest\backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

REM 4. celery worker
echo [4/5] start celery worker...
start "MoonTest-Worker" cmd /k "cd /d D:\MoonTest\backend && celery -A app.tasks.celery_app worker --pool=solo -l info --concurrency=1"

REM 5. frontend
echo [5/5] start frontend (port 3000)...
start "MoonTest-Frontend" cmd /k "cd /d D:\MoonTest\frontend && npm run dev"

echo ============================================
echo   all services started!
echo   - frontend: http://localhost:3000
echo   - backend:  http://localhost:8000/docs
echo   stop = close windows (or run stop_all.bat)
echo ============================================
pause
