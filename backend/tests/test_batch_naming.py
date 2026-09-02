"""batch_naming 纯函数测试（T1）"""
from datetime import datetime

import pytest

from app.services.batch_naming import build_batch_name, truncate_requirement


class TestBuildBatchName:
    def test_whitescan_api(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("whitescan_api", ts) == "白盒测试生成接口回归用例20260902143025"

    def test_whitescan_ui(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("whitescan_ui", ts) == "白盒测试生成UI回归用例20260902143025"

    def test_ai_generate_truncates_50(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        req = "登" * 60
        name = build_batch_name("ai_generate", ts, requirement=req)
        assert name == "登" * 50 + "生成的用例20260902143025"

    def test_ai_generate_short_req(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("ai_generate", ts, requirement="用户登录") == "用户登录生成的用例20260902143025"

    def test_ai_generate_empty_req_fallback(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("ai_generate", ts, requirement="") == "未命名需求生成的用例20260902143025"

    def test_manual(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("manual", ts) == "手工创建用例20260902143025"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            build_batch_name("bogus", datetime.now())


class TestTruncateRequirement:
    def test_truncate_50(self):
        assert truncate_requirement("a" * 80) == "a" * 50

    def test_none(self):
        assert truncate_requirement(None) == "未命名需求"

    def test_whitespace_only(self):
        assert truncate_requirement("   ") == "未命名需求"
