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
