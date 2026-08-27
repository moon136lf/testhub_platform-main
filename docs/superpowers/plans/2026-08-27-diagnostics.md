# AI 诊断（#5c）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 执行失败后一键 AI 诊断（execution_id 自动取数 + kimi2.6 多模态看截图）→ 诊断卡 → 应用修复回写元素库 → 重跑验证。

**Architecture:** 新建 DiagnosticsService（取数/打包/LLM/清洗）+ /diagnostics/analyze、/apply 两端点；ScriptAsset.ai_diagnosis 数组化（rule/multimodal 卡 append 共存）；前端 DiagnosisCard 组件接入报告页与转脚本页。无新表、无新 Redis 键。

**Tech Stack:** FastAPI + SQLAlchemy async + Pydantic；LLM 走 AIGateway（provider="moonshot" kimi2.6 多模态，#5b 已建）；前端 Vue3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-08-27-diagnostics-design.md`（偏差表 A-I 以 spec 为准）

**关键复用（不要重写）：**
- `SelfHealEngine._clean_llm_locator(raw)` — `backend/app/services/self_heal_engine.py:238`（classmethod，直接 import 调用）
- `SelfHealEngine._screenshot_to_b64(bytes)` — 同文件 :265（staticmethod）
- `ElementService.find_by_name(project_id, element_name)` — `backend/app/services/element_service.py:21`
- `AIGateway.chat(messages, provider=..., project_id=..., stage=...)` — project_id 传了才落 ai_call_log（`ai_gateway.py:365`），stage="diagnosis"
- `storage_client.get_object_bytes(object_name)` — 同步方法，screenshot_url 即 object_name（#5a 存的是 `fail_step{N}.png` 这种裸名）

**测试约定：** 全 mock（FakeDB/FakeSSE 风格参考 `tests/test_script_executor.py`）；`asyncio_run(coro)` helper 包 `asyncio.run`；pytest.ini 是 asyncio_mode=strict，service 层测试用同步 def + asyncio_run。

---

### Task 1: ai_diagnosis 数组化 — 模型层 helper + #4 写入处兼容

**Files:**
- Modify: `backend/app/models/test_case.py:128` 附近（ScriptAsset 加 property）
- Modify: `backend/app/api/v1/scripts.py:230-237`（#4 diagnose 写入处）
- Test: `backend/tests/test_diagnostics_service.py`（新建）

- [ ] **Step 1: 写失败测试（helper + #4 写入兼容）**

```python
"""Diagnostics (#5c) service tests (mock db/gateway/storage)."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock


def asyncio_run(coro): return asyncio.run(coro)


class TestAiDiagnosisList:
    def test_dict_wrapped_to_array(self):
        """#4 旧格式（单对象 dict）读取 → 包装为单元素数组不崩."""
        from app.models.test_case import ScriptAsset
        sa = ScriptAsset(id="s1", case_id="c1", project_id="p1", name="x",
                         content="code", version=1, status="confirmed",
                         ai_diagnosis={"mode": "rule", "category": "script_problem"})
        assert sa.diagnosis_list == [{"mode": "rule", "category": "script_problem"}]

    def test_list_passthrough_and_none(self):
        from app.models.test_case import ScriptAsset
        sa = ScriptAsset(id="s1", case_id="c1", project_id="p1", name="x",
                         content="code", version=1, status="confirmed",
                         ai_diagnosis=[{"mode": "rule"}, {"mode": "multimodal"}])
        assert len(sa.diagnosis_list) == 2
        sa2 = ScriptAsset(id="s2", case_id="c1", project_id="p1", name="y",
                          content="code", version=1, status="confirmed",
                          ai_diagnosis=None)
        assert sa2.diagnosis_list == []

    def test_append_diagnosis_card(self):
        """append 统一入口: 规则卡补 mode+created_at, 数组化存回."""
        from app.models.test_case import ScriptAsset
        sa = ScriptAsset(id="s1", case_id="c1", project_id="p1", name="x",
                         content="code", version=1, status="confirmed",
                         ai_diagnosis={"category": "page_bug"})  # 旧 dict
        card = {"category": "script_problem", "diagnosis": "定位器失效"}
        sa.append_diagnosis(card, mode="multimodal")
        assert len(sa.ai_diagnosis) == 2
        assert sa.ai_diagnosis[0]["mode"] == "rule"  # 旧 dict 被补 mode
        assert sa.ai_diagnosis[1]["mode"] == "multimodal"
        assert "created_at" in sa.ai_diagnosis[1]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q`
Expected: FAIL — `AttributeError: 'ScriptAsset' object has no attribute 'diagnosis_list'`

- [ ] **Step 3: 实现模型层 helper**

在 `backend/app/models/test_case.py` 的 ScriptAsset 类内（`ai_diagnosis` 字段定义之后、`to_dict` 之前）加：

```python
    @property
    def diagnosis_list(self) -> list:
        """诊断卡数组视图 (#5c): 兼容 #4 旧单对象 dict 格式."""
        if not self.ai_diagnosis:
            return []
        if isinstance(self.ai_diagnosis, dict):
            return [self.ai_diagnosis]
        return self.ai_diagnosis

    def append_diagnosis(self, card: dict, mode: str) -> None:
        """append 诊断卡 (rule/multimodal), 补 mode + created_at, 保留历史."""
        from datetime import datetime as _dt
        card = dict(card)
        card.setdefault("mode", mode)
        card.setdefault("created_at", _dt.utcnow().isoformat())
        existing = self.diagnosis_list
        # 旧 dict 卡若无 mode, 视为 #4 rule 卡
        for c in existing:
            if isinstance(c, dict) and "mode" not in c:
                c["mode"] = "rule"
        existing.append(card)
        self.ai_diagnosis = existing
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 改 #4 写入处（scripts.py:230-237）**

把：
```python
    revised_script = None
    if card.get("can_fix") and card.get("revised_step"):
        revised_script = (asset.content or "") + "\n# --- 修复步骤 {} ---\n".format(
            request.failed_step) + card["revised_step"]
        asset.content = revised_script
        asset.ai_diagnosis = card
        asset.version = (asset.version or 1) + 1
        await db.commit()
    return {"code": 0, "data": {"diagnosis_card": card, "revised_script": revised_script}}
```
改为：
```python
    revised_script = None
    if card.get("can_fix") and card.get("revised_step"):
        revised_script = (asset.content or "") + "\n# --- 修复步骤 {} ---\n".format(
            request.failed_step) + card["revised_step"]
        asset.content = revised_script
        asset.append_diagnosis(card, mode="rule")  # #5c: 数组化, 保留历史
        asset.version = (asset.version or 1) + 1
        await db.commit()
    return {"code": 0, "data": {"diagnosis_card": card, "revised_script": revised_script}}
```

- [ ] **Step 6: 全量回归（含 #4 既有测试）**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全部 PASS（#4 diagnose 测试若断言 `ai_diagnosis == card` 需同步改为 `ai_diagnosis == [card]` 或用 diagnosis_list 断言——先跑再看）

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/test_case.py backend/app/api/v1/scripts.py backend/tests/test_diagnostics_service.py backend/tests/test_scripts_api.py
git commit -m "feat(diagnostics): ai_diagnosis array-ized with #4 compat (#5c T1)"
```

---

### Task 2: DiagnosticsService.analyze — 取数 + 打包 + LLM + 卡解析

**Files:**
- Create: `backend/app/services/diagnostics_service.py`
- Test: `backend/tests/test_diagnostics_service.py`（追加）

- [ ] **Step 1: 写失败测试（取数 + script_fragment 拼装）**

追加到 `tests/test_diagnostics_service.py`：

```python
from unittest.mock import patch

from app.services.diagnostics_service import DiagnosticsService


class FakeDB:
    def __init__(self, results):
        self._results = results  # 顺序弹出
        self.added = []

    async def execute(self, q):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(side_effect=self._pop)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(side_effect=self._pop)))
        return r

    def _pop(self):
        return self._results.pop(0) if self._results else None

    async def flush(self): pass
    async def commit(self): pass


def _make_detail(**kw):
    from app.models.execution import ExecutionDetail
    base = dict(execution_record_id="er1", script_id="s1", step=3, action="click",
                status="fail", error_type="locate_failed", error_msg="Element not found: #login-btn",
                stack_trace="Traceback...", screenshot_url="fail_step3.png",
                dom_snapshot="<html><button id='new-login-btn'>登录</button></html>",
                heal_status="failed", heal_log=[])
    base.update(kw)
    return ExecutionDetail(**base)


def _make_asset(**kw):
    from app.models.test_case import ScriptAsset
    base = dict(id="s1", case_id="c1", project_id="p1", name="登录脚本",
                content="await page.click('#login-btn')", version=1, status="confirmed",
                step_mapping=[{"step": 3, "case_req": "点击登录", "impl": "#login-btn",
                               "status": "blocked", "element_name": "登录按钮",
                               "page_name": "LoginPage", "action": "click", "value": ""}])
    base.update(kw)
    return ScriptAsset(**base)


class TestAnalyzeFetch:
    def test_analyze_happy_path(self):
        """execution_id+step 取数 → 拼 fragment → LLM → 卡 append + 契约字段齐."""
        detail = _make_detail()
        asset = _make_asset()
        db = FakeDB([detail, asset])  # 查 detail → 查 asset
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={
            "content": '{"diagnosis": "定位器失效, ID 已变更为 new-login-btn", '
                       '"suggestion": "更新定位器为 #new-login-btn", '
                       '"new_locator": "#new-login-btn", "confidence": 0.92}',
            "tokens": 350,
        })
        storage = MagicMock()
        storage.get_object_bytes = MagicMock(return_value=b"fake-png")
        svc = DiagnosticsService(db=db, gateway=gw, storage=storage)
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        # §9.2.5 契约字段
        assert result["diagnosis"] == "定位器失效, ID 已变更为 new-login-btn"
        assert result["suggestion"] == "更新定位器为 #new-login-btn"
        assert result["new_locator"] == "#new-login-btn"
        assert result["confidence"] == 0.92
        assert result["apply_url"] == "/api/v1/diagnostics/apply"
        # LLM 调用参数: moonshot 多模态 + 埋点
        kwargs = gw.chat.call_args.kwargs
        assert kwargs.get("provider") == "moonshot"
        assert kwargs.get("stage") == "diagnosis"
        assert kwargs.get("project_id") == "p1"
        messages = gw.chat.call_args.args[0]
        content = messages[0]["content"]
        assert content[1]["type"] == "image_url"  # 多模态
        # prompt 含四要素
        prompt_text = content[0]["text"]
        assert "locate_failed" in prompt_text
        assert "click" in prompt_text and "#login-btn" in prompt_text  # fragment
        assert "Traceback" in prompt_text
        assert "<html>" in prompt_text
        # 诊断卡 append 到 asset.ai_diagnosis
        assert len(asset.ai_diagnosis) == 1
        assert asset.ai_diagnosis[0]["mode"] == "multimodal"
        assert asset.ai_diagnosis[0]["confidence"] == 0.92

    def test_analyze_no_step_takes_first_fail(self):
        """step=None → 取第一个 fail detail (FakeDB 顺序即查询顺序)."""
        detail = _make_detail()
        asset = _make_asset()
        db = FakeDB([detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": null, "confidence": null}', "tokens": 10})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345"))
        assert result["diagnosis"] == "d"
        assert result["new_locator"] is None

    def test_analyze_detail_not_found(self):
        db = FakeDB([None])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.analyze("exec-missing"))
            assert False, "should raise"
        except ValueError as e:
            assert "失败记录" in str(e) or "not found" in str(e).lower()

    def test_analyze_no_fail_detail(self):
        db = FakeDB([None])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.analyze("exec-x"))
            assert False, "should raise"
        except ValueError:
            pass

    def test_analyze_llm_invalid_json_falls_back(self):
        """LLM 输出非 JSON → 降级纯文本 diagnosis, new_locator/confidence=None."""
        detail = _make_detail()
        asset = _make_asset()
        db = FakeDB([detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "页面按钮 ID 变了，建议改为 #new-login-btn", "tokens": 80})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert "页面按钮" in result["diagnosis"]
        assert result["new_locator"] is None
        assert result["confidence"] is None

    def test_analyze_llm_getby_locator_rejected(self):
        """LLM 违约返回 get_by_* 表达式 → 清洗拒绝 → new_locator=None (防幻觉)."""
        detail = _make_detail()
        asset = _make_asset()
        db = FakeDB([detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={
            "content": '{"diagnosis": "d", "suggestion": "s", '
                       '"new_locator": "page.get_by_role(\\"button\\", name=\\"登录\\")", "confidence": 0.8}',
            "tokens": 100,
        })
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert result["new_locator"] is None
        assert "无效" in result["suggestion"] or "手动" in result["suggestion"]

    def test_analyze_screenshot_missing_degrades(self):
        """截图文件读取失败 → 无图纯文本诊断（不崩）."""
        detail = _make_detail()
        asset = _make_asset()
        db = FakeDB([detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": "#x", "confidence": 0.7}', "tokens": 60})
        storage = MagicMock()
        storage.get_object_bytes = MagicMock(side_effect=Exception("object missing"))
        svc = DiagnosticsService(db=db, gateway=gw, storage=storage)
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert result["new_locator"] == "#x"
        # messages 无 image_url (纯文本)
        messages = gw.chat.call_args.args[0]
        assert messages[0]["content"][0]["type"] == "text"
        assert len(messages[0]["content"]) == 1

    def test_analyze_no_step_mapping_fragment_falls_back_to_content(self):
        """无 step_mapping → script_fragment 降级为整段脚本."""
        detail = _make_detail()
        asset = _make_asset(step_mapping=None)
        db = FakeDB([detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": null, "confidence": null}', "tokens": 10})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        asyncio_run(svc.analyze("exec-abc12345", step=3))
        prompt_text = gw.chat.call_args.args[0][0]["content"][0]["text"]
        assert "await page.click" in prompt_text  # 整段脚本
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q -k Analyze`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.diagnostics_service'`

- [ ] **Step 3: 实现 DiagnosticsService.analyze**

新建 `backend/app/services/diagnostics_service.py`：

```python
"""页面级 AI 诊断 (#5c): execution_id 取数 → 打包(TRANS-05) → 多模态 LLM → 诊断卡.

与 #4 ScriptDiagnoseService 并存: #4 是脚本级手动诊断(手填/四分类/重生成),
#5c 是页面级自动诊断(execution_id 取数/kimi2.6 看截图/new_locator).
诊断卡 append 到 ScriptAsset.ai_diagnosis (mode 区分, 见 spec §2.1).
"""
import json
import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionDetail, ExecutionRecord
from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)

# 诊断 LLM 路线1: 硬编码 moonshot (kimi2.6 多模态, 同 #5b Level4); scope 配模型归 #10
DIAGNOSIS_PROVIDER = "moonshot"


class DiagnosticsService:
    def __init__(self, db: AsyncSession, gateway, storage):
        self.db = db
        self.gateway = gateway
        self.storage = storage

    async def analyze(self, exec_id: str, step: Optional[int] = None,
                      override: Optional[dict] = None) -> dict:
        """TRANS-05: 截图+DOM+堆栈+script_fragment 打包发 AI.

        入参 exec_id 是 ExecutionRecord.exec_id (unique, 前端从 session_id 拼
        exec-{session_id[:8]}, 与 /reports 同款标识).
        """
        detail = await self._get_fail_detail(exec_id, step)
        if not detail:
            raise ValueError(f"未找到失败记录: exec_id={exec_id}, step={step}")

        asset = None
        if detail.script_id:
            r = await self.db.execute(
                select(ScriptAsset).where(ScriptAsset.id == detail.script_id))
            asset = r.scalar_one_or_none()

        project_id = str(asset.project_id) if asset and asset.project_id else None

        # -- 打包四要素 (override 可覆盖) --
        error_type = detail.error_type or "script_error"
        error_msg = detail.error_msg or ""
        dom_snapshot = (detail.dom_snapshot or "")[:20000]  # 防 token 爆
        stack_trace = (detail.stack_trace or "")[:3000]
        script_fragment = self._build_fragment(asset, detail.step, detail.action)
        if override:
            error_type = override.get("error_type", error_type)
            error_msg = override.get("error_msg", error_msg)
            dom_snapshot = override.get("dom_snapshot", dom_snapshot)
            script_fragment = override.get("script_fragment", script_fragment)

        # 截图: storage 读 → base64 (复用 #5b 压缩); 失败降级无图
        img_b64 = self._load_screenshot_b64(detail.screenshot_url)

        # -- LLM 调用 --
        card = await self._call_llm(
            error_type=error_type, error_msg=error_msg, step=detail.step,
            action=detail.action, script_fragment=script_fragment,
            dom_snapshot=dom_snapshot, stack_trace=stack_trace, img_b64=img_b64,
            project_id=project_id,
        )

        # -- 落库: append 诊断卡 (数组化, mode=multimodal) --
        if asset is not None:
            asset.append_diagnosis(card, mode="multimodal")
            await self.db.flush()

        # -- 响应体 (§9.2.5 契约) --
        return {
            "diagnosis": card.get("diagnosis"),
            "suggestion": card.get("suggestion"),
            "new_locator": card.get("new_locator"),
            "confidence": card.get("confidence"),
            "apply_url": "/api/v1/diagnostics/apply",
            "card": card,
        }

    async def _get_fail_detail(self, exec_id: str, step: Optional[int]) -> Optional[ExecutionDetail]:
        r = await self.db.execute(
            select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id))
        rec = r.scalar_one_or_none()
        if not rec:
            return None
        q = select(ExecutionDetail).where(
            ExecutionDetail.execution_record_id == rec.id,
            ExecutionDetail.status == "fail")
        if step is not None:
            q = q.where(ExecutionDetail.step == step)
        q = q.order_by(ExecutionDetail.step).limit(1)
        r = await self.db.execute(q)
        return r.scalar_one_or_none()

    def _build_fragment(self, asset: Optional[ScriptAsset], step: Optional[int],
                        action: Optional[str]) -> str:
        """step_mapping[step] 拼 "{action} {impl} {value}"; 无则降级整段脚本."""
        if asset is None:
            return ""
        mapping = asset.step_mapping or []
        sm = next((m for m in mapping if m.get("step") == step), None)
        if sm:
            parts = [sm.get("action") or action or "", sm.get("impl") or "",
                     str(sm.get("value") or "")]
            return " ".join(p for p in parts if p).strip()
        return asset.content or ""

    def _load_screenshot_b64(self, screenshot_url: Optional[str]) -> Optional[str]:
        if not screenshot_url or self.storage is None:
            return None
        try:
            from app.services.self_heal_engine import SelfHealEngine
            raw = self.storage.get_object_bytes(screenshot_url)
            if not raw:
                return None
            return SelfHealEngine._screenshot_to_b64(raw)
        except Exception as e:
            logger.warning(f"diagnosis screenshot load failed: {e}")
            return None

    async def _call_llm(self, *, error_type: str, error_msg: str, step: Optional[int],
                        action: Optional[str], script_fragment: str,
                        dom_snapshot: str, stack_trace: str,
                        img_b64: Optional[str], project_id: Optional[str]) -> dict:
        prompt = f"""你是 UI 自动化测试诊断专家。脚本执行失败信息如下，请分析根因并给出修复建议。

失败步骤: 第 {step} 步 ({action or "unknown"})
错误类型: {error_type}
错误信息: {error_msg}
脚本片段: {script_fragment}
错误堆栈:
{stack_trace}

页面 DOM (截断):
{dom_snapshot}

请只输出一个 JSON 对象（不要 markdown 代码块，不要解释）：
{{"diagnosis": "根因分析，一句话", "suggestion": "修复建议，一句话", "new_locator": "若错误类型是 locate_failed 给出修复后的 Playwright 选择器字符串（如 #new-login-btn 或 text=\\"登录\\" 或 [aria-label=\\"登录\\"]，禁止 page.get_by_role(...) 等 Python API 表达式），否则 null", "confidence": 0到1之间的小数表示把握}}"""

        content_parts = [{"type": "text", "text": prompt}]
        if img_b64:
            content_parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
        messages = [{"role": "user", "content": content_parts}]

        resp = await self.gateway.chat(
            messages, provider=DIAGNOSIS_PROVIDER,
            project_id=project_id, stage="diagnosis",
        )
        raw = resp.get("content") or ""
        card = self._parse_llm_card(raw, step=step, action=action,
                                    error_type=error_type, error_msg=error_msg)
        return card

    def _parse_llm_card(self, raw: str, *, step, action, error_type, error_msg) -> dict:
        """解析 LLM 输出 → 诊断卡. 非法 JSON 降级纯文本; new_locator 清洗防幻觉."""
        card: Dict[str, Any] = {
            "step": step, "action": action,
            "error_type": error_type, "error_msg": (error_msg or "")[:500],
        }
        data = None
        # 去 markdown 围栏再试
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                data = None
        if isinstance(data, dict):
            card["diagnosis"] = str(data.get("diagnosis") or "").strip() or "（AI 未给出根因分析）"
            card["suggestion"] = str(data.get("suggestion") or "").strip()
            conf = data.get("confidence")
            card["confidence"] = round(float(conf), 2) if isinstance(conf, (int, float)) else None
            locator = data.get("new_locator")
            cleaned = self._clean_locator(locator)
            if locator and cleaned is None:
                card["new_locator"] = None
                card["suggestion"] = (card["suggestion"] + "；注意：AI 给出的定位器无效，请参考建议手动修改。").strip("；;")
            else:
                card["new_locator"] = cleaned
        else:
            # 非法 JSON: 纯文本降级
            card["diagnosis"] = raw.strip()[:1000] or "（AI 无输出）"
            card["suggestion"] = ""
            card["new_locator"] = None
            card["confidence"] = None
        return card

    @staticmethod
    def _clean_locator(raw) -> Optional[str]:
        if not raw or not isinstance(raw, str):
            return None
        from app.services.self_heal_engine import SelfHealEngine
        return SelfHealEngine._clean_llm_locator(raw.strip())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q`
Expected: PASS（Task 1 的 3 个 + Task 2 的 8 个 = 11 passed；若 FakeDB 的 scalars().all() mock 不匹配实际查询路径，调整 FakeDB 让 `execute` 按 select 目标返回——实现里 `_get_fail_detail` 只用 `scalar_one_or_none`，第二个查询也是 `scalar_one_or_none`，顺序 [detail, asset] 即可）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/diagnostics_service.py backend/tests/test_diagnostics_service.py
git commit -m "feat(diagnostics): DiagnosticsService.analyze — fetch+pack+multimodal LLM (#5c T2)"
```

---

### Task 3: DiagnosticsService.apply — 清洗 + 回写元素库

**Files:**
- Modify: `backend/app/services/diagnostics_service.py`（追加 apply）
- Modify: `backend/app/models/element.py:84`（source 列注释加 ai_fixed）
- Test: `backend/tests/test_diagnostics_service.py`（追加）

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestApply:
    def _element(self):
        from app.models.element import ElementRepository
        return ElementRepository(
            page_id="pg1", project_id="p1", element_id="login-btn",
            element_name="登录按钮", element_type="button",
            locator_strategies={"strategies": [{"type": "css", "value": "#old-btn"}]},
            source="manual", confidence=3)

    def test_apply_writes_element_with_ai_fixed(self):
        """apply: 清洗合法 → find_by_name → 回写 source=ai_fixed + confidence=round(c*10)."""
        el = self._element()
        db = FakeDB([el])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        result = asyncio_run(svc.apply(
            project_id="p1", element_name="登录按钮",
            new_locator="#new-login-btn", confidence=0.92))
        assert result["updated"] is True
        assert result["element_id"] == "login-btn"
        assert result["cleaned_locator"] == "#new-login-btn"
        assert el.source == "ai_fixed"
        assert el.confidence == 9  # round(0.92*10) = 9
        strategies = el.locator_strategies["strategies"]
        assert strategies[0]["value"] == "#new-login-btn"
        db.flush  # flush 被调 (FakeDB 有 flush)

    def test_apply_rejects_getby_expression(self):
        """get_by_* 表达式 → 400 语义 (ValueError), 不写库."""
        el = self._element()
        db = FakeDB([el])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.apply(project_id="p1", element_name="登录按钮",
                                  new_locator='page.get_by_role("button", name="登录")',
                                  confidence=0.9))
            assert False, "should raise"
        except ValueError as e:
            assert "无效" in str(e)

    def test_apply_element_not_found(self):
        db = FakeDB([None])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.apply(project_id="p1", element_name="不存在",
                                  new_locator="#x", confidence=0.9))
            assert False, "should raise"
        except ValueError as e:
            assert "未找到" in str(e)

    def test_apply_confidence_mapping_edge(self):
        """confidence=1.0 → 10; 0.5 → 5."""
        el = self._element()
        db = FakeDB([el])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        asyncio_run(svc.apply(project_id="p1", element_name="登录按钮",
                              new_locator="text=\"登录\"", confidence=1.0))
        assert el.confidence == 10
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q -k Apply`
Expected: FAIL — `AttributeError: 'DiagnosticsService' object has no attribute 'apply'`

- [ ] **Step 3: 实现 apply**

追加到 `diagnostics_service.py` 的 DiagnosticsService 类内：

```python
    async def apply(self, *, project_id: str, element_name: str,
                    new_locator: str, confidence: Optional[float]) -> dict:
        """TRANS-06 偏差版 (spec §1.4-G): new_locator 清洗 → 回写元素库.

        - 清洗拒绝 page.get_by_* 表达式 (#5b 审查教训)
        - source="ai_fixed" (§11.2 枚举扩展, spec 偏差 C)
        - confidence=round(c*10) 直接设值, 不叠加自愈计数器 (spec 偏差 E)
        - 无浏览器上下文, 不做真实命中验证 (spec §1.2 已登记); 靠重跑验证
        """
        from app.services.self_heal_engine import SelfHealEngine
        cleaned = SelfHealEngine._clean_llm_locator((new_locator or "").strip())
        if not cleaned:
            raise ValueError(f"定位器无效（含 page.get_by_* 表达式或格式非法）: {new_locator}")

        from app.services.element_service import ElementService
        svc = ElementService(self.db)
        el = await svc.find_by_name(project_id, element_name)
        if not el:
            raise ValueError(f"元素库未找到: {element_name}")

        # 新策略放首位 (主路径按 score 降序尝试, 新定位器优先用)
        existing = (el.locator_strategies or {}).get("strategies") or []
        new_strategy = {"type": "ai_fixed", "value": cleaned, "score": 100,
                        "unique": True, "verified": False}
        el.locator_strategies = {"strategies": [new_strategy] + existing}
        el.source = "ai_fixed"
        el.confidence = round((confidence or 0) * 10)
        await self.db.flush()
        return {"element_id": el.element_id, "updated": True,
                "cleaned_locator": cleaned}
```

同时把 `backend/app/models/element.py:84` 的列注释改为：

```python
    source = Column(String(20), default="manual", comment="manual/auto/healed/ai_fixed")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q`
Expected: PASS（11 + 4 = 15 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/diagnostics_service.py backend/app/models/element.py backend/tests/test_diagnostics_service.py
git commit -m "feat(diagnostics): apply — clean locator + writeback ai_fixed (#5c T3)"
```

---

### Task 4: API 端点 /diagnostics/analyze + /apply

**Files:**
- Create: `backend/app/api/v1/diagnostics.py`
- Create: `backend/app/schemas/diagnostics.py`
- Modify: `backend/app/api/__init__.py`（router 注册）
- Test: `backend/tests/test_diagnostics_api.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_diagnostics_api.py`：

```python
"""Diagnostics API tests (mock DiagnosticsService)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def asyncio_run(coro): return asyncio.run(coro)


from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


class TestAnalyzeEndpoint:
    def test_analyze_success_contract(self):
        """§9.2.5 契约: 响应含 diagnosis/suggestion/new_locator/confidence/apply_url."""
        from app.api.v1 import diagnostics as diag_mod

        async def fake_analyze(self, exec_id, step=None, override=None):
            return {"diagnosis": "d", "suggestion": "s", "new_locator": "#x",
                    "confidence": 0.9, "apply_url": "/api/v1/diagnostics/apply",
                    "card": {"mode": "multimodal"}}

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-abc12345", "step": 3})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        for k in ("diagnosis", "suggestion", "new_locator", "confidence", "apply_url"):
            assert k in body["data"]

    def test_analyze_detail_missing_404(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_analyze(self, exec_id, step=None, override=None):
            raise ValueError("未找到失败记录: exec_id=x")

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-missing"})
        assert resp.status_code == 404

    def test_analyze_gateway_unavailable_503(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_analyze(self, exec_id, step=None, override=None):
            raise ConnectionError("Provider 'moonshot' not available.")

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-x"})
        assert resp.status_code == 503

    def test_analyze_bad_body_422(self):
        client = _client()
        resp = client.post("/api/v1/diagnostics/analyze", json={})
        assert resp.status_code == 422  # execution_id 必填


class TestApplyEndpoint:
    def test_apply_success(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_apply(self, **kw):
            return {"element_id": "login-btn", "updated": True,
                    "cleaned_locator": "#new-login-btn"}

        with patch.object(diag_mod.DiagnosticsService, "apply", fake_apply):
            client = _client()
            resp = client.post("/api/v1/diagnostics/apply", json={
                "script_id": "0f0e0d0c-0b0a-4948-8276-000000000000",
                "project_id": "1a2b3c4d-5e6f-4948-8276-000000000000",
                "element_name": "登录按钮",
                "new_locator": "#new-login-btn", "confidence": 0.92})
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] is True

    def test_apply_invalid_locator_400(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_apply(self, **kw):
            raise ValueError("定位器无效（含 page.get_by_* 表达式或格式非法）: page.get_by_role(...)")

        with patch.object(diag_mod.DiagnosticsService, "apply", fake_apply):
            client = _client()
            resp = client.post("/api/v1/diagnostics/apply", json={
                "script_id": "0f0e0d0c-0b0a-4948-8276-000000000000",
                "project_id": "1a2b3c4d-5e6f-4948-8276-000000000000",
                "element_name": "登录按钮",
                "new_locator": "page.get_by_role(\"button\")", "confidence": 0.9})
        assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_api.py -q`
Expected: FAIL — 404 Not Found（路由不存在）或 ImportError

- [ ] **Step 3: 实现 schemas + API + 注册**

新建 `backend/app/schemas/diagnostics.py`：

```python
"""Diagnostics (#5c) schemas."""
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class ErrorDataOverride(BaseModel):
    """TRANS-05 可选覆盖 (spec §1.4 入参偏差)."""
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    screenshot_url: Optional[str] = None
    dom_snapshot: Optional[str] = None
    script_fragment: Optional[str] = None


class AnalyzeRequest(BaseModel):
    execution_id: str = Field(..., min_length=1, max_length=50,
                              description="ExecutionRecord.exec_id")
    step: Optional[int] = Field(None, ge=1, description="失败步骤号, 缺省取第一个 fail")
    error_data: Optional[ErrorDataOverride] = None


class ApplyRequest(BaseModel):
    script_id: str = Field(..., description="脚本 ID (诊断卡归属)")
    project_id: str = Field(..., description="项目 ID (元素库查询隔离)")
    element_name: str = Field(..., min_length=1, max_length=100)
    new_locator: str = Field(..., min_length=1, max_length=500)
    confidence: Optional[float] = Field(None, ge=0, le=1)


class DiagResponse(BaseModel):
    code: int = 0
    data: Dict[str, Any]
```

新建 `backend/app/api/v1/diagnostics.py`：

```python
"""AI 诊断 API (#5c) — §9.2.5 /diagnostics/analyze + /apply."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import storage_client
from app.schemas.diagnostics import AnalyzeRequest, ApplyRequest, DiagResponse
from app.services.ai_gateway import AIGateway
from app.services.diagnostics_service import DiagnosticsService

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_svc(db: AsyncSession = Depends(get_db)) -> DiagnosticsService:
    return DiagnosticsService(db=db, gateway=AIGateway(), storage=storage_client)


@router.post("/analyze")
async def analyze(request: AnalyzeRequest,
                  svc: DiagnosticsService = Depends(_get_svc)) -> DiagResponse:
    """TRANS-05: execution_id 自动取数打包发 AI (kimi2.6 多模态)."""
    try:
        data = await svc.analyze(
            request.execution_id, step=request.step,
            override=request.error_data.model_dump() if request.error_data else None,
        )
        return DiagResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        # gateway provider 未配置 (moonshot 无 key)
        raise HTTPException(status_code=503, detail=f"AI 服务不可用: {e}")
    except Exception as e:
        logger.error(f"diagnose analyze failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI 诊断失败: {e}")


@router.post("/apply")
async def apply_fix(request: ApplyRequest,
                    svc: DiagnosticsService = Depends(_get_svc)) -> DiagResponse:
    """TRANS-06: 应用修复 — new_locator 清洗后回写元素库 (source=ai_fixed)."""
    try:
        data = await svc.apply(
            project_id=request.project_id, element_name=request.element_name,
            new_locator=request.new_locator, confidence=request.confidence,
        )
        return DiagResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"diagnose apply failed: {e}")
        raise HTTPException(status_code=502, detail=f"应用修复失败: {e}")
```

注意：`ValueError` 语义分流——analyze 里"未找到失败记录"是 404，apply 里"定位器无效/元素未找到"是 400（上面已分开处理）。

修改 `backend/app/api/__init__.py`：
- 第 7 行 import 加 `diagnostics`：
```python
from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, scripts, system, reports, dashboard, diagnostics
```
- 在 dashboard 注册行后加：
```python
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_api.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 全量回归**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全部 PASS（约 380+）

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/diagnostics.py backend/app/schemas/diagnostics.py backend/app/api/__init__.py backend/tests/test_diagnostics_api.py
git commit -m "feat(diagnostics): /diagnostics/analyze + /apply endpoints (#5c T4)"
```

---

### Task 5: 前端 — diagnostics API + DiagnosisCard 组件

**Files:**
- Create: `frontend/src/api/diagnostics.js`
- Create: `frontend/src/components/DiagnosisCard.vue`

- [ ] **Step 1: API 封装**

新建 `frontend/src/api/diagnostics.js`：

```js
import axios from './axios.js'

const BASE = '/api/v1/diagnostics'

export const diagnosticsAPI = {
  // TRANS-05: execution_id 自动取数诊断
  async analyze(executionId, step = null, errorData = null) {
    const payload = { execution_id: executionId }
    if (step) payload.step = step
    if (errorData) payload.error_data = errorData
    const resp = await axios.post(`${BASE}/analyze`, payload)
    return resp.data
  },
  // TRANS-06: 应用修复 (回写元素库)
  async apply(payload) {
    const resp = await axios.post(`${BASE}/apply`, payload)
    return resp.data
  },
}
```

- [ ] **Step 2: DiagnosisCard 组件**

新建 `frontend/src/components/DiagnosisCard.vue`：

```vue
<template>
  <div class="diagnosis-card">
    <el-descriptions :column="1" border size="small">
      <el-descriptions-item label="模式">
        <el-tag :type="card.mode === 'multimodal' ? 'warning' : 'info'" size="small">
          {{ card.mode === 'multimodal' ? 'AI 多模态' : '规则归因' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="根因">{{ card.diagnosis || card.reason || '—' }}</el-descriptions-item>
      <el-descriptions-item v-if="card.suggestion" label="建议">{{ card.suggestion }}</el-descriptions-item>
      <el-descriptions-item v-if="card.new_locator" label="新定位器">
        <code class="locator">{{ card.new_locator }}</code>
      </el-descriptions-item>
      <el-descriptions-item v-if="card.confidence != null" label="置信度">
        <el-progress :percentage="Math.round(card.confidence * 100)" :stroke-width="14" style="width: 200px" />
      </el-descriptions-item>
    </el-descriptions>
    <div style="margin-top: 12px; text-align: right">
      <slot name="actions" />
      <el-button type="primary" :disabled="!card.new_locator" :loading="applying" @click="$emit('apply', card)">
        应用修复
      </el-button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  card: { type: Object, required: true },
  applying: { type: Boolean, default: false },
})
defineEmits(['apply'])
</script>

<style scoped>
.locator { background: #f5f7fa; padding: 2px 8px; border-radius: 4px; font-family: monospace; }
</style>
```

- [ ] **Step 3: build 验证**

Run: `cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -3`
Expected: `✓ built in Xs`（无编译错误）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/diagnostics.js frontend/src/components/DiagnosisCard.vue
git commit -m "feat(diagnostics): frontend API + DiagnosisCard component (#5c T5)"
```

---

### Task 6: 前端接入 — 报告页 + 转脚本页

**Files:**
- Modify: `frontend/src/views/reports/ReportDetail.vue`（失败明细表加诊断列+弹窗）
- Modify: `frontend/src/views/ScriptConvert.vue`（执行结果失败行诊断）

- [ ] **Step 1: ReportDetail.vue 失败明细加 [AI诊断]**

失败明细 `<el-table>`（约 line 34-56）加操作列（在堆栈列后）：

```html
        <el-table-column label="诊断" width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDiagnose(row)">AI诊断</el-button>
          </template>
        </el-table-column>
```

`</el-card>` 之后加诊断弹窗：

```html
    <el-dialog v-model="diagVisible" title="AI 诊断" width="640px">
      <div v-loading="diagLoading">
        <DiagnosisCard v-if="diagCard" :card="diagCard" :applying="applying"
                       @apply="onApply" />
        <el-empty v-else-if="!diagLoading" description="暂无诊断结果" />
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
        <el-button type="success" :disabled="!diagCard || !diagCard.new_locator" @click="rerunScript">
          重跑验证
        </el-button>
      </template>
    </el-dialog>
```

`<script setup>` 追加（import 区加 `import { diagnosticsAPI } from '@/api/diagnostics.js'` 和 `import DiagnosisCard from '@/components/DiagnosisCard.vue'`；ElMessage 已有）：

```js
// ---- AI 诊断 (#5c) ----
const diagVisible = ref(false)
const diagLoading = ref(false)
const applying = ref(false)
const diagCard = ref(null)
const diagRow = ref(null)

const openDiagnose = async (row) => {
  diagRow.value = row
  diagCard.value = null
  diagVisible.value = true
  diagLoading.value = true
  try {
    const resp = await diagnosticsAPI.analyze(route.params.execId ?? route.query.exec_id ?? detail.value?.record?.exec_id, row.step)
    diagCard.value = resp.data?.card ?? resp.data
    ElMessage.success('诊断完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '诊断失败')
    diagVisible.value = false
  } finally {
    diagLoading.value = false
  }
}

const onApply = async () => {
  if (!diagCard.value?.new_locator || !diagRow.value?.script_id) return
  applying.value = true
  try {
    const projectId = detail.value?.record?.project_id
    const elementName = detail.value?.details?.find(d => d.step === diagRow.value.step)?.element_name
      || diagRow.value.element_name
    await diagnosticsAPI.apply({
      script_id: diagRow.value.script_id,
      project_id: projectId,
      element_name: elementName,
      new_locator: diagCard.value.new_locator,
      confidence: diagCard.value.confidence,
    })
    ElMessage.success('已回写元素库（source=ai_fixed），可重跑验证')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '应用修复失败')
  } finally {
    applying.value = false
  }
}

const rerunScript = () => {
  if (!diagRow.value?.script_id) return
  diagVisible.value = false
  window.open(`/reports`, '_blank')  // 重跑走脚本库页（SCRIPT-03 入口），提示用户
  ElMessage.info('请到脚本库或转脚本页重跑该脚本验证修复效果')
}
```

注意：若 `detail.details` 的行里没有 `element_name`（ExecutionDetail 无此列），apply 的 element_name 需从后端拿——**Task 6a 补丁**：analyze 响应的 card 里带 `element_name`（后端 `_get_fail_detail` 后从 asset.step_mapping 推，加到 card）。本 Task 先按此依赖写，Task 7 落实后端字段。若不想跨 Task 依赖，`openDiagnose` 里 elementName 直接用 `diagCard.value.element_name`（Task 7 加上后即生效）。

- [ ] **Step 2: ScriptConvert.vue 执行结果加诊断**

ScriptConvert.vue 执行结果区（统计卡片下方）加失败明细区（当前无失败行展示——SSE 只有消息流）。最小接入：执行完成后拉失败明细 + 诊断按钮。

在统计卡片区域（约 line 25-32 的 div）后加：

```html
      <div v-if="lastExecFails.length" class="fail-list">
        <div class="fail-title">失败步骤（点击 AI 诊断）</div>
        <div v-for="f in lastExecFails" :key="f.id" class="fail-row">
          <span>第 {{ f.step }} 步 {{ f.action }}：{{ f.error_type }}</span>
          <el-button link type="primary" @click="openExecDiagnose(f)">AI诊断</el-button>
        </div>
      </div>
```

复用 Task 6 Step 1 的诊断弹窗（同一段 dialog 模板 + script 逻辑，elementName 用 `diagCard.value.element_name`）。script 部分追加：

```js
// ---- 执行失败明细 + 诊断 (#5c) ----
import { diagnosticsAPI } from '@/api/diagnostics'
import DiagnosisCard from '@/components/DiagnosisCard.vue'

const lastExecFails = ref([])
const execSessionId = ref(null)

const handleRun = async (row) => {
  runningId.value = row.id
  try {
    const resp = await scriptAPI.run(row.id, { ...runConfig })
    execSessionId.value = resp.data.session_id
    lastExecFails.value = []
    startSSE(resp.data.session_id, {
      onDone: async () => {
        runningId.value = null
        await loadExecFails()
      },
    })
  } catch (e) { ElMessage.error('运行失败'); runningId.value = null }
}

const loadExecFails = async () => {
  if (!execSessionId.value) return
  try {
    const execId = `exec-${execSessionId.value.slice(0, 8)}`
    const resp = await axios.get(`/api/v1/reports/records/${execId}/details?status=fail`)
    lastExecFails.value = resp.data?.data ?? []
  } catch { lastExecFails.value = [] }
}

const openExecDiagnose = (row) => {
  const execId = `exec-${execSessionId.value.slice(0, 8)}`
  openDiagnose({ ...row, execId, project_id: currentProjectId.value })
}
```

其中 `openDiagnose`/`onApply` 与 Step 1 相同逻辑（弹窗 + DiagnosisCard 复用；`openDiagnose` 接受 row 里带 `execId` 时优先用——实现为 `row.execId || 默认`）。`currentProjectId` 用页面已有 `form.projectId`。批量运行 `handleBatchRun` 同样在 onDone 后调 `loadExecFails()`。

- [ ] **Step 3: build 验证**

Run: `cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -3`
Expected: `✓ built in Xs`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/reports/ReportDetail.vue frontend/src/views/ScriptConvert.vue
git commit -m "feat(diagnostics): report page + script convert page diagnosis entries (#5c T6)"
```

---

### Task 7: 后端补 card.element_name + run 响应带 exec_id（spec §8 未决定案）

**Files:**
- Modify: `backend/app/services/diagnostics_service.py`（analyze 卡带 element_name）
- Modify: `backend/app/api/v1/scripts.py`（run/batch-run 响应加 exec_id，前端免拼）
- Test: `backend/tests/test_diagnostics_service.py`（追加 1 测试）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_diagnostics_service.py`：

```python
class TestAnalyzeCardExtras:
    def test_card_carries_element_name(self):
        """apply 需要 element_name — 诊断卡从 step_mapping 推并携带."""
        detail = _make_detail()
        asset = _make_asset()  # step_mapping[step=3].element_name = "登录按钮"
        db = FakeDB([detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": "#x", "confidence": 0.8}', "tokens": 50})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert result["card"]["element_name"] == "登录按钮"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_diagnostics_service.py -q -k Extras`
Expected: FAIL — KeyError: 'element_name'

- [ ] **Step 3: 实现**

`diagnostics_service.py` 的 `_parse_llm_card` 调用处与 `_build_fragment` 统一：在 `analyze` 里取 element_name 并传入卡。改 `_call_llm` 签名加 `element_name`，`_parse_llm_card` 里加：

```python
        card: Dict[str, Any] = {
            "step": step, "action": action, "element_name": element_name,
            "error_type": error_type, "error_msg": (error_msg or "")[:500],
        }
```

`analyze` 里在调用 `_call_llm` 前加：

```python
        element_name = self._infer_element_name(asset, detail.step)
```

方法：

```python
    @staticmethod
    def _infer_element_name(asset: Optional[ScriptAsset], step: Optional[int]) -> Optional[str]:
        if asset is None or step is None:
            return None
        sm = next((m for m in (asset.step_mapping or []) if m.get("step") == step), None)
        return (sm or {}).get("element_name")
```

`scripts.py` run/batch-run 响应 data 加 `exec_id`（两处）：

```python
    return {"code": 0, "message": "Execution started",
            "data": {"session_id": session_id, "exec_id": f"exec-{session_id[:8]}",
                     "sse_url": f"/api/sse/stream/{session_id}"}}
```

batch-run 同款（message 换 "Batch execution started"）。

- [ ] **Step 4: 跑测试 + 全量回归**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全部 PASS

- [ ] **Step 5: 前端切到后端 exec_id（消除拼接 hack）**

`ScriptConvert.vue` 的 `loadExecFails`/`openExecDiagnose` 改用 `resp.data.exec_id`（handleRun/handleBatchRun 里存 `execId.value = resp.data.exec_id`），删 `exec-${...slice(0,8)}` 拼接。

- [ ] **Step 6: build + Commit**

```bash
cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -2
git add backend/app/services/diagnostics_service.py backend/app/api/v1/scripts.py backend/tests/test_diagnostics_service.py frontend/src/views/ScriptConvert.vue
git commit -m "feat(diagnostics): card.element_name + run resp exec_id (#5c T7)"
```

---

### Task 8: 验收核对 + 全量验证

**Files:** 无新文件（验证任务）

- [ ] **Step 1: 全量后端测试**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全部 PASS

- [ ] **Step 2: 前端 build**

Run: `cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -2`
Expected: `✓ built`

- [ ] **Step 3: spec 验收 11 条逐条核对**

对照 `docs/superpowers/specs/2026-08-27-diagnostics-design.md` §7：
1. analyze 收 execution_id 自动取数（T2 测试 test_analyze_happy_path 四要素断言）
2. 多模态 + §9.2.5 契约字段（T2 provider/stage 断言 + T4 test_analyze_success_contract）
3. JSON 解析 + 清洗拒 get_by_*（T2 test_analyze_llm_invalid_json_falls_back / test_analyze_llm_getby_locator_rejected）
4. apply 回写 source=ai_fixed + round(c×10)（T3 test_apply_writes_element_with_ai_fixed）
5. ai_diagnosis 数组化 + #4 兼容（T1 三测试 + T4 API 回归）
6. ai_call_log 埋点 stage=diagnosis（T2 kwargs.project_id/stage 断言——gateway 内部走 W10 log_ai_call，project_id 传了即落）
7. 前端双入口 + 组件复用（T6）
8. 应用→重跑闭环（T6 rerunScript + 脚本库重跑入口）
9. quick-run 不支持（spec §1.2 登记，无代码）
10. 核心服务覆盖 ≥80%（DiagnosticsService 单测覆盖 analyze 全分支 + apply 全分支）
11. KB-AUTO-01/scope 不做（spec §1.2 登记）

- [ ] **Step 4: 派代码审查子代理（requesting-code-review 流程）**

Base: T1 前 HEAD，Head: T7 提交。重点核对 spec 偏差表 A-I 与实现一致性。

- [ ] **Step 5: 审查问题修复 + 最终提交**

```bash
git add -A
git commit -m "fix(diagnostics): review fixes (#5c T8)" # 若有
```
