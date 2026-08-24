"""
测试 scan_interactive_elements - 可交互元素扫描 (Task 12)

覆盖：
- 过滤不可见元素
- 基于坐标去重
- 多选择器扫描
- 选择器异常容错
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.playwright_service import scan_interactive_elements


def _make_elem(visible=True, box=None):
    """构造 Mock 元素"""
    elem = AsyncMock()
    elem.is_visible = AsyncMock(return_value=visible)
    elem.bounding_box = AsyncMock(return_value=box)
    return elem


class TestScanInteractiveElements:
    @pytest.mark.asyncio
    async def test_filters_hidden_elements(self):
        """应过滤不可见元素"""
        page = AsyncMock()
        visible_elem = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 80, "height": 30})
        hidden_elem = _make_elem(visible=False, box={"x": 100, "y": 200, "width": 80, "height": 30})

        # page.locator(selector).all() 返回元素列表
        def locator_factory(selector):
            mock_loc = AsyncMock()
            if selector == "button":
                mock_loc.all = AsyncMock(return_value=[visible_elem, hidden_elem])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page.locator = MagicMock(side_effect=locator_factory)

        result = await scan_interactive_elements(page)

        assert len(result) == 1
        assert result[0] is visible_elem

    @pytest.mark.asyncio
    async def test_dedupes_by_coordinates(self):
        """基于坐标去重"""
        page = AsyncMock()
        # 两个元素在同一坐标（重复）
        elem1 = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 80, "height": 30})
        elem2 = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 90, "height": 40})
        # 第三个元素不同坐标
        elem3 = _make_elem(visible=True, box={"x": 50, "y": 60, "width": 80, "height": 30})

        def locator_factory(selector):
            mock_loc = AsyncMock()
            mock_loc.all = AsyncMock(return_value=[elem1, elem2, elem3])
            return mock_loc

        page.locator = MagicMock(side_effect=locator_factory)

        result = await scan_interactive_elements(page)

        # elem1 和 elem2 同坐标，只保留第一个
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_scans_multiple_selectors(self):
        """应扫描多种选择器（button/input/link 等）"""
        page = AsyncMock()
        button = _make_elem(visible=True, box={"x": 1, "y": 1, "width": 10, "height": 10})
        link = _make_elem(visible=True, box={"x": 2, "y": 2, "width": 10, "height": 10})

        call_log = []

        def locator_factory(selector):
            call_log.append(selector)
            mock_loc = AsyncMock()
            if selector == "button":
                mock_loc.all = AsyncMock(return_value=[button])
            elif selector == "a[href]":
                mock_loc.all = AsyncMock(return_value=[link])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page.locator = MagicMock(side_effect=locator_factory)

        result = await scan_interactive_elements(page)

        # 验证扫描了多个选择器
        assert "button" in call_log
        assert "a[href]" in call_log
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_tolerates_selector_errors(self):
        """单个选择器异常不应中断整体扫描"""
        page = AsyncMock()

        def locator_factory(selector):
            if selector == "button":
                # 模拟 button 选择器抛异常
                mock_loc = AsyncMock()
                mock_loc.all = AsyncMock(side_effect=Exception("selector error"))
                return mock_loc
            # 其他选择器正常返回
            good_elem = _make_elem(visible=True, box={"x": 5, "y": 5, "width": 10, "height": 10})
            mock_loc = AsyncMock()
            mock_loc.all = AsyncMock(return_value=[good_elem])
            return mock_loc

        page.locator = MagicMock(side_effect=locator_factory)

        # 不应抛异常
        result = await scan_interactive_elements(page)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_tolerates_element_extraction_errors(self):
        """单个元素提取异常不应中断整体扫描"""
        page = AsyncMock()
        bad_elem = AsyncMock()
        bad_elem.is_visible = AsyncMock(side_effect=Exception("elem error"))
        good_elem = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 80, "height": 30})

        def locator_factory(selector):
            mock_loc = AsyncMock()
            if selector == "button":
                mock_loc.all = AsyncMock(return_value=[bad_elem, good_elem])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page.locator = MagicMock(side_effect=locator_factory)

        result = await scan_interactive_elements(page)

        # bad_elem 被跳过，只保留 good_elem
        assert len(result) == 1
        assert result[0] is good_elem

    @pytest.mark.asyncio
    async def test_includes_elements_without_bounding_box(self):
        """无 bounding box 的元素仍应加入结果（不参与去重，但不跳过）"""
        page = AsyncMock()
        no_box_elem = _make_elem(visible=True, box=None)
        good_elem = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 80, "height": 30})

        def locator_factory(selector):
            mock_loc = AsyncMock()
            if selector == "button":
                mock_loc.all = AsyncMock(return_value=[no_box_elem, good_elem])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page.locator = MagicMock(side_effect=locator_factory)

        result = await scan_interactive_elements(page)

        # 无 box 的元素仍被纳入结果（无法去重但保留）
        assert len(result) == 2
