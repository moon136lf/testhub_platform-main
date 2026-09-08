"""定位器快速校验：单条定位器在真实页面跑一次，返回命中数和评分。
service 层 mock playwright page；真浏览器验证走 Task 10 手动验收。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.element_asset_service import verify_locator_on_page


@pytest.mark.asyncio
async def test_unique_hit_adds_score():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[MagicMock()])  # 命中1个
    result = await verify_locator_on_page(page, {"type": "css", "value": "#btn", "score": 80})
    assert result["hit_count"] == 1
    assert result["score"] == 100  # 80 + 20 唯一加分
    assert result["error"] is None


@pytest.mark.asyncio
async def test_multi_hit_penalizes():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    result = await verify_locator_on_page(page, {"type": "css", "value": ".btn", "score": 80})
    assert result["hit_count"] == 3
    assert result["score"] == 60  # 80 - 20 非唯一扣分


@pytest.mark.asyncio
async def test_no_hit_returns_zero_score():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[])
    result = await verify_locator_on_page(page, {"type": "css", "value": "#gone", "score": 80})
    assert result["hit_count"] == 0
    assert result["score"] == 0


@pytest.mark.asyncio
async def test_selector_error_returns_error():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(side_effect=Exception("bad selector"))
    result = await verify_locator_on_page(page, {"type": "css", "value": "###", "score": 80})
    assert result["hit_count"] == 0
    assert result["error"] is not None


@pytest.mark.asyncio
async def test_xpath_type_prefixes():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[MagicMock()])
    await verify_locator_on_page(page, {"type": "xpath", "value": "//div[1]", "score": 50})
    page.locator.assert_called_with("xpath=//div[1]")


@pytest.mark.asyncio
async def test_zero_baseline_score_unique_hit():
    """无基准分（旧数据/手工定位）唯一命中 → 20 分"""
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[MagicMock()])
    result = await verify_locator_on_page(page, {"type": "text", "value": "登录", "score": 0})
    assert result["score"] == 20
