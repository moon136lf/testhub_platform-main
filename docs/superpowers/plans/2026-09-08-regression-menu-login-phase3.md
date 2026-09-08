# 阶段3：回归+菜单+登录态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 回归自动化独立页（for_regression 数据源）、白盒用例归入用例管理、菜单重组、评审应用 LLM 增强、登录态复用（storage_state）——重构收官。

**Architecture:** 回归归属用 `for_regression` 标记（script_asset + test_case 加列，白盒生成链路自动置 true）替代 RegressionSet.actual_included 数据源（保留表做 AI 建议缓存）；登录态复用新建 `login_state_service.py`（storage_state 缓存到 test_env 同目录文件 + TTL，test_env.credentials 扩 login 块，script_executor 每用例独立 context 注入）；菜单重组纯前端 MainLayout + 路由。另含阶段2 遗留的 P1 假成功修复（ScriptContentRunner：executor 消费 codegen 产物）。

**Tech Stack:** 同前两阶段；基线 704+ passed（master@496771d）。

**需求依据:** docs/SESSION_HANDOFF_2026-09-04-refactor-plan.md 阶段3 行 + 数据/逻辑设计要点 1/4；假成功项见 docs/SESSION_HANDOFF_2026-09-07-phase1-execution.md 与 PHASE2_PROGRESS.md T8 节。

**前置事实（已核实）:**
- RegressionSet 模型：project_id/script_id/ai_suggested/ai_reason/actual_included/include_source（backend/app/models/regression.py）——现回归页数据源
- whitescan 用例生成走 case_batch_service.create_batch("whitescan_ui"/"whitescan_api")（functional_case_generator.py:40-41）
- script_executor 逐条 step_mapping 执行（SmartLocator 词表 {click,fill,select,check,uncheck}），不执行 codegen 产物；编辑器行用 seq 键被 step 键过滤 → 0 步假通过（阶段2 T8 确认）
- playwright_service 有 _auto_login（表单自动填充）；无 storage_state
- test_env.credentials JSONB 已有（加密敏感字段约定）；环境管理页 EnvManagement.vue 存在
- 菜单现状：AI与用例 8 项混在一起；执行记录与报告独立菜单（/reports）
- 假成功清单 P2：executor 不消费 codegen 产物（编辑器脚本执行 0 步通过）

---

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/migrations/015_regression_flag.sql` | script_asset.for_regression、test_case.source_type（白盒来源标识） |
| `backend/app/services/login_state_service.py` | 新建：storage_state 生成/缓存/TTL/注入 |
| `backend/app/services/script_executor.py` | 修改：登录态注入 + **ScriptContentRunner**（消费 codegen 产物修假成功） |
| `backend/app/services/functional_case_generator.py` | 修改：白盒生成置 for_regression |
| `backend/app/api/v1/regression.py` | 数据源切 for_regression + AI 建议保留 |
| `backend/app/api/v1/test_cases.py` | source_type 透出 + 白盒用例标识 |
| `frontend/src/layouts/MainLayout.vue` | 菜单重组（三组结构） |
| `frontend/src/router/index.js` | 执行记录并入（/reports 路由保留、菜单取消） |
| `frontend/src/views/Regression.vue` | 改造：for_regression 数据源 |
| `frontend/src/views/system/EnvManagement.vue` | 登录配置表单 + 测试登录按钮 |
| `frontend/src/views/reviews/ReviewCenter.vue` | 评审应用 LLM 增强（配合后端） |
| `backend/app/services/case_refiner.py` | 应用建议 LLM 增强（阶段3 清单项） |

---

### Task 0: ScriptContentRunner——修阶段2 遗留假成功（P1，最优先）

**Files:**
- Modify: `backend/app/services/script_executor.py`
- Test: `backend/tests/test_script_content_runner.py`

- [ ] **Step 1: 失败测试**

```python
"""ScriptContentRunner：executor 消费 codegen 产物（修编辑器脚本 0 步假通过）。
mock playwright page；navigate/wait/assert_db 等编辑器动作不经元素库。"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.script_executor import execute_content_steps


@pytest.mark.asyncio
async def test_executes_editor_steps_by_seq_key():
    """编辑器保存的 step_mapping 用 seq 键——不再被 step 过滤为 0 步"""
    asset = MagicMock()
    asset.step_mapping = [
        {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com", "element_name": ""},
        {"seq": 2, "action": "click", "target": "#btn", "value": "", "element_name": "按钮"},
    ]
    page = MagicMock()
    page.goto = AsyncMock()
    page.locator.return_value.click = AsyncMock()

    steps = execute_content_steps(asset.step_mapping)  # 纯函数：解析行式步骤
    assert len(steps) == 2
    assert steps[0]["action"] == "navigate"

@pytest.mark.asyncio
async def test_action_dispatch_table():
    """每类动作的执行分发（click/fill/select/wait/assert_text）"""
    from app.services.script_executor import dispatch_editor_action
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    loc = MagicMock()
    loc.click = AsyncMock(); loc.fill = AsyncMock(); loc.select_option = AsyncMock()
    expect_mock = MagicMock()

    await dispatch_editor_action(page, {"action": "click", "target": "#b", "value": ""}, expect_mock)
    page.locator.assert_called_with("#b")
    await dispatch_editor_action(page, {"action": "input", "target": "#u", "value": "admin"}, expect_mock)
    loc.fill.assert_called_with("admin")
    await dispatch_editor_action(page, {"action": "wait", "target": "", "value": "2"}, expect_mock)
    page.wait_for_timeout.assert_called_with(2000)

@pytest.mark.asyncio
async def test_assert_db_executes_sql():
    """assert_db：跑 SQL 比对 expected（字符串语义）"""
    from app.services.script_executor import dispatch_editor_action
    page = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = "5"

    # 注入 db 执行器
    with patch("app.services.script_executor._run_assert_db_query", new=AsyncMock(return_value="5")):
        result = await dispatch_editor_action(
            page, {"action": "assert_db", "target": "", "value": "SELECT 1", "expected": "5"}, None)
        assert result is None  # 通过无异常

    with patch("app.services.script_executor._run_assert_db_query", new=AsyncMock(return_value="6")):
        with pytest.raises(AssertionError, match="5"):
            await dispatch_editor_action(page, {"action": "assert_db", "target": "", "value": "SELECT 1", "expected": "5"}, None)
```

- [ ] **Step 2: 实现**（script_executor.py 追加；**注意 executor 是 async 而 codegen 生成同步脚本——这里不是 exec 生成的文本，而是直接解释 step_mapping 行**，生成产物仅作展示。此决策写进 docstring）

```python
def _editor_steps(step_mapping):
    """解析编辑器行式步骤（seq 键）与旧步骤（step 键）统一为可执行列表。"""
    steps = [s for s in (step_mapping or []) if isinstance(s, dict)]
    return [s for s in steps if (s.get("step", 0) or s.get("seq", 0))]


async def _run_assert_db_query(sql: str):
    """assert_db 的 DB 查询执行（独立 DB 会话，读-only）。"""
    from sqlalchemy import text as _text
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(_text(sql))
        row = result.scalar()
        return str(row) if row is not None else ""


async def dispatch_editor_action(page, step, expect_mod, db_query=None):
    """执行单条编辑器动作。返回 None=通过；抛 AssertionError=断言失败。"""
    action = step.get("action", "")
    target = step.get("target", "")
    value = step.get("value", "")

    if action == "navigate":
        await page.goto(value)
        return None
    if action == "click":
        await page.locator(target).click()
        return None
    if action == "input":
        await page.locator(target).fill(value)
        return None
    if action == "select":
        await page.locator(target).select_option(value)
        return None
    if action == "wait":
        try:
            ms = int(float(value or 1) * 1000)
        except (ValueError, TypeError):
            ms = 1000
        await page.wait_for_timeout(ms)
        return None
    if action == "assert_text":
        await expect_mod(page.locator(target)).to_have_text(value)
        return None
    if action == "assert_visible":
        await expect_mod(page.locator(target)).to_be_visible()
        return None
    if action == "assert_db":
        query = db_query or _run_assert_db_query
        actual = await query(value)
        if actual != str(step.get("expected", "")):
            raise AssertionError(
                f"DB断言失败: SQL「{value[:60]}」期望 {step.get('expected')} 实际 {actual}")
        return None
    raise ValueError(f"不支持的操作类型: {action}")
```

**执行集成**：在 ScriptExecutor.execute 的步骤循环入口分支——`if step_mapping 行含 seq 键（编辑器格式）→ 走 dispatch_editor_action 逐条执行（不需要元素库查找，target 即定位符）；else 走原 SmartLocator 链路`。expect_mod 用 `from playwright.sync_api import expect` 的 async 对应（executor 是 async playwright——实现者确认 async API 的 expect 导入路径）。

- [ ] **Step 3: 测试过 + 全量回归 + Commit** `fix(executor): consume editor steps by seq — kill 0-step false pass; assert_db DB query`

---

### Task 1: 回归归属标记（for_regression）

**Files:**
- Create: `backend/migrations/015_regression_flag.sql`
- Modify: `backend/app/models/test_case.py`（ScriptAsset 加列）
- Modify: `backend/app/services/functional_case_generator.py`（白盒生成置 true）
- Test: `backend/tests/test_regression_flag.py`

- [ ] **Step 1: 迁移**

```sql
-- Migration: for_regression flag (phase3 regression ownership)
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS for_regression BOOLEAN DEFAULT FALSE;
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) DEFAULT 'ai_gen';
COMMENT ON COLUMN test_case.source_type IS 'ai_gen/whitescan/manual——白盒生成=whitescan（归回归集）';
```

- [ ] **Step 2: 失败测试**

```python
"""for_regression 归属标记：白盒用例自动归回归集"""
def test_script_asset_has_flag():
    from app.models.test_case import ScriptAsset
    assert hasattr(ScriptAsset(), "for_regression")

def test_test_case_has_source_type():
    from app.models.test_case import TestCase
    assert hasattr(TestCase(), "source_type")

@pytest.mark.asyncio
async def test_whitescan_generation_marks_for_regression():
    """白盒功能用例生成 → 产出的 script/case 带 for_regression=True / source_type=whitescan"""
    # mock batch_import/create 流程，断言 whitescan 链路传入标记（实现者按 functional_case_generator 实际结构 patch）
```

- [ ] **Step 3: 实现**（模型加列 + to_dict + functional_case_generator 的 whitescan 分支置 `for_regression=True` / `source_type="whitescan"` + create 分支默认 False/ai_gen）
- [ ] **Step 4: 测试过 + 执行迁移 + Commit** `feat(regression): for_regression flag — whitescan cases auto-tagged`

---

### Task 2: 回归页数据源切换

**Files:**
- Modify: `backend/app/api/v1/regression.py` + `backend/app/services/regression_service.py`
- Test: `backend/tests/test_regression_service.py`（追加）

- [ ] **Step 1: 失败测试**：`list_view` 数据源改为 `script_asset.for_regression == True`（RegressionSet 保留仅作 AI 建议缓存，list 主数据源不再依赖 actual_included）；AI 识别按钮逻辑不变（写 RegressionSet 建议 + 同步置 for_regression）
- [ ] **Step 2: 实现**（最小侵入：list_view 查询改为 for_regression；identify 保持；加入/移出回归集 = 置/清 for_regression + RegressionSet 同步）
- [ ] **Step 3: 测试过 + Commit** `feat(regression): data source switches to for_regression flag`

---

### Task 3: 白盒用例归入用例管理

**Files:**
- Modify: `backend/app/api/v1/test_cases.py`（list 增加 source_type 过滤参数 + 透出）
- Modify: `backend/app/api/v1/ai_case_generation.py`（如列表端点共用则同步）
- Test: 追加 source_type 过滤测试

- [ ] **Step 1: 失败测试**：`GET /test-cases/?source_type=whitescan` 只返回白盒用例；列表响应含 source_type 字段
- [ ] **Step 2: 实现**（to_dict/CaseResponse 加 source_type；list 端点加过滤参数）
- [ ] **Step 3: 测试过 + Commit** `feat(cases): source_type surfaced + whitescan filter`

---

### Task 4: 登录态复用（storage_state）

**Files:**
- Create: `backend/app/services/login_state_service.py`
- Modify: `backend/app/models/system.py`（TestEnv 无需改列——credentials JSONB 扩 login 块）
- Modify: `backend/app/services/script_executor.py`（执行前注入 storage_state）
- Modify: `backend/app/api/v1/system.py`（登录配置保存 + 测试登录端点）
- Test: `backend/tests/test_login_state_service.py`

- [ ] **Step 1: 失败测试**

```python
"""登录态复用：storage_state 生成/缓存/TTL/失效重登"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.login_state_service import LoginStateService

LOGIN_CFG = {
    "login_url": "/login",
    "username_selector": "input[name=u]", "username": "admin",
    "password_selector": "input[name=p]", "password": "pass",
    "submit_selector": "button[type=submit]",
    "success_check": "dashboard",
    "state_ttl_minutes": 120,
}


class TestLoginState:
    @pytest.mark.asyncio
    async def test_generate_state_via_login_flow(self):
        """首次：走登录流程 → 返回 storage_state"""
        page = MagicMock()
        page.goto = AsyncMock()
        page.locator.return_value.fill = AsyncMock()
        page.locator.return_value.click = AsyncMock()
        page.content = AsyncMock(return_value="<html>dashboard</html>")
        page.context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})

        svc = LoginStateService()
        state = await svc.ensure_state("env1", LOGIN_CFG, page)
        assert "cookies" in state
        page.goto.assert_called()  # 访问了登录页

    @pytest.mark.asyncio
    async def test_cache_hit_within_ttl(self):
        """TTL 内二次调用命中缓存不重登"""
        svc = LoginStateService()
        svc._cache["env1"] = {"state": {"cookies": [1]}, "ts": __import__("time").time(), "ttl": 120}
        state = await svc.ensure_state("env1", LOGIN_CFG, MagicMock())
        assert state == {"cookies": [1]}

    @pytest.mark.asyncio
    async def test_expired_relogins(self):
        """过期 → 重新登录"""
        import time
        svc = LoginStateService()
        svc._cache["env1"] = {"state": {"cookies": [1]}, "ts": time.time() - 3600, "ttl": 120}
        page = MagicMock()
        page.goto = AsyncMock()
        page.locator.return_value.fill = AsyncMock()
        page.locator.return_value.click = AsyncMock()
        page.content = AsyncMock(return_value="<html>dashboard</html>")
        page.context.storage_state = AsyncMock(return_value={"cookies": [2]})
        state = await svc.ensure_state("env1", LOGIN_CFG, page)
        assert state == {"cookies": [2]}

    @pytest.mark.asyncio
    async def test_invalidate(self):
        svc = LoginStateService()
        svc._cache["env1"] = {"state": {}, "ts": 0, "ttl": 1}
        await svc.invalidate("env1")
        assert "env1" not in svc._cache
```

- [ ] **Step 2: 实现**（LoginStateService：_cache dict 按 env_id；ensure_state 检查 TTL → 未命中走登录流程（goto login_url → fill username/password → click submit → 等 success_check 出现在 URL/content → storage_state）；invalidate；**执行失败跳登录页的自动刷新**在 script_executor 集成：失败且当前 URL 含 login → invalidate + 重新 ensure + 重试一次）

- [ ] **Step 3: 环境管理 API**：`PUT /system/envs/{id}/login-config`（写 credentials["login"]）+ `POST /system/envs/{id}/test-login`（真跑一次登录返回成功/失败）
- [ ] **Step 4: 测试过 + Commit** `feat(auth): storage_state login state reuse — cache/TTL/auto-relogin`

---

### Task 5: 菜单重组

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/router/index.js`（/reports 保留路由，AI生成页并入规则/历史 Tab 为**阶段3.5 可选**——本轮只做菜单分组）

- [ ] **Step 1: 菜单改三组结构**（照定稿表）：

```html
<!-- 仪表盘/项目管理 不动 -->
<el-sub-menu index="case-assets">
  <template #title><el-icon><Document /></el-icon><span>用例资产</span></template>
  <el-menu-item index="/cases">用例管理</el-menu-item>
  <el-menu-item index="/reviews">用例评审与精修</el-menu-item>
  <el-menu-item index="/ai/generate">AI智能用例生成</el-menu-item>
  <el-menu-item index="/ai/knowledge">知识库管理</el-menu-item>
</el-sub-menu>
<!-- 元素资产 不动（已是二级） -->
<el-sub-menu index="automation">
  <template #title><el-icon><VideoCameraFilled /></el-icon><span>自动化</span></template>
  <el-menu-item index="/ai/convert">用例转自动化脚本</el-menu-item>
  <el-menu-item index="/auto/ui">UI自动化测试</el-menu-item>
  <el-menu-item index="/auto/regression">回归自动化</el-menu-item>
</el-sub-menu>
<!-- 白盒测试 单独（从 quality 组拆出）；质量与报告组取消，/reports 路由保留菜单去掉 -->
```

- [ ] **Step 2: build + 手动核对中国菜单项路由全通**
- [ ] **Step 3: Commit** `feat(ui): menu regroup — case-assets/element-assets/automation per refactor plan`

---

### Task 6: 评审应用 LLM 增强

**Files:**
- Modify: `backend/app/services/case_refiner.py`（apply 时对「断言增强/步骤完整性」类建议走 LLM 改写）
- Modify: `backend/app/services/test_case_service.py`（apply_suggestions 分流：结构类自动落地（已有）+ 改写类走 LLM）
- Test: `backend/tests/test_case_refiner.py`（追加）

- [ ] **Step 1: 失败测试**：应用「软断言转硬断言」建议 → LLM 收到原步骤 → 返回改写后步骤 → case.steps 更新（mock gateway）
- [ ] **Step 2: 实现**：apply_suggestions 对 dimension=断言增强 且 status pending 的建议调 `_llm_rewrite_steps(case, suggestions)`（gateway.chat，失败降级为仅标记 applied 不改写——不阻塞）
- [ ] **Step 3: 测试过 + Commit** `feat(review): LLM rewrite on apply — soft-assert suggestions actually land`

---

### Task 7: 收官验收

- [ ] **Step 1: 全量测试**（≥715 passed 预期）
- [ ] **Step 2: 前端 build**
- [ ] **Step 3: 真浏览器验收清单**（用户亲自）：
  1. 菜单三组结构；/reports 无菜单但直链可访问
  2. 回归自动化页：白盒生成的用例转脚本后自动出现在回归集；AI 识别按钮可用
  3. 用例管理：白盒用例有来源标识
  4. 环境管理：配登录配置 → 测试登录按钮 → 执行脚本免登录（storage_state 生效）
  5. 编辑器保存的脚本执行真实跑步骤（假通过修复验证）
  6. 评审应用建议 → 步骤实际变化
- [ ] **Step 3: 收官存档**

---

## Self-Review 结果

- **Spec 覆盖**：回归独立（T1/T2）+ 白盒归入用例管理（T1/T3）+ 菜单重组（T5）+ 登录态复用（T4）+ 评审 LLM 增强（T6）+ **假成功修复（T0，阶段2 遗留最优先）**——定稿阶段3 范围全覆盖。执行记录与报告并入各页 = 菜单取消 + /auto/ui 报告 Tab 已在阶段2 就位（回归页报告已有 report-summary），无额外工作。
- **类型一致性**：dispatch_editor_action/_editor_steps（T0）；for_regression/source_type（T1 定义 T2/T3 消费）；LoginStateService.ensure_state/invalidate（T4）。
- **风险已标注**：① T0 executor 分支的 async expect 导入需实现者确认；② T4 登录流程对目标站选择器鲁棒性（success_check 判定）——测试登录按钮（Task 4 Step 3）让用户能自查；③ T2 RegressionSet 表保留做 AI 建议缓存，不物理删。
