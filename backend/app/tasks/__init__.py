"""
Celery configuration and app instance
"""

from celery import Celery
from app.core.config import settings

# Create Celery app
celery_app = Celery(
    "moontest",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max
    task_soft_time_limit=540,  # 9 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(['app.tasks'])
