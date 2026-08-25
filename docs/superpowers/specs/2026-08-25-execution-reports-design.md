# 执行记录与报告（#6）设计 — 报告中心 + 导出

**版本**：v1.0
**日期**：2026-08-25
**作者**：Claude Code (Opus 4.8)
**状态**：待审批（等 #5a 完成后实施）
**流程**：Superpowers（brainstorming → writing-plans → TDD → 编码 → verification）
**范围依据**：需求 §5.2 执行记录与报告 + §8.2.7 execution_record + #5a 已建 ExecutionDetail

---

## 1. 概述

#6「执行记录与报告」——把 #5a 产生的执行记录归拢整合，提供**报告中心**：执行记录列表（整合入口）+ 报告详情页（整合视图：统计+失败明细+截图+最简趋势）+ 导出 HTML/PDF。不做分享链接、不做自动化率指标、不做推送/冷存储（留 P1）。

### 1.1 依赖（#5a 已落地）

#6 **不新建表**，只读消费 #5a 两张表（master c30b103+ 已建）：
- `execution_record`（§8.2.7 记录级）：exec_id/project_id/exec_type/status/total_cases/passed_count/fail_count/pass_rate/duration_ms/tokens_used/env_info/report_url/started_at/finished_at
- `execution_detail`（#5a 明细级）：execution_record_id/script_id/case_id/step/action/status/error_type/error_msg/stack_trace/screenshot_url/dom_snapshot/heal_status/heal_log/duration_ms

#6 是**读取层 + 报告生成层 + 前端展示**，不写执行逻辑。

### 1.2 已确认决策

- **范围**：P0 全量 = 列表 + 报告详情 + 导出 HTML/PDF
- **明细依赖**：依赖 #5a 的 ExecutionDetail（失败步骤+截图）
- **PDF 生成**：weasyprint（HTML→PDF，Python 原生无 Chrome 依赖）
- **趋势**：后端 SQL date_trunc 按天聚合，**仅通过率**单一指标（不做自动化率，消除定义纠结）
- **项目隔离**：列表+趋势按 project_id 隔离
- **分享链接**：不做（系统内查看/下载即可）
- **推送**：留 `notifier` 扩展口（本期 stub，后期对接钉钉/微信）
- **报告产物**：渲染后存 MinIO，key 回写 `execution_record.report_url`；查看/下载走后端端点
- **报告幂等**：`report_url IS NOT NULL` 视为已生成，`force=true` 强制重生成

### 1.3 不做（YAGNI / P1）

- 分享链接（对外 URL）
- 自动化率趋势指标
- REPORT-04 推送（钉钉/飞书/邮件）——留 notifier stub
- REPORT-05 180天冷存储
- 用户体系 / 鉴权

---

## 2. 数据层（只读，不建表）

完全消费 #5a 的 `execution_record` + `execution_detail`。#6 不加字段、不建表。

### 2.1 报告产物存储

- HTML 报告渲染后上传 MinIO（复用 `app/core/storage.py`）
- key 约定：`reports/{exec_id}.html` / `reports/{exec_id}.pdf`
- 回写 `execution_record.report_url`（存 HTML key 作为默认产物）
- 分享/查看不暴露 MinIO URL，走后端端点（详情页直接读数据渲染；导出走 report_generator 产物下载）

---

## 3. 服务层

**2 个 service + 1 个 stub**（不碰 #5a 的 execution.py、不改执行逻辑）：

| 文件 | 职责 |
|---|---|
| services/execution_query_service.py | 记录列表（分页+项目隔离+类型/时间筛选）、记录详情、明细列表、趋势聚合 |
| services/report_generator.py | 报告渲染：Jinja2 HTML → weasyprint PDF → 上传 MinIO → 回写 report_url（幂等） |
| services/notifier.py | P1 扩展 stub：报告生成后触发推送（本期仅日志，后期接钉钉/微信） |

### 3.1 ExecutionQueryService

```python
class ExecutionQueryService:
    async def list_records(project_id, exec_type=None, days=7, page=1, page_size=20) -> {items, total}
    async def get_record_detail(exec_id) -> ExecutionRecord + 聚合(失败步骤数/总耗时分解/token)
    async def list_details(exec_id, status='fail') -> [ExecutionDetail]  # 默认失败明细
    async def get_trend(project_id, days=7) -> [{date, pass_rate, exec_count}]
```

- 趋势聚合用 `func.date_trunc('day', started_at)` group by（与 #10 TokenService.get_usage 同款写法），命中 `idx_exec_record_time` 索引
- `pass_rate`：当日执行记录 pass_rate 加权均值（按 total_cases 加权）
- `exec_count`：当日执行记录数
- **不做自动化率**（单一通过率指标）

### 3.2 ReportGenerator

```python
class ReportGenerator:
    async def generate_report(exec_id, force=False) -> {html_key, pdf_key}
        # 1. 取 ExecutionRecord + 关联 ExecutionDetail（含截图URL/错误分类/堆栈）
        # 2. Jinja2 渲染 HTML（templates/report.html）
        # 3. weasyprint HTML→PDF
        # 4. 上传 MinIO（reports/{exec_id}.html / .pdf）
        # 5. 回写 execution_record.report_url（HTML key）
        # 6. 触发 notifier.notify_report_ready（P1 stub）
        # 幂等：report_url IS NOT NULL 且 not force → 直接返回已有 key
```

### 3.3 Notifier（P1 stub）

```python
class Notifier:
    async def notify_report_ready(self, exec_id, meta):
        """P1 预留：本期仅记日志；后期对接钉钉/微信 webhook。
        webhook 配置复用 #10 SystemSettingService（notify category）。"""
        logger.info(f"[notifier stub] report ready for {exec_id}: {meta}")
```

后期实现只改 `notifier.py`，不动报告生成逻辑（单一职责）。

---

## 4. API 层（单 router `reports.py`，prefix /reports）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /reports/records?project_id=&exec_type=&days=&page=&page_size= | 执行记录列表（项目隔离+筛选+分页） |
| GET | /reports/records/{exec_id} | 报告详情（ExecutionRecord + 明细聚合） |
| GET | /reports/records/{exec_id}/details?status=fail | 执行明细列表（默认失败） |
| GET | /reports/trend?project_id=&days=7 | 近N天通过率按天聚合 |
| POST | /reports/{exec_id}/generate?force=false | 生成报告（HTML+PDF 落 MinIO，幂等） |
| GET | /reports/{exec_id}/export?format=html\|pdf | 下载报告产物（字节流，attachment） |

**设计**：
- 前缀 `/reports` 而非 `/executions`——避开 #5a 的 `/executions/*`（run/quick-run/batch-run），语义对齐 §5.2
- `generate` 用 POST（有副作用：写 MinIO + 回写 DB）
- `export` 返回字节流，`Content-Disposition: attachment` 触发下载
- 注册到 `api/__init__.py`

**与 #5a 边界**：#5a `/executions/*` 触发执行+写记录；#6 `/reports/*` 读记录+生成/导出报告。共用表，router 独立互不改。

---

## 5. 前端 + 模板

### 5.1 新建前端

| 文件 | 内容 |
|---|---|
| views/reports/ExecutionList.vue | 项目下拉 + 类型/时间筛选 + 分页表格（时间/类型/通过率/状态/[查看报告]）+ 顶部小趋势折线块 |
| views/reports/ReportDetail.vue | 统计卡片（总/通过/失败/通过率/耗时/token）+ 失败步骤明细表（步骤/动作/错误类型/错误信息/截图缩略图/堆栈展开）+ [导出HTML][导出PDF][重新生成] |
| api/report.js | 封装 /reports/* 全部端点 |

### 5.2 路由 + 菜单

- `router/index.js` 加 `/reports`（列表）+ `/reports/:execId`（详情）
- MainLayout.vue 「质量与报告」子菜单「执行记录与报告」（现 index `/quality/report`）改为指向 `/reports`

### 5.3 Jinja2 报告模板（backend/app/templates/report.html）

- 头部：项目名/执行ID/类型/环境/耗时/时间区间
- 统计卡：总用例/通过/失败/通过率/Token消耗
- 失败步骤表：步骤号/动作/错误类型/错误信息/截图（`<img src=minio_url>`）/堆栈（可折叠）
- 趋势小结：近7天通过率折线（**静态 SVG 内联**，weasyprint 不支持 JS）
- 页脚：生成时间/MoonTest

**weasyprint 注意**：不执行 JS，图表用静态 SVG 内联（后端生成 SVG 字符串塞进 HTML）；截图用 `<img src="minio_url">`（weasyprint 会拉取，需 MinIO 可达——联调验证，本期 mock 占位）。

### 5.4 导出交互

- 导出HTML/PDF：`window.location = /reports/{execId}/export?format=html|pdf`（触发下载）
- 重新生成：POST `/reports/{execId}/generate?force=true`，loading 后刷新详情

---

## 6. 测试 + 依赖

### 6.1 测试（延续 mock）

| 文件 | 覆盖 |
|---|---|
| test_execution_query_service.py | 列表分页+筛选、详情聚合、明细列表、趋势按天聚合算术（mock db.execute） |
| test_report_generator.py | 渲染 HTML 非空、PDF 生成（mock weasyprint）、上传 MinIO（mock storage）、幂等（report_url 已存跳过）、force 重生成、notifier stub 被调不报错 |
| test_api_reports.py | 端点契约（dependency override，6 端点 status/shape） |

### 6.2 依赖（backend/requirements.txt）

- `weasyprint`（PDF，新增）
- `Jinja2`（FastAPI 通常已带，确认；无则加）
- 不加钉钉/微信 webhook 依赖（P1 才加）

### 6.3 weasyprint 环境风险

weasyprint 在 Windows 依赖 GTK/Pango/cairo，装麻烦。策略：requirements 加 weasyprint，测试全 mock（`@patch('weasyprint.HTML')`），联调时在能装 GTK 的环境真跑 PDF。本期 mock 不触发真实渲染，不阻塞。spec 标注此风险。

---

## 7. 与 #5a 边界 + worktree 策略

### 7.1 文件边界

- #6 **只读** `execution_record` / `execution_detail` model（import 不改字段）
- #6 **不碰** `services/script_executor.py`、`tasks/`、`api/v1/executions.py`（#5a 执行触发链路）
- #6 **不碰** `models/execution.py`（#5a 在改，#6 只 import 用）
- 共享文件：仅 `api/__init__.py`（注册 reports router，追加）+ `requirements.txt`（加 weasyprint/jinja2），均追加，git 易自动合并

### 7.2 worktree 策略

- #6 在**新 worktree** `module6-execution-reports` 开发，基于含 #5a 的 master
- **前置条件**：#5a 完成（ExecutionDetail/ScriptExecutor 已落地）
- 不与 #10 worktree 混；#6 实施时 #5a 应已完成，从最新 master 拉 worktree

---

## 8. 诚实边界

- 全部 mock，无真实 DB / 无真实 MinIO / 无真实 weasyprint 渲染
- 报告产物上传/下载 MinIO 真实链路留联调
- notifier 是 stub，推送留 P1
- 分享链接不做（系统内查看/下载）

---

## Self-Review 记录（2026-08-25）

| 项 | 结果 |
|---|---|
| 占位符扫描 | 无 TBD/TODO |
| 内部一致性 | 不建表只读 #5a 两表、/reports 前缀避开 #5a、趋势仅通过率单一指标、notifier stub P1——全文一致 |
| 范围检查 | 报告中心+导出，单 spec 可承载，约 1.5-2 天（等 #5a 完成） |
| 歧义检查 | 已消除：不做自动化率（消除 a/b 定义纠结）、不做分享、推送留 stub |
| 依赖前置 | 依赖 #5a 的 ExecutionDetail（master c30b103+ 已建），字段齐（screenshot_url/dom_snapshot/error_type/stack_trace）|

确认后转入 writing-plans 生成实施计划（等 #5a 完成后实施）。
