"""统一日志配置: RotatingFileHandler + StreamHandler 双输出. 幂等."""
import logging
import os
from logging.handlers import RotatingFileHandler

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
LOG_FILE = "app.log"
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


def setup_logging(log_dir: str = "logs",
                  level_console: str | None = None,
                  level_file: int = logging.INFO,
                  log_file: str = LOG_FILE) -> None:
    """配置根 logger 双输出. 幂等 (重复调用先清旧 handler, uvicorn --reload 重跑安全).

    level_console: 缺省按 settings.DEBUG 推断 (True→INFO, False→WARNING),
    可被 LOG_LEVEL 环境变量覆盖 (调用方传 os.getenv("LOG_LEVEL")).
    log_file: 文件名 (worker 用 app-worker.log 区分进程).
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    fmt = logging.Formatter(LOG_FORMAT)

    os.makedirs(log_dir, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(log_dir, log_file),
                             maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                             encoding="utf-8")
    fh.setLevel(level_file)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if level_console is None:
        level_console = "INFO" if settings.DEBUG else "WARNING"
    sh = logging.StreamHandler()
    sh.setLevel(level_console)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    root.setLevel(min(fh.level, sh.level))


def setup_worker_logging() -> None:
    """Celery worker 进程日志: 单独文件 app-worker.log (多进程写同一文件有轮转交错风险)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    setup_logging(log_dir=os.path.join(base_dir, "logs"), log_file="app-worker.log")
