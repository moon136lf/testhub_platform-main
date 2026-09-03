# MoonTest 日志指南（LOGGING.md）

> 面向测试/运维人员：不用懂代码，看懂日志、按 requestId 排查问题。

## 1. 日志文件

| 文件 | 内容 | 进程 |
|---|---|---|
| `backend/logs/app.log` | API 服务全部日志 | uvicorn (端口 8000) |
| `backend/logs/app-worker.log` | 异步任务日志（AI生成/元素抓取/白盒扫描/转脚本） | celery worker |

轮转：单文件 10MB × 5 个备份，UTF-8。`view_logs.bat` 可快速查看。

## 2. 统一格式

```
yyyyMMdd HH:mm:ss,SSS | LEVEL | 模块:行号 | requestId=xxx | 消息
20260903 10:15:32,456 | INFO    | app.services.element_service:fetch:88 | requestId=abc123 | 【元素库】抓取完成 | 元素=53 耗时=2664ms
```

- **requestId**：一次 HTTP 请求的唯一编号。同一次请求产生的所有日志（访问行 + 内部动作 + 错误）requestId 相同——排查时 grep 它即可看全链路。
- 上游系统传 `X-Request-Id` 头则沿用（跨系统链路串联），无则自动生成；响应头也会回写 `X-Request-Id`。
- Celery worker 任务没有 HTTP 请求上下文，requestId 显示 `-`，此时按日志里的 `session=`/`scan=`/`case=` 串联。

## 3. 中文动作日志（测试人员主要看这个）

关键节点格式：**【模块名】动作 | key=value ...**

- `INFO` = 开始/成功：`【AI用例生成】识别完成 | session=xxx 测试点=88 token≈26400`
- `ERROR` = 失败，必带 **原因=** 和 **建议=**：
  `【AI用例生成】AI识别失败 | session=xxx 原因=ReadTimeout 建议=检查AI网关配置与模型可用性`
- `WARNING` = 降级/非致命（继续执行）：`【脚本执行】定位器回写失败(非致命) | ...`

模块清单：元素库 / AI用例生成 / 用例转脚本 / 脚本执行 / 自愈引擎 / 回归测试 / 白盒扫描 / 知识库 / 报告推送 / SSE / 系统。

## 4. 访问行

```
HTTP POST /api/v1/ai-case-generation/upload-document -> 200, requestId=..., costMs=409, client=127.0.0.1, body={"project_id":"7d6..."}
```

- 每个非 SSE 请求一行；`body` 为 JSON 请求体摘要（≤2KB，超长标 `<2KB截断>`）
- 敏感字段自动打码：password / secret / token / api_key / passwd / authorization → `***`
- 级别：`>=500` ERROR、`>=3s` WARNING、其余 INFO
- SSE 流端点（`/api/sse/*`）不记访问行（"完成"在流关闭时），由【SSE】连接建立/关闭两行代替

## 5. 级别约定

| 级别 | 含义 |
|---|---|
| INFO | 关键节点（开始/成功/访问行） |
| WARNING | 降级、重试、非致命失败（流程继续） |
| ERROR | 失败（带 原因=/建议=，全局异常带堆栈） |

## 6. 环境变量（backend/.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LOG_LEVEL` | INFO（DEBUG=true 时） | 根日志级别 |
| `SQLALCHEMY_LEVEL` | **WARNING** | SQLAlchemy SQL 日志级别（默认关闭 SQL 刷屏；调 DEBUG 可看全部 SQL） |
| `GRAYLOG_HOST` | 空 | 配置后日志同步推送 Graylog（GELF UDP，WARNING 以上） |
| `GRAYLOG_PORT` | 12201 | GELF input 端口 |

## 7. Graylog 字段映射

自写 GELF UDP handler（零依赖），消息为 GELF 1.1 JSON：

| GELF 字段 | 来源 | Graylog 检索 |
|---|---|---|
| `short_message` | 格式化后的日志行 | 全文搜索 |
| `_request_id` | contextvars | `request_id:abc123` 精确过滤 |
| `facility` | logger 名 | 按模块过滤 |
| `level` | syslog 0-6 | 级别过滤 |

未配置 GRAYLOG_HOST 时完全不影响本地日志。

## 8. 三场景示例（改造前 → 改造后）

**① 接口访问（上传文档）**

改造前：
```
INFO: 127.0.0.1:58525 - "POST /api/v1/ai-case-generation/upload-document HTTP/1.1" 422
（外加几千行 SQL SELECT/COMMIT 刷屏）
```
改造后：
```
20260903 10:20:01,123 | INFO | app.main:log_requests:105 | requestId=a1b2c3d4-... | HTTP POST /api/v1/ai-case-generation/upload-document -> 200, requestId=a1b2c3d4-..., costMs=409, client=127.0.0.1, body={"project_id":"7d6..."}
```

**② SSE 连接**

改造前：
```
INFO | app.api.v1.sse | SSE connection established: c321ddda-...
```
改造后：
```
20260903 10:20:02,456 | INFO | app.api.v1.sse:stream_events:42 | requestId=a1b2c3d4-... | 【SSE】连接建立 | session=c321ddda-...
```
（与访问行 requestId 一致，一个请求一条链）

**③ 失败排查（AI 识别失败）**

改造前：
```
ERROR | app.tasks.ai_case_tasks | Test point identification failed: ReadTimeout
（无上下文，不知道哪一步、该查什么）
```
改造后：
```
20260903 10:26:02,336 | INFO | requestId=... | 【AI用例生成】开始识别测试点 | session=1fd0cb31 文档=21435字
20260903 10:27:03,219 | ERROR | requestId=... | 【AI用例生成】AI识别失败 | session=1fd0cb31 原因=ReadTimeout 建议=检查AI网关配置与模型可用性
20260903 10:27:03,220 | ERROR | requestId=... | 【AI用例生成】识别任务失败 | session=1fd0cb31 原因=ReadTimeout 建议=查看上方AI识别失败日志
```

## 9. 常见排查套路

1. 拿到问题时间点 → 在 app.log 找该时刻的**访问行**，记下 requestId
2. `grep requestId=<值> app.log app-worker.log` → 该请求全链路
3. 找 `ERROR` 行 → 看 **原因=**（什么坏了）和 **建议=**（先检查什么）
4. worker 日志（任务类问题）按 `session=` 串联
