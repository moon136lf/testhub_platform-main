#!/bin/bash

echo "🚀 Starting MoonTest Backend Services..."

# Check if Redis is running
echo "Checking Redis connection..."
redis-cli ping > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Redis is not running. Please start Redis first."
    exit 1
fi
echo "✅ Redis is running"

# Check if PostgreSQL is running
echo "Checking PostgreSQL connection..."
pg_isready -h localhost -p 5432 > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ PostgreSQL is not running. Please start PostgreSQL first."
    exit 1
fi
echo "✅ PostgreSQL is running"

# Start Celery worker in background
echo "Starting Celery worker..."
celery -A app.tasks worker --loglevel=info --concurrency=4 &
CELERY_PID=$!
echo "✅ Celery worker started (PID: $CELERY_PID)"

# Start FastAPI server
echo "Starting FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Cleanup on exit
trap "kill $CELERY_PID" EXIT
