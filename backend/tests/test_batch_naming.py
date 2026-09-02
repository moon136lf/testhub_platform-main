# backend/tests/test_batch_naming.py
"""build_script_name 纯函数测试 (#case-batch T4)。"""
from datetime import datetime
from app.services.batch_naming import build_script_name

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
