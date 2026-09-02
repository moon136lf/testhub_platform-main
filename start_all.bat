@echo off
chcp 65001 >nul
echo ============================================
echo   MoonTest one-click start
echo ============================================

REM 1. docker containers (redis + postgres)
echo [1/6] check docker containers...
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
echo [2/6] kill stale celery processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*celery*worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped stale PID=' + $_.ProcessId) }"
REM uvicorn --reload worker 子进程(spawn_main)不含 uvicorn 字样, 按端口兜底清理残留 API (防孤儿抢 8000)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -Unique OwningProcess | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('  stopped stale port-8000 PID=' + $_.OwningProcess) }"

REM 3. backend api
echo [3/6] start backend api (port 8000)...
set LOG_LEVEL=INFO
start "MoonTest-API" cmd /k "cd /d D:\MoonTest\backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

REM 4. celery worker
echo [4/6] start celery worker...
start "MoonTest-Worker" cmd /k "cd /d D:\MoonTest\backend && celery -A app.tasks.celery_app worker --pool=solo -l info --concurrency=1"

REM 5. wait for backend ready (poll /health every 2s, max 30s)
echo [5/6] waiting for backend ready...
set /a TRIES=0
:wait_backend
timeout /t 2 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost:8000/api/v1/health/ 2>nul | findstr "200" >nul 2>&1
if not errorlevel 1 (
    echo   backend ready.
    goto backend_ok
)
set /a TRIES+=1
if %TRIES% lss 15 (
    echo   waiting... (%TRIES%/15)
    goto wait_backend
)
echo   WARNING: backend not ready after 30s, starting frontend anyway.
:backend_ok

REM 6. frontend (after backend ready - no ECONNREFUSED on first load)
echo [6/6] start frontend (port 3000)...
start "MoonTest-Frontend" cmd /k "cd /d D:\MoonTest\frontend && npm run dev"

echo ============================================
echo   all services started!
echo   - frontend: http://localhost:3000
echo   - backend:  http://localhost:8000/docs
echo   stop = close windows (or run stop_all.bat)
echo ============================================
pause
