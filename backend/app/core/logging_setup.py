"""统一日志配置 v2: 统一格式 + requestId(contextvars) 注入 + 可选 GELF(Graylog). 幂等."""
import json
import logging
import os
import socket
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler

from app.core.config import settings

_request_id: ContextVar = ContextVar("request_id", default="-")

LOG_FILE = "app.log"
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


def set_request_id(rid: str) -> None:
    _request_id.set(rid or "-")


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """把 contextvars 的 requestId 注入每条 LogRecord (record.request_id)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class UnifiedFormatter(logging.Formatter):
    """datefmt 不含 %f 时 Python 不会自动补毫秒, 用 formatTime 强制 ',SSS' 后缀.

    控制台输出时 ERROR/CRITICAL 整行染红（ANSI），文件输出不加色。
    """

    def formatTime(self, record: logging.LogRecord, datefmt=None) -> str:
        import time as _time
        # datefmt 参数由 __init__ 存到 self._fmt 之外, 这里直接用实例保存的 datefmt
        s = _time.strftime(getattr(self, "_moontest_datefmt", "%Y%m%d %H:%M:%S"),
                           self.converter(record.created))
        return "%s,%03d" % (s, record.msecs)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        # 染色仅在控制台 handler 生效（_moontest_color 标记）：
        # ERROR/CRITICAL 整行红，WARNING 整行黄
        if getattr(self, "_moontest_color", False):
            if record.levelno >= logging.ERROR:
                return f"[91m{line}[0m"
            if record.levelno >= logging.WARNING:
                return f"[33m{line}[0m"
        return line


def build_formatter(color: bool = False) -> logging.Formatter:
    """统一格式: yyyyMMdd HH:mm:ss,SSS | LEVEL | logger:lineno | requestId=xx | msg

    color=True 时 ERROR 及以上级别整行 ANSI 红色（仅控制台 handler 用）。
    """
    fmt = UnifiedFormatter(
        "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | requestId=%(request_id)s | %(message)s",
        datefmt="%Y%m%d %H:%M:%S",
    )
    fmt._moontest_datefmt = "%Y%m%d %H:%M:%S"
    fmt._moontest_color = color
    return fmt


class GelfUdpHandler(logging.Handler):
    """自写 GELF UDP handler (graypy 已停维护, 零依赖替代). GELF 1.1: JSON UTF-8 单包 <8192B."""

    def __init__(self, host: str, port: int = 12201):
        super().__init__()
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "version": "1.1",
                "host": socket.gethostname(),
                "short_message": self.format(record),
                "timestamp": record.created,
                "level": min(record.levelno // 10, 6),
                "facility": record.name,
                "line": record.lineno,
                "_request_id": getattr(record, "request_id", "-"),
            }
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")[:8192]
            self._sock.sendto(data, self._addr)
        except Exception:
            self.handleError(record)


def setup_logging(log_dir: str = "logs",
                  level_console: str | None = None,
                  level_file: int = logging.INFO,
                  log_file: str = LOG_FILE) -> None:
    """配置根 logger 双输出 + requestId filter. 幂等 (重复调用先清旧 handler/filter).

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

    for f in list(root.filters):
        root.removeFilter(f)

    os.makedirs(log_dir, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(log_dir, log_file),
                             maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                             encoding="utf-8")
    fh.setLevel(level_file)
    fh.setFormatter(build_formatter(color=False))
    # requestId filter 挂在 HANDLER 上（不是 root logger）：
    # logger filter 只对直接调用该 logger 的记录生效，子 logger propagate
    # 的记录不过 root filter —— 挂 handler 上则所有传播记录都会被注入
    fh.addFilter(RequestIdFilter())
    root.addHandler(fh)

    # Windows 控制台强制 UTF-8, 避免中文日志乱码/UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if level_console is None:
        level_console = "INFO" if settings.DEBUG else "WARNING"
    sh = logging.StreamHandler()
    sh.setLevel(level_console)
    sh.setFormatter(build_formatter(color=True))
    sh.addFilter(RequestIdFilter())
    root.addHandler(sh)

    root.setLevel(min(fh.level, sh.level))

    # 可选: Graylog GELF UDP (settings.GRAYLOG_HOST 非空才挂)
    if getattr(settings, "GRAYLOG_HOST", ""):
        try:
            gh = GelfUdpHandler(settings.GRAYLOG_HOST, settings.GRAYLOG_PORT)
            gh.setLevel(logging.WARNING)
            gh.setFormatter(build_formatter(color=False))
            gh.addFilter(RequestIdFilter())
            root.addHandler(gh)
        except Exception:
            pass  # Graylog 不可达不影响本地


def setup_worker_logging() -> None:
    """Celery worker 进程日志: 单独文件 app-worker.log (多进程写同一文件有轮转交错风险)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    setup_logging(log_dir=os.path.join(base_dir, "logs"), log_file="app-worker.log")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
