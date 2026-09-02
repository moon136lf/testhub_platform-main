"""batch_naming 纯函数测试（T1 + #case-batch T4 build_script_name）"""
import pytest
from datetime import datetime

from app.services.batch_naming import (
    build_batch_name,
    build_script_name,
    truncate_requirement,
)


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


# --- build_script_name (#case-batch T4) ---

TS = datetime(2026, 9, 2, 12, 30, 45)


def test_with_batch_name():
    assert build_script_name("批次A", "登录用例", TS) == "批次A-自动化脚本123045"


def test_without_batch_name_falls_back_to_title():
    assert build_script_name(None, "登录用例", TS) == "登录用例"


def test_taken_appends_suffix_2():
    name = "批次A-自动化脚本123045"
    assert build_script_name("批次A", "登录", TS, taken={name}) == f"{name}-2"


def test_taken_suffix2_appends_suffix_3():
    name = "批次A-自动化脚本123045"
    assert build_script_name("批次A", "登录", TS,
                             taken={name, f"{name}-2"}) == f"{name}-3"
