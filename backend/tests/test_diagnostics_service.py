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
