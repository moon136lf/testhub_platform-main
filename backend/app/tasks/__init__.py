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
# 显式 include：autodiscover 默认只找 <pkg>.tasks 模块，
# 而本项目的任务文件是 code_scan_tasks/ai_case_tasks 等，autodiscover 永远找不到（NotRegistered 根因）
celery_app.conf.update(include=[
    'app.tasks.code_scan_tasks',
    'app.tasks.ai_case_tasks',
    'app.tasks.script_tasks',
    'app.tasks.element_tasks',
])

# Worker 日志落 backend/logs/app-worker.log (与 API 的 app.log 分进程, 避免多进程轮转交错)
from celery.signals import worker_process_init, worker_ready
from app.core.logging_setup import setup_worker_logging


@worker_process_init.connect
def _init_worker_redis(**_kwargs):
    # Celery worker 不经过 FastAPI lifespan，redis_client.redis 恒为 None，
    # 任务里的 SSE send_message 会静默失败（'NoneType' has no attribute 'lpush'）
    import asyncio
    from app.core.redis import redis_client
    asyncio.run(redis_client.connect())


@worker_ready.connect
def _init_worker_logging(**_kwargs):
    setup_worker_logging()
