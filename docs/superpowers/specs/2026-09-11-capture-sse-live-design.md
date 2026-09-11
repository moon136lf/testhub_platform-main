# 会话式抓取 SSE 直播 设计文档

日期：2026-09-11 ｜ 状态：用户已确认设计，待出实施计划

## 背景与需求

会话式抓取工作台「开始抓取元素」是同步端点，大页面扫描期间无任何反馈（像卡死）。用户要求：**完整对齐一次性抓取的直播体验**（消息流 + 进度条 + 完成时返回本批元素数），并加**扫描元素实时计数**（按选择器轮播报）。

用户已确认的 2 个决策：
1. **实现方式：进程内 SSE**（不套 Celery）——会话抓取跑在 backend 进程内（browser_mgr 持有 page），Celery worker 是另一进程拿不到 page。端点内直接 `SSEStream(sid).send_message(...)` 写 Redis List，复用既有 `/api/sse/element-fetch/{sid}` 订阅通道与前端 EventSource 渲染模式。
2. **计数粒度：按选择器轮播报**——`scan_interactive_elements` 加可选 `on_progress` 回调，每轮（button/input/a[href]/span/p/div…）扫描完回调一次「已扫描 X 类，累计发现 N 个」；回调不传则零影响（一次性抓取链路不动）。

## 设计

### 1. 后端：扫描器进度回调

`playwright_locator_core.py` `scan_interactive_elements(page, include_text, include_div_text, on_progress=None)`：
- `on_progress: Optional[Callable[[str, int], Awaitable[None]]]`——参数 `(selector, running_total)`；`scan_selectors` 与 `scan_div_text_selectors` 的 selector 循环末尾（每轮 try/except 之后、下一轮之前）：`if on_progress: await on_progress(selector, len(elements))`
- 回调内异常吞掉（不中断扫描）；缺省 None 时行为与现状完全一致（既有 800 测试不动）

### 2. 后端：capture 端点发 SSE

`POST /capture/browser/{sid}/capture`（elements.py:760）：
- 端点开头创建 `sse = SSEStream(sid)`（复用 `app.core.sse.SSEStream`，redis key `sse:{sid}`，sid 本就是 bs_xxx 唯一）
- 抓取流程埋点（全部 fire-and-forget 语义：send_message 内部已 try/except 不抛）：
  - 开始：`type=system, stage=scan, content="正在扫描页面元素...", progress=0.05`
  - on_progress 回调：`content=f"已扫描 {selector}，累计发现 {n} 个元素", progress=0.1~0.7 线性映射（按轮序号/总轮数估算）`
  - 过滤完成：`content=f"过滤后保留 {len(elements)} 个元素", progress=0.8`
  - 截图上传后：`content="正在写入暂存列表...", progress=0.9`
  - 完成前：`type=success, stage=done, content=f"抓取完成：本批 {len(elements)} 个元素", progress=1.0, data={"total_count": len(elements), "batch_idx": ..., "batch_count": ..., "staging_session_id": ...}`——data 与端点同步响应体一致
  - 异常路径：现有 try/except 里补 `type=error` 消息（抓取失败时直播可见）
- 端点保持同步响应体不变（前端兼容）

### 3. SSE 订阅端点

无需新建——复用既有 `GET /api/sse/element-fetch/{session_id}`（sse.py:69，`stream_events(session_id)` 读同一 redis key `sse:{session_id}`）。sid 直接当 session_id 用。

注意既有 stream_messages 语义：读到 progress>=1.0 自动断流；60 次 timeout（约 5 分钟）自动断。会话抓取单批次几十秒内完成，匹配。

### 4. 前端：CaptureWorkbench 直播面板

- `captureNow` 改造：发 POST 前先 `sseConnection = new EventSource('/api/sse/element-fetch/' + browserSessionId)`（与 element.js 的 createSSEConnection 一致，EventSource 不走 axios baseURL）；抓取完成后关闭连接
- 消息渲染：加 `liveMessages` ref + 左栏卡片下方（或 shot-header 下）直播面板，样式对齐 ElementLibrary 的 `.live-feed/.live-message`（时间 + 内容，error 红色）；每次抓取前清空
- 完成处理：POST 响应仍为权威数据源（现有 `r.staging_session_id`/`r.total_count` 逻辑不变）；SSE 只做展示。SSE 完成消息（type=success）不触发数据更新，仅展示
- 失败处理：POST catch 现有逻辑不变；SSE error 消息额外展示在面板

### 5. 不做项

- Celery 任务化（会话 page 在 backend 进程，worker 拿不到——架构上不可行，已确认）
- 逐元素计数（刷屏，按轮播报已覆盖诉求）
- 一次性抓取链路的回调接入（已有自己的 SSE 编排，不动）

## 测试

后端 TDD（pytest）：
1. `scan_interactive_elements` on_progress：传回调时每轮被调用且参数为 (selector, 累计数)；不传时无调用；回调抛异常不中断扫描
2. capture 端点：mock SSEStream，断言发了开始/success(progress=1.0) 消息且 data 与响应体一致；扫描异常路径发 error 消息
3. 回归：现有 800 测试全绿（on_progress 缺省零影响）

前端：`npm run build` + 真浏览器验收（直播面板滚动、计数更新、完成后自动收尾）

## 验收点

| 需求 | 实现 |
|---|---|
| 直播消息流 | 工作台左栏直播面板，对齐一次性抓取样式 |
| 进度 | 每阶段 progress 推进，完成 1.0 |
| 实时计数 | 每选择器轮报「已扫描 X，累计发现 N 个」 |
| 完成通知 | success 消息 + 本批元素数，面板收尾 |
