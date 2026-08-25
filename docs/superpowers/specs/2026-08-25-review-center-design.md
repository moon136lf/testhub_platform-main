# 用例评审与E2E精修（#7）设计 — 评审中心 + 批量精修 + 汇总

**版本**：v1.0
**日期**：2026-08-25
**作者**：Claude Code (Opus 4.8)
**状态**：待审批（#3 已落地，#7 可独立实施，不依赖 #5a）
**流程**：Superpowers（brainstorming → writing-plans → TDD → 编码 → verification）
**范围依据**：需求 §3.2 用例评审与E2E精修

---

## 1. 概述

#7「用例评审与E2E精修」——把 #3 已落地的单用例级评审/精修能力，整合成**评审中心流程页**：汇总统计 + 用例列表 + 可行性分析 + 项目级 E2E 精修报告区 + 批量精修/批量评审。后端复用 #3 的 CaseRefiner 引擎 + TestCase 评审字段，#7 只加薄编排层（ReviewService）+ 项目维度 API + 前端页。

### 1.1 依赖（#3 已落地 master）

#7 **不建表、不加字段、不重写引擎**，复用 #3：
- `CaseRefiner`（5 维度：步骤完整性/断言增强/异常路径/数据准备/可行性修正，规则+LLM 混合）
- TestCase 6 评审字段：review_status / review_comment / feasibility_level / cannot_automate_reason / refinement_report(JSONB) / refined_at + is_finalized
- 单用例 API（#3）：`POST /test-cases/{id}/refine`、`GET /refinement-report`、`POST /apply-suggestions`、`PATCH /review`、versions/rollback

### 1.2 已确认决策

- **范围**：P0 全量 = 评审中心页 + 批量精修 + 批量评审 + 项目级汇总报告 + 汇总统计
- **批量精修**：同步顺序（复用 #3 同步策略，不引 Celery）
- **汇总精修报告**：项目级聚合各 case.refinement_report 的 suggestions，带 case 透传
- **REVIEW-06 仓库回写**：不做（跨 #4/#5，留 #4/#5）
- **worktree**：#7 新 worktree `module7-review-center`，基于含 #3 的 master（#7 不依赖 #5a）

### 1.3 不做（YAGNI）

- REVIEW-06 页面对象仓库回写（跨 #4/#5）
- LLM 异步精修（同步顺序）
- 独立评审人体系（无用户体系，operator 沿用 system 占位）

---

## 2. 数据层（不建表，只读消费 #3 字段）

#7 **不建表、不加字段**。完全消费 #3 的 TestCase 评审字段 + refinement_report JSONB。

### 2.1 汇总统计来源（§3.2.2「汇总统计」「自动化可行性分析」两卡）

- 总用例/待评审/已通过/需修改 → `COUNT(*) GROUP BY review_status`（一条 SQL）
- 完全/部分/需手工自动化 → `COUNT(*) GROUP BY feasibility_level`
- 可自动化率 = (full + partial) / total × 100%

### 2.2 项目级精修报告聚合

- 取项目下所有 `refinement_report IS NOT NULL` 的用例
- 聚合每条 `suggestions` 数组 → 项目级建议总表（每条带 case_id / case_name 透传）
- 「应用全部」= 对每条 case 调 #3 `apply-suggestions`；「逐条确认」= 单条 apply

---

## 3. 服务层 + API

### 3.1 ReviewService（薄编排，复用 #3 不重写）

`services/review_service.py`（新建）：
```python
class ReviewService:
    async def get_review_stats(project_id) -> dict
        # COUNT GROUP BY review_status + feasibility_level + 可自动化率
    async def batch_refine(project_id, case_ids) -> list
        # 顺序对每个 case 调 TestCaseService.refine_case（#3 已有）
        # 同步阻塞，返回每条 {case_id, score, feasibility_level, suggestion_count, error?}
        # 单条失败不中断（容错）
    async def get_project_refinement_report(project_id) -> dict
        # 聚合项目下所有 refinement_report：建议总表（带 case_id/name 透传）
    async def batch_update_review(project_id, case_ids, review_status, review_comment) -> dict
        # 批量改评审状态（REVIEW-01 流转），复用 update_case 的 review 字段
```

**复用不重写**：`batch_refine` 内部循环调 `TestCaseService.refine_case`；`batch_update_review` 内部调 `update_case`。ReviewService 只做编排+聚合，不碰 CaseRefiner。

### 3.2 API（新 router `reviews.py`，prefix /reviews）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /reviews/stats?project_id= | 评审汇总统计（评审状态分布 + 可行性分布 + 可自动化率） |
| POST | /reviews/batch-refine | 批量精修（body: project_id + case_ids[]），同步顺序 |
| GET | /reviews/refinement-report?project_id= | 项目级精修报告汇总（建议总表带 case 透传） |
| POST | /reviews/batch-review | 批量改评审状态（body: case_ids[] + review_status + review_comment） |

**为何单列 `/reviews`**：#3 单用例精修在 `/test-cases/{id}/refine`（用例维度），#7 批量/汇总是**项目维度**，语义不同，单列前缀清晰，不撞 #3。

**与 #3 边界**：#3 = 单用例（`/test-cases/{id}/*`）；#7 = 项目级统计+批量+汇总（`/reviews/*`）。共用字段+refinement_report，#7 复用 #3 service，不重复实现引擎。

---

## 4. 前端评审中心页

### 4.1 新建

| 文件 | 内容 |
|---|---|
| views/reviews/ReviewCenter.vue | 评审中心页（整合 §3.2.2 整页结构，4 块） |
| api/review.js | 封装 /reviews/* + 复用 #3 单用例精修 API |

### 4.2 ReviewCenter.vue 结构（对齐 §3.2.2）

**① 顶部筛选**：项目下拉 + 模块下拉（按 page_name 分组）+ 评审状态筛选（全部/待评审/已通过/需修改）+ 查询

**② 汇总统计卡**：总用例 / 待评审 / 已通过 / 需修改（调 `GET /reviews/stats`），进度条显示各状态占比

**③ 用例列表 + 可行性**：
- 表格：☑勾选 / 用例名 / 关联测试点 / 评审状态(tag) / 可行性(tag) / 精修评分 / [精修][评审]
- 可行性统计条：完全/部分/需手工占比 + 可自动化率进度条
- 批量工具栏：选中 N → [批量精修][批量评审]

**④ E2E 精修报告区**（项目级汇总）：
- 精修时间戳 + 优化建议总表（`GET /reviews/refinement-report`，带 case 名透传）
- [应用全部建议]（遍历调 #3 apply-suggestions）+ 每条 [确认]/[拒绝]
- 应用后刷新列表+统计

### 4.3 路由 + 菜单

- `router/index.js` 加 `/reviews` → ReviewCenter
- MainLayout.vue「AI与用例」区「用例评审与E2E精修」菜单项改指 `/reviews`（修复死链）

### 4.4 交互

- 批量精修：选中 → loading → 每条结果（评分/可行性/建议数）→ 刷新统计
- 批量评审：弹窗选状态+意见 → 应用 → 刷新
- 单条精修/评审：复用 #3 单用例 API

---

## 5. 测试 + 边界

### 5.1 测试（延续 mock）

| 文件 | 覆盖 |
|---|---|
| test_review_service.py | 统计聚合算术（GROUP BY mock）、批量精修顺序调 refine_case + 容错、项目级报告聚合、批量改评审状态（mock db） |
| test_api_reviews.py | 4 端点契约（dependency override，status/shape） |

**关键测试点**：
- `get_review_stats`：mock 分组计数，断言可自动化率 = (full+partial)/total
- `batch_refine`：mock refine_case，断言顺序调用 N 次、收集结果、单条失败不中断
- `get_project_refinement_report`：mock 几条 case 的 refinement_report JSONB，断言建议总表带 case_id/name 透传

### 5.2 与 #3 边界（避免重写）

- #7 **只读+编排**：复用 #3 `TestCaseService.refine_case` / `apply_suggestions` / `update_case`，**不重写** CaseRefiner
- #7 **不碰** `case_refiner.py`、`test_case_service.py` 的 refine/apply 逻辑、`schemas/refinement.py`
- #7 新增：`review_service.py`（薄编排）+ `reviews.py` router + 前端页
- 共享文件：`api/__init__.py`（注册 reviews router，追加）+ `router/index.js` + `MainLayout.vue`（菜单改指），追加/改 index，易合并

### 5.3 worktree 策略

- #7 依赖 #3（master 已有）+ 不依赖 #5a
- **新 worktree** `module7-review-center`，基于含 #3 的 master
- 与 #10/#6 worktree 互不混

### 5.4 诚实边界

- 全 mock，无真实 DB / 无真实 LLM（CaseRefiner LLM 层 #3 已是占位）
- 批量精修同步阻塞，大批量可能慢（联调验证，本期不优化）

---

## Self-Review 记录（2026-08-25）

| 项 | 结果 |
|---|---|
| 占位符扫描 | 无 TBD/TODO |
| 内部一致性 | 不建表只读 #3 字段、/reviews 项目维度 vs /test-cases/{id} 用例维度、同步顺序批精修、项目级汇总报告——全文一致 |
| 范围检查 | 评审中心页+批量+汇总，单 spec 可承载，约 1-1.5 天 |
| 歧义检查 | 已澄清：不重写引擎只编排、不做 REVIEW-06、不做异步 |
| 依赖前置 | #3 已在 master（CaseRefiner+字段+单用例 API），#7 不依赖 #5a，可独立实施 |

确认后转入 writing-plans 生成实施计划（#7 不依赖 #5a，#10 合回 master 后即可实施）。
