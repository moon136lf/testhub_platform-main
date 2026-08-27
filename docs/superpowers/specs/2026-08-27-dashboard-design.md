# #11 仪表盘优化 — Design Spec

> **创建**：2026-08-27
> **分支**：`worktree-module11-dashboard`（基于最新 master）
> **目标**：把 `Dashboard.vue` 的硬编码 mock 换成真实聚合数据。UI 壳已存在，本模块主要是后端聚合端点 + 前端接线。

---

## 1. 背景 & 现状

需求文档 §2.1 仪表盘为 P1 优先级。现有 `frontend/src/views/Dashboard.vue`（368 行）UI 完整：
- 4 统计卡（入库元素数 / 测试用例数 / 已自动化数 / 测试点数）
- 今日 AI 调用次数 + 今日 Token 消耗
- 2 饼图（元素类型分布 / 用例类型分布）
- AI 调用趋势折线（调用次数 + Token 消耗）

**但全部硬编码 mock**：`refreshData()` 写死 156/243/187/324，图表 data 数组写死。#11 = 后端聚合 + 前端接真实 API。

---

## 2. 数据来源（已核对模型）

| 指标 | 来源表/模型 | 过滤 |
|---|---|---|
| 入库元素数 | `element_repository` (ElementRepository) | project_id? + `status='active'` |
| 测试用例数 | `test_case` (TestCase) | project_id? + `is_deleted=False` |
| 已自动化数 | `test_case` (TestCase) | project_id? + `is_deleted=False` + `automation_status='automated'` |
| 测试点数 | `test_point` (TestPoint) | project_id? |
| 今日 AI 调用次数 | `ai_call_log` COUNT | project_id? + `created_at >= 今日 0 点(UTC)` |
| 今日 Token 消耗 | `SUM(ai_call_log.tokens_used)` | 同上 |
| 元素类型分布 | `element_repository GROUP BY element_type` COUNT | project_id? + `status='active'` |
| 用例类型分布 | `test_case GROUP BY case_type` COUNT | project_id? + `is_deleted=False` |
| AI 调用趋势 | `ai_call_log date_trunc('day',created_at)` → COUNT + SUM(tokens) | project_id? + 近 N 天 |

### 2.1 关键决策

- **4 卡片 + 今日统计是「当前总量」**，不受 `days` 影响；只有 AI 调用趋势折线受 `days`（7/30）影响（符合 §2.1）。
- **`project_id` 可选**：选「全部项目」时跳过 project_id 过滤（用户确认 2026-08-27）。与 `/scripts/stats` 一致（project_id 可选）。
- **「今日」用 UTC 0 点边界**（`datetime.now(timezone.utc)` 取 date 当日 0 点）。与 #6/#10 全 UTC 风格一致。已知时区近似，联调时按业务时区调整。
- **元素计数过滤 `status='active'`**（排除 deprecated/deleted 元素）。
- **测试用例计数过滤 `is_deleted=False`**（软删除约定，见 W1）。

---

## 3. 架构（单聚合端点）

```
GET /api/v1/dashboard/overview?project_id=&days=7
  → DashboardService.get_overview(project_id, days)
  → 单次响应（卡片区 + 分布区 + 趋势区）
```

### 3.1 后端新建文件

| 文件 | 职责 |
|---|---|
| `backend/app/services/dashboard_service.py` | DashboardService：聚合 4 表 |
| `backend/app/api/v1/dashboard.py` | 单 router，prefix `/dashboard`，1 个 GET 端点 |
| `backend/app/schemas/dashboard.py` | OverviewResponse schema |
| `backend/tests/test_dashboard_service.py` | service 单测（mock db） |
| `backend/tests/test_api_dashboard.py` | API 端点测试（dependency_overrides） |

### 3.2 后端修改文件

| 文件 | 改动 |
|---|---|
| `backend/app/api/__init__.py` | import + 注册 dashboard router（追加 2 行） |

**后端不改：** 不建表（只读 4 表：element_repository / test_case / test_point / ai_call_log）、不改任何现有 service/router/model。

### 3.3 前端修改

| 文件 | 改动 |
|---|---|
| `frontend/src/views/Dashboard.vue` | `refreshData()` 改调真实 API；3 个 chart setOption 用 API 数据；切换项目/时间/刷新都重拉 overview |
| `frontend/src/api/dashboard.js` | 新建，封装 `/dashboard/overview` |

**前端不改：** 路由/菜单已有（`/dashboard` 现成），`MainLayout.vue`、`router/index.js` 不动。

---

## 4. API 契约

### GET /api/v1/dashboard/overview

**Query:**
- `project_id: str | None`（可选，空=全部项目）
- `days: int = 7`（ge=1, le=90，仅影响趋势折线）

**Response:**
```json
{
  "code": 0,
  "data": {
    "stats": {
      "element_count": 156,
      "case_count": 243,
      "automated_count": 187,
      "point_count": 324
    },
    "today": {
      "ai_calls": 128,
      "tokens_used": 45672
    },
    "element_distribution": [
      {"type": "button", "count": 30},
      {"type": "input", "count": 25}
    ],
    "case_distribution": [
      {"type": "functional", "count": 60},
      {"type": "api", "count": 40}
    ],
    "ai_trend": [
      {"date": "2026-08-21", "call_count": 50, "tokens": 15000},
      {"date": "2026-08-22", "call_count": 80, "tokens": 24000}
    ]
  }
}
```

### 4.1 DashboardService 签名

```python
class DashboardService:
    def __init__(self, db: AsyncSession): ...
    async def get_overview(self, project_id: Optional[str] = None, days: int = 7) -> dict:
        # 返回 stats/today/element_distribution/case_distribution/ai_trend
```

- `project_id=None` → 跳过 project_id 过滤
- `project_id` 非空 → `UUID(project_id)`（非法 UUID 让 500，本期不优雅处理，与 #6 一致）

---

## 5. 数据流

```
前端：选项目/时间/点刷新 → refreshData()
  → dashboardAPI.getOverview({project_id, days})
  → GET /dashboard/overview
  → DashboardService.get_overview
      ├─ element_repository: count(active) + group by type
      ├─ test_case: count(!deleted) + count(automated) + group by type
      ├─ test_point: count
      └─ ai_call_log: 今日 count + sum(tokens) + 趋势(date_trunc)
  → 响应 → 前端填 4 卡 + 今日 + 2 饼 + 趋势折线
```

---

## 6. 边界 & 测试策略

### 6.1 边界

- 只读 4 表，不改字段，不碰其他模块 service/router
- 共享文件改动最小：`api/__init__.py` 追加 router 注册

### 6.2 测试策略

- **全 mock**（无真实 DB），与 #6/#10 一致
- **吸取 #6 教训**：日期/Row 用 `MagicMock` 带 `.date()` 方法，不用纯 tuple，避免 mock 把实现带偏
- service 测试 mock `AsyncSession.execute`，断言真实输出形态（数字/分布数组/趋势数组）
- API 测试用 `app.dependency_overrides` mock service，覆盖：正常 / project_id 缺省 / 404 不适用（overview 永不 404）

---

## 7. 不做项（YAGNI）

- ❌ 不做实时刷新（轮询/SSE）——需求未要求
- ❌ 不做缓存——数据量小，单查够快
- ❌ 不做导出——需求未要求
- ❌ 不做自动化率卡片——§2.1 明确只有这 4 卡
- ❌ 不改路由/菜单——已存在

---

## 8. 与需求偏差

无。本设计严格对齐 §2.1 字段定义与页面结构。

---

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 「今日」UTC 边界与业务时区不符 | 已知近似，联调时按业务时区调整 |
| 4 表 count 在大数据量下慢 | 本期数据量小，暂不优化；未来可加 Redis 缓存 |
| 全 mock 测试不监督真实 SQL | 趋势用 MagicMock 带 `.date()` 覆盖真实分支（#6 教训） |

---

**Spec 完成，待 user review 后进入 writing-plans。**
