"""
Pytest configuration and fixtures
"""

import os
import sys
from unittest.mock import MagicMock, Mock

# 将 backend 目录加入 sys.path，确保 `import app.xxx` 可用
# （app/__init__.py 使 app 成为命名空间包，pytest 收集时需显式路径）
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# 测试日志分流: pytest 运行时把根 logger 的文件输出指到 logs/test.log,
# 与真实流量日志 (app.log/app-worker.log) 隔离, 避免测试 ERROR 淹没真实报错。
# 控制台 handler 保留 (pytest -s 仍可见)。
import logging
from logging.handlers import RotatingFileHandler

def _pytest_log_redirect() -> None:
    root = logging.getLogger()
    test_log = os.path.join(BACKEND_DIR, "logs", "test.log")
    os.makedirs(os.path.dirname(test_log), exist_ok=True)
    # 移除既有 RotatingFileHandler (setup_logging 在 import app.main 时挂的 app.log handler)
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler) and "test.log" not in getattr(h, "baseFilename", ""):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    fh = RotatingFileHandler(test_log, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"))
    root.addHandler(fh)

_pytest_log_redirect()
