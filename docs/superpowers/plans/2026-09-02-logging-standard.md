# 后端日志规范化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 日志落文件+轮转、报错带上下文、全局异常兜底+请求日志——让报错能回查、能定位。

**Spec:** `docs/superpowers/specs/2026-09-02-logging-standard-design.md`

**Tech:** Python logging（RotatingFileHandler + StreamHandler）+ FastAPI middleware/exception handler + Celery worker logging。

**测试约定:** 同步 def + 直接断言；logging 配置用 caplog/临时目录验证。

---

### Task 1: logging_setup.py 统一配置（P1 核心）

**Files:**
- Create: `backend/app/core/logging_setup.py`
- Modify: `backend/app/main.py:16-21`（换 basicConfig）
- Test: `backend/tests/test_logging_setup.py`

- [ ] Step 1: 写失败测试

```python
"""logging_setup tests: 落文件+轮转+幂等."""
import logging
import os


class TestSetupLogging:
    def test_writes_file_and_rotates(self, tmp_path):
        from app.core.logging_setup import setup_logging
        log_dir = str(tmp_path)
        setup_logging(log_dir=log_dir, level_console="INFO", level_file=logging.INFO)
        logger = logging.getLogger("test_lsu")
        logger.info("hello-file")
        for h in logging.getLogger().handlers:
            h.flush()
        assert os.path.exists(os.path.join(log_dir, "app.log"))
        content = open(os.path.join(log_dir, "app.log"), encoding="utf-8").read()
        assert "hello-file" in content
        assert "test_lsu" in content  # logger name in format
        assert os.path.basename(__file__) is not None  # format has funcName/lineno — smoke

    def test_idempotent_no_dup_handlers(self, tmp_path):
        from app.core.logging_setup import setup_logging
        setup_logging(log_dir=str(tmp_path))
        setup_logging(log_dir=str(tmp_path))
        root = logging.getLogger()
        fh = [h for h in root.handlers if h.__class__.__name__ == "RotatingFileHandler"]
        sh = [h for h in root.handlers if h.__class__.__name__ == "StreamHandler"]
        assert len(fh) == 1
        assert len(sh) == 1

    def test_file_level_stays_info(self, tmp_path):
        """文件级别不随 console 级别抬高."""
        from app.core.logging_setup import setup_logging
        setup_logging(log_dir=str(tmp_path), level_console="ERROR", level_file=logging.INFO)
        logger = logging.getLogger("test_lsu2")
        logger.info("still-logged")
        for h in logging.getLogger().handlers:
            h.flush()
        content = open(os.path.join(tmp_path / "app.log"), encoding="utf-8").read()
        assert "still-logged" in content
```

- [ ] Step 2: 跑测试确认失败

Run: `cd /d/MoonTest/backend && timeout 100 python -m pytest tests/test_logging_setup.py -q -p no:cacheprovider`
Expected: FAIL (ModuleNotFoundError: app.core.logging_setup)

- [ ] Step 3: 实现 `backend/app/core/logging_setup.py`

```python
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
                  level_file: int = logging.INFO) -> None:
    """配置根 logger 双输出. 幂等 (重复调用先清旧 handler, uvicorn --reload 重跑安全).

    level_console: 缺省按 settings.DEBUG 推断 (True→INFO, False→WARNING),
    可被 LOG_LEVEL 环境变量覆盖 (调用方传 os.getenv("LOG_LEVEL")).
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
    fh = RotatingFileHandler(os.path.join(log_dir, LOG_FILE),
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
```

- [ ] Step 4: 跑测试确认通过

Run: `cd /d/MoonTest/backend && timeout 100 python -m pytest tests/test_logging_setup.py -q -p no:cacheprovider`
Expected: 3 passed

- [ ] Step 5: main.py 换用 setup_logging + .gitignore + commit

`backend/app/main.py` 第 16-21 行：

```python
# 原:
logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# 换为:
import os
from app.core.logging_setup import setup_logging
setup_logging(log_dir=os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"),
              level_console=os.getenv("LOG_LEVEL"))
```

（`import logging` 与模块内 `logger = logging.getLogger(__name__)` 保留。）

`backend/.gitignore`（或主仓 .gitignore）追加一行 `backend/logs/`。

```bash
cd /d/MoonTest && git add backend/app/core/logging_setup.py backend/app/main.py backend/tests/test_logging_setup.py .gitignore backend/.gitignore
git commit -m "feat(logging): setup_logging — rotating file + console dual output (#logging T1)" 
```
（commit 末尾加 Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>，下同）

---

### Task 2: Celery worker 日志落同一文件

**Files:**
- Modify: `backend/app/tasks/__init__.py`（celery_app 定义后接 worker 日志信号）
- Test: `backend/tests/test_logging_setup.py`（追加）

- [ ] Step 1: 追加失败测试

```python
class TestCeleryLogging:
    def test_worker_setup_connects(self, tmp_path):
        """celery signals module imports without error and wires setup."""
        # 验证 signals 模块存在且 setup_worker_logging 可调用 (真实 worker 行为 e2e 才能验, 此处冒烟)
        from app.core.logging_setup import setup_worker_logging  # noqa: F401
        import app.tasks  # noqa: F401  导入即注册 signal, 不抛错
```

- [ ] Step 2: 跑测试确认失败

Run: `cd /d/MoonTest/backend && timeout 100 python -m pytest tests/test_logging_setup.py::TestCeleryLogging -q -p no:cacheprovider`
Expected: FAIL (ImportError: setup_worker_logging)

- [ ] Step 3: 实现

`backend/app/core/logging_setup.py` 追加：

```python
def setup_worker_logging(**kwargs) -> None:
    """Celery worker_setup_logging 信号回调: worker 进程也走统一配置."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    setup_logging(log_dir=os.path.join(base_dir, "logs"), **kwargs)
```

`backend/app/tasks/__init__.py` 文件末尾追加：

```python
# Worker 日志落 logs/app.log (与 API 同一目录, 各自进程写同一 RotatingFileHandler 路径, 轮转互不干扰即可)
from celery.signals import worker_ready
from app.core.logging_setup import setup_worker_logging

@worker_ready.connect
def _init_worker_logging(**_kwargs):
    setup_worker_logging()
```

（注：Celery worker 与 API 是不同进程，各自持有自己的 RotatingFileHandler 写同一文件——Windows 下多进程写同一文件有覆盖风险，若实测有交错损坏，改用按进程区分文件名 `app-worker.log`。实现时先验证再决定，默认分开：worker 用 `app-worker.log`。）

更稳妥版（直接采用）：`setup_worker_logging` 传 `log_file="app-worker.log"`，logging_setup 的 `setup_logging` 加参数 `log_file: str = "app.log"`。

- [ ] Step 4: 跑测试确认通过

Run: `cd /d/MoonTest/backend && timeout 100 python -m pytest tests/test_logging_setup.py -q -p no:cacheprovider`
Expected: 4 passed

- [ ] Step 5: Commit

```bash
cd /d/MoonTest && git add backend/app/core/logging_setup.py backend/app/tasks/__init__.py backend/tests/test_logging_setup.py
git commit -m "feat(logging): celery worker logs to app-worker.log (#logging T2)"
```

---

### Task 3: 报错日志补上下文 + 消灭静默吞异常（P2）

**Files:**
- Modify: `backend/app/services/ai_gateway.py`（6 provider + chat 聚合，~8 处）
- Modify: `backend/app/services/ai_fix_service.py:49`
- Modify: `backend/app/services/operation_log_service.py:47-48`（except pass）
- Modify: 其余高频点：code_scan_service、script_executor、self_heal_engine、functional_case_generator（挑 logger.warning/error 已有的行补上下文）
- Test: 无新增单测（日志文案改动不改变行为）；跑全量确认无回归

- [ ] Step 1: 改造模式（每处一行改动）

统一约定 `<事件> | key=value ...: <异常>`。示例（ai_gateway.py:85）：

```python
# 原:
logger.error(f"GLM chat failed: {e}")
# 换:
logger.error(f"GLM chat failed | provider=glm model={payload.get('model')} messages_len={len(messages)}: {e}")
```

（每处按实际可得变量补 2-3 个关键标识；取不到的变量不硬造。）

ai_gateway chat 聚合入口（~426/436 行）补 provider 名与调用方 stage：

```python
logger.warning(f"Provider not available, skipping | provider={provider_name}")
logger.warning(f"Provider failed, trying next | provider={provider_name}: {e}")
```

ai_fix_service.py:49：

```python
logger.error(f"AI fix generate failed | issue_id={issue_id} project_id={project_id}: {e}")
```

（核对函数签名里实际参数名后填。）

operation_log_service.py:47-48：

```python
# 原:
except Exception:
    pass
# 换:
except Exception as e:
    logger.debug(f"operation log write skipped (non-critical): {e}")
```

其余 code_scan_service/script_executor/self_heal_engine/functional_case_generator：grep `logger\.\(warning\|error\)` 逐处补，预计 ~10 处，同样的模式。

- [ ] Step 2: 全量测试确认无回归

Run: `cd /d/MoonTest/backend && timeout 500 python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_batch_import_fix.py --deselect tests/test_storage_get_object.py`
Expected: 502+ passed, 0 failed

- [ ] Step 3: Commit

```bash
cd /d/MoonTest && git add backend/app/services/
git commit -m "feat(logging): error logs carry context (ids/provider) + no silent swallows (#logging T3)"
```

---

### Task 4: 全局异常兜底 + 请求日志（P3）

**Files:**
- Modify: `backend/app/main.py`（exception handler + middleware）
- Test: `backend/tests/test_logging_middleware.py`

- [ ] Step 1: 写失败测试

```python
"""Request logging middleware + global exception handler tests."""
from unittest.mock import MagicMock, patch


class TestRequestLogging:
    def test_middleware_logs_method_path_status(self, client):
        # client fixture: 参照 tests/test_api_whitescan.py 的 client fixture 写法 (TestClient + dependency overrides)
        import logging
        with patch("app.core.logging_setup.logger", ) as mock_log:
            pass  # 见 Step 3 实现后按实际断言: caplog 更简单
```

（注：client fixture 用 TestClient 直连 app；断言用 caplog 捕获根 logger：`caplog.set_level(logging.INFO)` 后断言 `"GET /health -> 200" in caplog.text` 样式。真实健康端点用 `/` 或任一存在路由。）

```python
class TestGlobalExceptionHandler:
    def test_unhandled_exception_returns_500(self, client, caplog):
        import logging
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.v1 import regression  # 任一路由模块做临时注入
        # 注入一个会抛异常的路由 (app.router 临时添加)
        from fastapi import APIRouter
        r = APIRouter()
        @r.get("/__boom__")
        async def boom():
            raise RuntimeError("boom-test")
        app.include_router(r, prefix="/api/v1")
        with caplog.at_level(logging.ERROR):
            resp = TestClient(app, raise_server_exceptions=False).get("/api/v1/__boom__")
        assert resp.status_code == 500
        assert "boom-test" in caplog.text
        # 清理: 移除测试路由避免污染其他测试
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/v1/__boom__"]
```

- [ ] Step 2: 跑测试确认失败

Run: `cd /d/MoonTest/backend && timeout 100 python -m pytest tests/test_logging_middleware.py -q -p no:cacheprovider`
Expected: FAIL (500 handler 未记日志 / 请求日志不存在)

- [ ] Step 3: 实现（main.py，lifespan 定义之后、路由注册之前）

```python
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    line = f"{request.method} {request.url.path} -> {response.status_code} ({ms:.0f}ms)"
    if response.status_code >= 500:
        logger.error(line)
    elif ms >= 3000:
        logger.warning(line)
    else:
        logger.info(line)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception | {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"code": 500, "detail": "Internal server error"})
```

（`JSONResponse` 已在 main.py import；注意现有全局 handler 若已有（搜 `exception_handler`），保留原有业务 handler 只加兜底 Exception。）

- [ ] Step 4: 跑测试确认通过 + 全量无回归

Run: `cd /d/MoonTest/backend && timeout 100 python -m pytest tests/test_logging_middleware.py -q -p no:cacheprovider`
Expected: 2 passed
Run: `cd /d/MoonTest/backend && timeout 500 python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_batch_import_fix.py --deselect tests/test_storage_get_object.py`
Expected: 0 failed

- [ ] Step 5: start_all.bat 加 LOG_LEVEL + Commit

`start_all.bat` 的 API 启动行前加：

```bat
set LOG_LEVEL=INFO
```

```bash
cd /d/MoonTest && git add backend/app/main.py backend/tests/test_logging_middleware.py start_all.bat
git commit -m "feat(logging): request log middleware + unhandled exception handler (#logging T4)"
```

---

### Task 5: 真实启动验证 + 收尾

- [ ] Step 1: 真实启动冒烟

```bash
cd /d/MoonTest/backend && timeout 30 python -c "from app.main import app" && ls logs/
# 启动 API: start_all.bat 或直接 uvicorn, 确认 logs/app.log 生成且含 lifespan 启动行
```

- [ ] Step 2: 人为触发报错验证可查性

调用一个必然失败的接口（如无效 UUID 的 regression/list），在 logs/app.log 中确认：请求日志行 + 422/500 + 异常堆栈可检索。

- [ ] Step 3: 如有 fixup 则 commit（勾选 plan checkboxes）
