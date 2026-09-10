"""find_by_name 三级匹配（阶段3验收反馈2：模糊匹配提升元素库命中率）"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from app.services.element_service import ElementService


def _el(name, text=None, confidence=5):
    el = MagicMock()
    el.element_name = name
    el.element_text = text
    el.confidence = confidence
    return el


def _svc(rows):
    db = MagicMock()

    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        r.scalar_one_or_none.return_value = rows[0] if rows else None
        return r
    db.execute = _execute
    return ElementService(db)


class TestFuzzyMatching:
    @pytest.mark.asyncio
    async def test_exact_match_first(self):
        """一级精确命中直接返回"""
        el = _el("账号输入框")
        svc = _svc([el])
        found = await svc.find_by_name("11111111-1111-1111-1111-111111111111", "账号输入框")
        assert found is el

    @pytest.mark.asyncio
    async def test_fuzzy_contains_both_directions(self):
        """二级模糊：target 含元素名（"获取验证码按钮" vs "获取验证码"）"""
        el = _el("获取验证码", text="获取验证码")
        svc = _svc([el])
        found = await svc.find_by_name("11111111-1111-1111-1111-111111111111", "获取验证码按钮")
        assert found is el

    @pytest.mark.asyncio
    async def test_fuzzy_element_name_contains_target(self):
        """元素名含 target（"登录按钮" vs "登录"）"""
        el = _el("登录按钮")
        svc = _svc([el])
        found = await svc.find_by_name("11111111-1111-1111-1111-111111111111", "登录")
        assert found is el

    @pytest.mark.asyncio
    async def test_multi_hit_takes_highest_confidence(self):
        """多命中取 confidence 最高的"""
        low, high = _el("登录", confidence=3), _el("登录2", confidence=9)
        svc = _svc([low, high])
        found = await svc.find_by_name("11111111-1111-1111-1111-111111111111", "登录")
        assert found is high

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        svc = _svc([])
        assert await svc.find_by_name("11111111-1111-1111-1111-111111111111", "完全不存在的东西") is None

    @pytest.mark.asyncio
    async def test_short_keyword_skips_fuzzy(self):
        """单字符关键词不做模糊（误命中面太大）"""
        svc = _svc([])
        # 精确没命中 + 模糊跳过 → None
        assert await svc.find_by_name("11111111-1111-1111-1111-111111111111", "登") is None

    @pytest.mark.asyncio
    async def test_empty_name_returns_none(self):
        svc = _svc([])
        assert await svc.find_by_name("11111111-1111-1111-1111-111111111111", "") is None
