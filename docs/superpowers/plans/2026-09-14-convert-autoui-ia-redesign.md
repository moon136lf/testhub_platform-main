# 用例转脚本+UI自动化测试 前端信息架构改造 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 spec `docs/superpowers/specs/2026-09-14-convert-autoui-ia-redesign.md` 改造两页面信息架构：转脚本页=待转用例列表+单条转换直播；UI自动化=脚本库（用例名/中文枚举/删除/分页）+ 测试集详情独立页（测试记录体系）。

**Architecture:** 前端两页面重构（ScriptConvert.vue / AutoUITest.vue）+ 新增测试集详情页（TestSetDetail.vue）；后端配套：脚本名改用例名、脚本删除端点、ExecutionRecord 加 test_set_id、测试集记录聚合端点。复用现有分页/SSE/报告组件。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Vue3 + Element Plus + pytest（基线 896 passed）

---

## 现状要点（执行 agent 必读）

- 测试命令：`cd backend && PYTHONUTF8=1 /d/MoonTest/backend/venv/Scripts/python.exe -m pytest -q -c pytest.ini --rootdir=.`（基线 **896**）；前端 `cd frontend && npm run build`（node_modules 已装）
- commit 只 stage 指定文件（项目铁律）；worktree 用 `git worktree add <path> -b <branch> master` 手动建
- `backend/app/api/v1/scripts.py:108` list_scripts 已有 page/page_size/category/keyword/排序（created_at desc——**要改 updated_at desc**）；`:32 _enrich_scripts` 已聚合 bound_case/test_set_refs
- `backend/app/services/batch_naming.py:31 build_script_name(batch_name, fallback_title, ts, taken)`——现批次名优先，要改**用例名优先**
- `backend/app/services/script_convert_service.py:95-115` 转换命名调用点（`base = batch_name-自动化脚本HHmmss if batch_name else title`）
- `backend/app/api/v1/test_cases.py:302` is_finalized 服务端过滤参数已有；`:424` DELETE /{case_id} 已有（前端接即可）
- `backend/app/models/execution.py:13 ExecutionRecord` **无 test_set_id 列**（要加）；`execution_query_service.py:19 list_records` 按 project+exec_type+days 过滤
- `backend/app/api/v1/test_sets.py` 无 DELETE 端点（要加）
- 前端：`frontend/src/views/ScriptConvert.vue`（365行）、`frontend/src/views/AutoUITest.vue`（735行，Tab: sets/library）、路由 `frontend/src/router/index.js:78/91`（ai/convert、auto/ui）
- 后端 8000 **无 --reload**（CLAUDE.md：改后端必须重启）；测删除类改动别忘同步前端 api 封装（`frontend/src/api/*.js`）
- 真实 DB：PG16 localhost:5433（.env 已配）；DM 项目 project_id=3ff3ea1e-7c4c-4ee5-afcd-c52ae34e074b

---

## Task 1: 后端——脚本名改用例名 + 脚本删除端点 + 列表排序修正

**Files:**
- Modify: `backend/app/services/batch_naming.py:31-45`
- Modify: `backend/app/services/script_convert_service.py:95-115`（命名调用点）
- Modify: `backend/app/api/v1/scripts.py`（order_by updated_at + DELETE 端点）
- Test: `backend/tests/test_script_naming_and_delete.py`（新建）

- [ ] **Step 1: 写失败测试（命名：用例名优先）**

```python
"""脚本名改用例名 + 脚本删除端点（IA改造 Task1）。"""
from app.services.batch_naming import build_script_name
from datetime import datetime


def test_build_script_name_case_title_first():
    """用例名优先：不再拼 批次名-自动化脚本HHmmss。"""
    ts = datetime(2026, 9, 14, 10, 0, 0)
    name = build_script_name("批次A", "登录功能验证", ts, taken=set())
    assert name == "登录功能验证"


def test_build_script_name_collision_suffix():
    ts = datetime(2026, 9, 14, 10, 0, 0)
    name = build_script_name("批次A", "登录功能验证", ts, taken={"登录功能验证"})
    assert name == "登录功能验证-2"
    name2 = build_script_name("批次A", "登录功能验证", ts, taken={"登录功能验证", "登录功能验证-2"})
    assert name2 == "登录功能验证-3"


def test_build_script_name_empty_title_fallback():
    ts = datetime(2026, 9, 14, 10, 0, 0)
    name = build_script_name("批次A", "", ts, taken=set())
    assert "自动化脚本" in name  # 无用例名回退批次名风格
```

- [ ] **Step 2: 跑确认失败**

Run: `pytest tests/test_script_naming_and_delete.py -v`
Expected: FAIL（现返回 "批次A-自动化脚本100000"）

- [ ] **Step 3: 改 build_script_name（用例名优先）**

```python
def build_script_name(batch_name: str | None, fallback_title: str,
                      ts: datetime, taken: set[str] | None = None) -> str:
    """脚本名: 用例名优先(fallback_title); 撞名追加 -2/-3...(上限10次);
    无用例名时回退 批次名-自动化脚本HHmmss 风格。"""
    taken = taken or set()
    base = fallback_title or (
        f"{batch_name}-自动化脚本{ts.strftime('%H%m%S')}" if batch_name
        else f"自动化脚本{ts.strftime('%H%m%S')}")
    candidate = base
    for n in range(2, 12):
        if candidate not in taken:
            return candidate
        candidate = f"{base}-{n}"
    return f"{base}-{ts.strftime('%H%m%S')}"
```

- [ ] **Step 4: 改转换调用点（script_convert_service.py:97-101）**

```python
        if case.get("project_id"):
            base_title = normalized.title or (f"{batch_name}-自动化脚本" if batch_name else "自动化脚本")
            r = await self.db.execute(
                select(ScriptAsset.name).where(
                    ScriptAsset.project_id == case["project_id"],
                    ScriptAsset.name.like(f"{base_title}%")))
            taken = set(r.scalars().all())
        name = build_script_name(batch_name, normalized.title,
                                 datetime.now(), taken=taken)
```

（`base` 变量改 `base_title`，like 前缀用用例名——查重逻辑对齐新命名。）

- [ ] **Step 5: 跑命名测试 + 既有转换测试**

Run: `pytest tests/test_script_naming_and_delete.py tests/test_script_convert_service.py -v`
Expected: PASS（既有测试若断言旧命名格式，按新语义更新断言——用例名优先）

- [ ] **Step 6: 写失败测试（脚本删除端点）**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.api.v1 import scripts as scripts_api


@pytest.mark.asyncio
async def test_delete_script_soft(monkeypatch):
    """DELETE /scripts/{id} → ScriptAsset.is_deleted=True。"""
    asset = MagicMock(); asset.is_deleted = False
    monkeypatch.setattr(scripts_api, "db_get_script", AsyncMock(return_value=asset))
    # 实现 mypy: 端点内用 db.get(ScriptAsset, id)——这里 patch get_db 会太重，
    # 改为直接实现并断言赋值；若无独立 helper 则此测试改为端点函数直调（照 test_script_content_passthrough 风格）


@pytest.mark.asyncio
async def test_delete_script_404():
    svc_deleted = None
    # 端点直调风格：伪造 db（get 返回 None）→ 断言 HTTPException 404
    from fastapi import HTTPException
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as ei:
        await scripts_api.delete_script("00000000-0000-0000-0000-000000000000", db=db)
    assert ei.value.status_code == 404
```

**实现注意**：删除端点用直调风格测试（仓库无 ASGI client 惯例）：

```python
# scripts.py 追加
@router.delete("/{script_id}", status_code=200)
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """删除脚本资产（软删，IA改造：脚本库操作列）。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    asset = await db.get(ScriptAsset, sid)
    if not asset:
        raise HTTPException(status_code=404, detail="脚本不存在")
    asset.is_deleted = ScriptAsset.__table__.c.is_deleted.name and True  # 见下
    # ScriptAsset 现无 is_deleted 列——执行时先 grep 模型确认；无则加列(Boolean, default=False, server_default="false")
    db.add(asset)
    await db.commit()
    return {"code": 0, "message": "deleted"}
```

**执行时先核对**：`grep -n "is_deleted" backend/app/models/test_case.py`（ScriptAsset 是否已有 is_deleted；没有则加列并同步 `backend/migrations/` 建 .sql 幂等脚本，参照 `migrations/phase10_execution_bugs.sql` 风格，应用方式照 Task 报告惯例 asyncpg 直跑）。list_scripts 主查询加 `ScriptAsset.is_deleted.is_(False)`（若有该列）。

- [ ] **Step 7: 列表排序改 updated_at desc**

scripts.py 两处 `order_by(ScriptAsset.created_at.desc())` 改 `order_by(ScriptAsset.updated_at.desc())`（updated_at 列存在，models/test_case.py:148）。

- [ ] **Step 8: 全量回归 + commit**

Run: `PYTHONUTF8=1 /d/MoonTest/backend/venv/Scripts/python.exe -m pytest -q -c pytest.ini --rootdir=.`（≥896，无回退）

```bash
git add backend/app/services/batch_naming.py backend/app/services/script_convert_service.py backend/app/api/v1/scripts.py backend/app/models/test_case.py backend/migrations/ backend/tests/test_script_naming_and_delete.py
git commit -m "feat(scripts): 脚本名改用例名+删除端点+列表按更新时间倒序 — IA改造T1"
```

---

## Task 2: 后端——测试集删除 + ExecutionRecord.test_set_id + 测试集记录端点

**Files:**
- Modify: `backend/app/models/execution.py`（加 test_set_id 列）
- Modify: `backend/app/tasks/script_tasks.py`（执行测试集时写入 test_set_id）
- Modify: `backend/app/api/v1/test_sets.py`（DELETE + records 端点）
- Modify: `backend/app/services/execution_query_service.py`（按 test_set_id 过滤 + 趋势聚合）
- Modify: `backend/migrations/`（新 .sql：execution_record 加列，幂等）
- Test: `backend/tests/test_testset_records.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""测试集删除 + 记录关联（IA改造 Task2）。"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
from app.api.v1 import test_sets as ts_api
from app.models.execution import ExecutionRecord


def test_execution_record_has_test_set_id():
    assert hasattr(ExecutionRecord, "test_set_id")


@pytest.mark.asyncio
async def test_delete_test_set():
    ts = MagicMock(); ts.id = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=ts)
    db.commit = AsyncMock()
    resp = await ts_api.delete_test_set(str(ts.id), db=db)
    assert resp["code"] == 0
    db.delete.assert_called_once_with(ts)


@pytest.mark.asyncio
async def test_delete_test_set_404():
    db = MagicMock(); db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as ei:
        await ts_api.delete_test_set("00000000-0000-0000-0000-000000000000", db=db)
    assert ei.value.status_code == 404
```

- [ ] **Step 2: 跑确认失败**

Run: `pytest tests/test_testset_records.py -v`
Expected: FAIL（test_set_id 不存在 / delete_test_set 未定义）

- [ ] **Step 3: 实现**

1. execution.py ExecutionRecord 加列：
```python
    test_set_id = Column(UUID(as_uuid=True), ForeignKey("test_set.id", ondelete="SET NULL"), nullable=True, index=True, comment="来源测试集(测试集执行时写入)")
```
2. 迁移 SQL `backend/migrations/phase_ia_testset_records.sql`（幂等）：
```sql
ALTER TABLE execution_record ADD COLUMN IF NOT EXISTS test_set_id UUID REFERENCES test_set(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_exec_record_test_set ON execution_record(test_set_id);
```
（执行时用 asyncpg 直跑本地 PG 应用——参照 phase10 惯例；**先确认表名**：grep `__tablename__` models/execution.py）
3. script_tasks.py 执行入口（约:180 ExecutionRecord(...) 构造处）：调用方若带 test_set_id（前端执行测试集传参）则写入——核对 run_scripts_task 的请求 schema（`grep -n "script_ids\|test_set" backend/app/schemas/*.py backend/app/api/v1/scripts.py | grep -i run`），加 `test_set_id: Optional[str]` 透传。
4. test_sets.py 加端点：
```python
@router.delete("/{set_id}")
async def delete_test_set(set_id: str, db: AsyncSession = Depends(get_db)):
    try:
        sid = uuid.UUID(set_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    ts = await db.get(TestSet, sid)
    if not ts:
        raise HTTPException(status_code=404, detail="测试集不存在")
    await db.delete(ts)
    await db.commit()
    return {"code": 0, "message": "deleted"}
```
5. execution_query_service.py：list_records 加 `test_set_id: Optional[UUID] = None` 过滤参数；新增 `set_trend(db, test_set_id, limit=10)`：
```python
    async def set_trend(self, test_set_id, limit: int = 10) -> list:
        rows = (await self.db.execute(
            select(ExecutionRecord.pass_rate, ExecutionRecord.status, ExecutionRecord.started_at)
            .where(ExecutionRecord.test_set_id == test_set_id,
                   ExecutionRecord.is_deleted.is_(False))
            .order_by(ExecutionRecord.started_at.desc()).limit(limit))).all()
        return [{"pass_rate": float(r[0] or 0), "status": r[1],
                 "started_at": r[2].isoformat() if r[2] else None} for r in rows]
```
6. test_sets.py 加 `GET /{set_id}/records`（page/page_size/result 筛选 all/success/failed）+ `GET /{set_id}/trend`（调 set_trend）。

- [ ] **Step 4: 跑通过 + 全量回归**

Run: `pytest tests/test_testset_records.py -v && PYTHONUTF8=1 /d/MoonTest/backend/venv/Scripts/python.exe -m pytest -q -c pytest.ini --rootdir=.`
Expected: PASS，≥896+新增

- [ ] **Step 5: commit**

```bash
git add backend/app/models/execution.py backend/app/tasks/script_tasks.py backend/app/api/v1/test_sets.py backend/app/services/execution_query_service.py backend/migrations/phase_ia_testset_records.sql backend/tests/test_testset_records.py
git commit -m "feat(testsets): 删除端点+ExecutionRecord.test_set_id+记录/趋势端点 — IA改造T2"
```

---

## Task 3: 前端——ScriptConvert.vue 重构（待转用例列表）

**Files:**
- Modify: `frontend/src/views/ScriptConvert.vue`（整体重构）

- [ ] **Step 1: 重构页面（核心结构）**

```vue
<template>
  <div>
    <!-- 顶栏：项目选择（默认第一个） -->
    <el-select v-model="form.projectId" @change="loadCases">...</el-select>
    <!-- 用例列表 -->
    <el-table :data="cases" v-loading="loading">
      <el-table-column prop="name" label="用例名" min-width="240" show-overflow-tooltip />
      <el-table-column prop="priority" label="优先级" width="90" />
      <el-table-column label="转换状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.automation_status)">{{ statusCn(row.automation_status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="170" sortable />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="convertOne(row)">转脚本</el-button>
          <el-button link @click="showDetail(row)">详情</el-button>
          <el-button v-if="row.automation_status === 'converted'" link
                     type="success" @click="gotoScript(row)">查看脚本</el-button>
          <el-button link type="danger" @click="delCase(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
                   layout="total, prev, pager, next" @current-change="loadCases" />
    <!-- SSE 直播区（单条转换时显示） -->
    <el-drawer v-model="liveVisible" title="转换直播" size="45%">
      <div ref="logBox" class="live-log">...</div>
    </el-drawer>
    <!-- 用例详情抽屉 -->
    <el-drawer v-model="detailVisible" title="用例详情" size="55%">
      <!-- 步骤表：步骤/操作/目标/测试数据/预期结果 -->
    </el-drawer>
  </div>
</template>
```

实现要点：
- onMounted：`GET /projects` 取第一个 project_id 填入 form.projectId → loadCases
- loadCases：`GET /test-cases?project_id=&is_finalized=true&page=&page_size=20`（**核对实际端点路径**——grep frontend/src/api/testCase.js 现有封装）；排序依赖后端（Task1 改 updated_at desc——**test_cases 列表若仍是 created_at 排序，Task1 一并改**）
- convertOne(row)：调现有转换 API（单条 case_ids=[row.id]），SSE 订阅复用现有 sse 封装（grep 现文件 `sse\|EventSource` 段保留），直播完成刷新列表
- gotoScript(row)：`router.push({ path: '/auto/ui', query: { caseId: row.id } })`（脚本库定位到该用例脚本——AutoUITest 读 query 高亮/筛选用例）
- delCase(row)：ElMessageBox.confirm → `DELETE /test-cases/{id}`（api/testCase.js 若无该封装则加）
- 状态映射表（前端统一）：
```js
const AUTOMATION_STATUS_CN = { pending: '未转换', converting: '转换中', converted: '已转换', failed: '转换失败' }
```
- 移除旧"多选下拉+批量转换"区块与"stats 统计卡"（简化；若用户后续要批量再加）

- [ ] **Step 2: build 验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: commit**

```bash
git add frontend/src/views/ScriptConvert.vue frontend/src/api/testCase.js
git commit -m "feat(frontend): 转脚本页重构为定稿用例列表(默认项目/单条转换直播/查看脚本跳转/删除) — IA改造T3"
```

---

## Task 4: 前端——AutoUITest.vue 脚本库 Tab 改造

**Files:**
- Modify: `frontend/src/views/AutoUITest.vue`（脚本库 Tab 部分）

- [ ] **Step 1: 脚本库列表改造**

1. 列调整：
   - 脚本名列：**优先显示 row.bound_case || row.name**（存量旧命名显示用例名），title 属性透出原始 name
   - 加"来源批次"列（row.batch_name，有则显示，无则 —）
   - 现有 绑定用例 列头改"绑定用例"保留；**修复为空**：核对后端返回 d["bound_case"] 与前端取值路径一致（`grep -n "bound_case" frontend/src/views/AutoUITest.vue`——若前端读别的键名则对齐）
2. **枚举中文映射表**（放 `<script setup>` 顶部统一管理）：
```js
const LAST_STATUS_CN = { never_run: '未运行', success: '成功', fail: '失败', blocked: '阻塞', running: '运行中' }
const LOCATOR_SOURCE_CN = { element_library: '元素库', ai_generated: 'AI生成', mixed: '混合', none_draft: '草稿' }
const SCRIPT_STATUS_CN = { draft: '草稿', ready: '就绪', pending_confirm: '待确认', deprecated: '已弃用' }
```
   列内用 `{{ LAST_STATUS_CN[row.last_status] || row.last_status }}` 模式；执行结果列 tag 颜色对应（成功=success，失败=danger，阻塞=warning，未运行=info）
3. 操作列加**删除**：
```js
async function delScript(row) {
  await ElMessageBox.confirm(`确定删除脚本「${row.bound_case || row.name}」？${row.test_set_refs ? `该脚本被 ${row.test_set_refs} 个测试集引用。` : ''}`, '删除确认', { type: 'warning' })
  await request.delete(`/scripts/${row.id}`)
  ElMessage.success('已删除')
  loadScripts()
}
```
4. 翻页：脚本列表加 el-pagination（后端已分页）；列表自动加载改 onMounted（读路由 query.caseId 时过滤 `case_id=` 参数高亮定位）

- [ ] **Step 2: build 验证 + commit**

Run: `cd frontend && npm run build`

```bash
git add frontend/src/views/AutoUITest.vue
git commit -m "feat(frontend): 脚本库列表用例名显示+枚举中文化+删除+分页 — IA改造T4"
```

---

## Task 5: 前端——测试集 Tab + 测试集详情页（新建）

**Files:**
- Modify: `frontend/src/views/AutoUITest.vue`（测试集 Tab：详情/删除按钮）
- Create: `frontend/src/views/TestSetDetail.vue`
- Modify: `frontend/src/router/index.js`（加路由 `/auto/ui/set/:id`）
- Modify: `frontend/src/api/*.js`（若缺 testSet 封装则补 delete/records/trend）

- [ ] **Step 1: 测试集 Tab 加操作**

操作列：详情（`router.push('/auto/ui/set/' + row.id)`）/ 删除（confirm → `DELETE /test-sets/{id}` → 刷新）。

- [ ] **Step 2: 新建 TestSetDetail.vue（完整组件）**

```vue
<template>
  <div>
    <el-page-header @back="$router.back()" :content="set?.name || '测试集详情'" />
    <!-- 信息卡 -->
    <el-card v-if="set" style="margin-top: 12px">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="名称">{{ set.name }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ SOURCE_CN[set.source] || set.source }}</el-descriptions-item>
        <el-descriptions-item label="用例数">{{ (set.case_ids || []).length }}</el-descriptions-item>
        <el-descriptions-item label="最近通过率">{{ set.last_pass_rate != null ? set.last_pass_rate + '%' : '—' }}</el-descriptions-item>
      </el-descriptions>
      <el-button type="primary" style="margin-top: 12px" @click="runSet">执行测试集</el-button>
    </el-card>
    <!-- 迷你趋势（最近10次通过率） -->
    <el-card v-if="trend.length" style="margin-top: 12px">
      <div class="trend-title">最近 {{ trend.length }} 次通过率</div>
      <div class="trend-bar">
        <div v-for="(t, i) in trend" :key="i" class="trend-col"
             :title="`${t.started_at} ${t.status} ${t.pass_rate}%`">
          <div class="trend-fill" :class="t.status === 'success' ? 'ok' : 'bad'"
               :style="{ height: Math.max(t.pass_rate, 4) + '%' }" />
        </div>
      </div>
    </el-card>
    <el-tabs v-model="tab" style="margin-top: 12px">
      <el-tab-pane label="成员用例" name="cases">
        <el-table :data="caseRows">
          <el-table-column type="index" label="#" width="55" />
          <el-table-column prop="name" label="用例名" min-width="240" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeCase(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="测试记录" name="records">
        <el-radio-group v-model="recordFilter" size="small" @change="loadRecords">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="success">成功</el-radio-button>
          <el-radio-button value="failed">有失败</el-radio-button>
        </el-radio-group>
        <el-table :data="records" style="margin-top: 12px">
          <el-table-column prop="started_at" label="触发时间" width="170" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="recTagType(row)">{{ recCn(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="通过率" min-width="160">
            <template #default="{ row }">
              <el-progress :percentage="Number(row.pass_rate) || 0" :stroke-width="12"
                           :color="row.status === 'success' ? '#67c23a' : '#e6a23c'" />
            </template>
          </el-table-column>
          <el-table-column prop="fail_count" label="失败" width="70" />
          <el-table-column label="未执行" width="90">
            <template #default="{ row }">
              <span v-if="unexecutedCount(row) > 0" style="color:#e6a23c;cursor:pointer"
                    @click="showUnexecReason(row)">{{ unexecutedCount(row) }} 条 ▸</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="viewReport(row)">查看报告</el-button>
              <el-button link @click="rerun(row)">再跑一次</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-model:current-page="recPage" :page-size="recPageSize" :total="recTotal"
                       layout="total, prev, pager, next" @current-change="loadRecords" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
```

实现要点：
- onMounted：`GET /test-sets/{id}`（若现有 API 只有列表无单查，用列表过滤或后端 Task2 补单查端点——**执行时核对**，缺则后端加 `GET /test-sets/{set_id}`）、trend、records、成员用例（按 case_ids 查 test-cases 详情，复用现有批量查法——grep AutoUITest.vue `setCases` 现有实现照搬）
- records 过滤：result=all 直接查；success→`status=success`；failed→`status=fail`+`status=partial`（**核对 ExecutionRecord.status 实际枚举**：grep 模型注释/写入点，部分失败的状态值以实际为准，映射中文）
- unexecutedCount(row)：`row.total_cases - row.passed_count - row.fail_count`（负值归 0）；showUnexecReason 用 ElMessageBox 展示"上次执行因失败策略中断，N 条用例未执行"
- viewReport(row)：跳现有报告详情页（grep AutoUITest.vue 现有查看报告跳转路径照搬）
- rerun(row)：调现有执行 API（同 script_ids/case_ids 配置，带 test_set_id=本集 id）
- runSet：调执行 API 带 test_set_id → 成功后切到"测试记录" Tab 刷新（执行直播仍走现有 AutoUITest 页文字直播区，详情页只展示结果——**简化，不做页内 SSE**）
- SOURCE_CN：`{ manual: '手工', ai_suggest: 'AI建议', convert_page: '页面转换', ai_regression: 'AI识别回归', manual_regression: '手工回归' }`

- [ ] **Step 3: 路由注册**

router/index.js auto/ui 同级加：
```js
{ path: 'auto/ui/set/:id', name: 'TestSetDetail', component: () => import('@/views/TestSetDetail.vue'), meta: { title: '测试集详情' } },
```
（照相邻路由对象结构补 meta/parent——**执行时看 :78-95 上下文对齐嵌套结构**）

- [ ] **Step 4: build + commit**

Run: `cd frontend && npm run build`

```bash
git add frontend/src/views/AutoUITest.vue frontend/src/views/TestSetDetail.vue frontend/src/router/index.js frontend/src/api/
git commit -m "feat(frontend): 测试集Tab操作+测试集详情页(执行/成员用例/测试记录/趋势) — IA改造T5"
```

---

## Task 6: 收尾——全量回归 + 手动验收清单

- [ ] 全量：`cd backend && PYTHONUTF8=1 /d/MoonTest/backend/venv/Scripts/python.exe -m pytest -q -c pytest.ini --rootdir=.`（≥896+新增全绿）
- [ ] build：`cd frontend && npm run build`
- [ ] 重启 backend（8000 无 --reload）+ 前端 dev server
- [ ] 手动验收（对照 spec 第四节 6 条）：
  1. 进转脚本页默认第一个项目，定稿用例列表倒序+翻页
  2. 单条转脚本 → SSE 直播 → 行状态"已转换"+"查看脚本"跳脚本库
  3. 新脚本名=用例名；脚本库绑定用例列有值
  4. 三列表删除（二次确认）+ 中文枚举 + 倒序 + 翻页
  5. 测试集详情页：执行/成员用例/测试记录（通过率/未执行/查看报告/再跑一次/筛选/趋势）
  6. 全量测试绿 + build 绿
- [ ] 存档更新 + memory

## 验收标准（spec 摘录）

见 Task 6 手动验收清单——6 条全过即收官。
