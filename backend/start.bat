@echo off
echo Starting MoonTest Backend Services...

REM Start Celery worker in background
echo Starting Celery worker...
start "Celery Worker" cmd /k celery -A app.tasks worker --loglevel=info --concurrency=4 --pool=solo

REM Wait a moment for Celery to start
timeout /t 3 /nobreak

REM Start FastAPI server
echo Starting FastAPI server...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
