# 后端日志规范化设计

> 创建：2026-09-02
> 背景：报错难以回查——日志只进 uvicorn 控制台窗口、配置粒度粗（DEBUG 开关决定 INFO/WARNING）、报错缺上下文、个别静默吞异常、无请求串联。
> 用户确认：按 P1（含 Celery 落文件）→ P2 → P3 顺序实现。P4（request_id 贯穿）明确不做。

---

## 1. 目标与边界

### 1.1 做

1. **P1 落文件 + 轮转**：日志同时写 `backend/logs/app.log` 与控制台，RotatingFileHandler（10MB × 5 备份）；文件日志始终 INFO 不随 DEBUG 降级；Celery worker 日志同落文件
2. **P2 报错带上下文**：~20 处高频失败点日志补 `key=value` 上下文（issue_id/project_id/provider 等）；消灭 `except: pass`
3. **P3 兜底 + 请求日志**：全局 exception handler 记完整堆栈；请求中间件记 `method path → status (耗时)`

### 1.2 不做

- request_id 中间件贯穿各层（P4）
- 结构化 JSON 日志 / 日志采集系统对接
- 前端日志

## 2. 组件设计

### 2.1 新建 `backend/app/core/logging_setup.py`

```python
def setup_logging(log_dir="logs", level_console=None, level_file=logging.INFO):
    """统一配置: RotatingFileHandler + StreamHandler 双输出, 幂等可重复调用."""
```

- 格式：`%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d | %(message)s`
- 文件：`logs/app.log`，RotatingFileHandler(maxBytes=10MB, backupCount=5)，UTF-8 编码
- 控制台级别默认取 settings.DEBUG ? INFO : WARNING（保持现行为）；文件恒 INFO
- 幂等：重复调用先清理已有 handler（uvicorn --reload 会重跑）
- main.py 的 lifespan/启动处调用；Celery worker 启动处（`app/tasks/` 或 celery_app 定义处）复用同一函数落同一目录

### 2.2 main.py 改动

- 删除现有 `logging.basicConfig`，改调 `setup_logging()`

### 2.3 P2 日志上下文（约定）

- 格式约定：`<事件描述> | key=value key=value: <异常>`，例如：
  `AI fix generate failed | issue_id=xxx project_id=yyy provider=glm: timeout`
- 改造范围（高频失败点，日志语句已存在的）：ai_gateway 6 个 provider chat/embedding、chat 聚合入口、ai_fix_service、code_scan_service、script_executor、self_heal_engine、functional_case_generator、regression_service 等 ~20 处
- `except Exception: pass` → 至少 `logger.debug(f"... failed: {e}")`（operation_log_service.py:47 等）

### 2.4 P3 main.py 增补

- 全局 handler：`@app.exception_handler(Exception)` → `logger.exception` + 返回 500 JSON
- 请求中间件：`logger.info(f"{method} {path} -> {status} ({ms}ms)")`；≥3s 用 WARNING、5xx 用 ERROR

## 3. 其他

- `backend/logs/` 加 `.gitignore`
- start_all.bat：加 `set LOG_LEVEL=INFO`（预留覆盖口子，控制台级别读取 `LOG_LEVEL` 优先于 DEBUG 推断）
- 不改业务逻辑；现有测试不应受影响，全量跑一次验证
- 验收：启动后 `backend/logs/app.log` 存在且双输出；人为触发一个报错（如无效 project_id）能在文件中查到带上下文+堆栈的记录；请求日志逐行可见
