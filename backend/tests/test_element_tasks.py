"""
测试 element_tasks._fetch_elements_async 的 SSE 流程编排 (Task 13)

不依赖真实 Playwright/MinIO/Redis，全部 Mock，验证：
- 8 阶段 SSE 消息顺序与进度值
- 元素验证过滤（score >= 60）
- 截图上传调用
- 异常时发送 error 消息并 raise
- finally 关闭浏览器资源
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import app.tasks.element_tasks as element_tasks_module
from app.tasks.element_tasks import _fetch_elements_async


@pytest.fixture
def mock_deps():
    """Mock 所有外部依赖：PlaywrightService / scan / generate / verify / extract / storage / SSE / cache"""
    # Mock PlaywrightService 实例
    mock_pw = MagicMock()
    mock_pw.start = AsyncMock()
    mock_pw.close = AsyncMock()
    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_pw.browser = mock_browser
    mock_pw._auto_login = AsyncMock()

    # Mock SSEStream
    mock_sse = MagicMock()
    mock_sse.send_message = AsyncMock()

    # Mock storage_client
    mock_storage = MagicMock()
    mock_storage.upload_bytes = AsyncMock(return_value="http://minio/screenshot.png")

    # Mock scan / generate / verify / extract
    mock_elem = MagicMock()

    async def fake_scan(page):
        return [mock_elem, mock_elem]  # 2 个元素

    async def fake_generate(page, elem):
        return [{"type": "id", "value": "#x", "base_score": 100}]

    async def fake_verify(page, candidate, elem):
        return {"type": "id", "value": "#x", "score": 100, "unique": True, "verified": True}

    async def fake_extract(page, elem):
        return {
            "type": "button",
            "text": "登录",
            "placeholder": None,
            "aria_label": None,
            "aria_role": None,
            "coords": {"x": 10, "y": 20, "width": 80, "height": 30},
            "context": {"parent_tag": "form", "sibling_tags": []},
        }

    # 元素属性
    mock_elem.get_attribute = AsyncMock(return_value=None)
    mock_page.screenshot = AsyncMock(return_value=b"png-bytes")
    mock_page.close = AsyncMock()
    mock_page.goto = AsyncMock()

    return {
        "pw": mock_pw,
        "page": mock_page,
        "context": mock_context,
        "sse": mock_sse,
        "storage": mock_storage,
        "elem": mock_elem,
        "fake_scan": fake_scan,
        "fake_generate": fake_generate,
        "fake_verify": fake_verify,
        "fake_extract": fake_extract,
    }


class TestFetchElementsAsync:
    @pytest.mark.asyncio
    async def test_successful_fetch_returns_elements_and_progress(self, mock_deps):
        session_id = str(uuid4())
        project_id = str(uuid4())

        with patch.object(element_tasks_module, "PlaywrightService", return_value=mock_deps["pw"]), \
             patch.object(element_tasks_module, "scan_interactive_elements", mock_deps["fake_scan"]), \
             patch.object(element_tasks_module, "generate_locators_for_element", mock_deps["fake_generate"]), \
             patch.object(element_tasks_module, "verify_and_score_locator", mock_deps["fake_verify"]), \
             patch.object(element_tasks_module, "extract_semantic_info", mock_deps["fake_extract"]), \
             patch.object(element_tasks_module, "storage_client", mock_deps["storage"]), \
             patch.object(element_tasks_module, "SSEStream", return_value=mock_deps["sse"]), \
             patch.object(element_tasks_module, "ElementCacheService") as mock_cache_cls:
            mock_cache_cls.cache_page = AsyncMock()

            result = await _fetch_elements_async(
                session_id, project_id, "https://example.com", None, None
            )

        # 验证返回结构
        assert result["session_id"] == session_id
        assert result["url"] == "https://example.com"
        assert result["screenshot_url"] == "http://minio/screenshot.png"
        assert result["total_count"] == 2
        assert len(result["elements"]) == 2
        assert "duration_seconds" in result

        # 验证元素结构含 locator_strategies
        elem = result["elements"][0]
        assert "temp_id" in elem
        assert "locator_strategies" in elem
        assert "strategies" in elem["locator_strategies"]
        assert elem["locator_strategies"]["strategies"][0]["score"] == 100

        # 验证 SSE 消息发送了 complete（progress=1.0）
        sent_stages = [call.kwargs.get("stage") for call in mock_deps["sse"].send_message.call_args_list]
        sent_progresses = [call.kwargs.get("progress") for call in mock_deps["sse"].send_message.call_args_list]
        assert "complete" in sent_stages
        assert 1.0 in sent_progresses

    @pytest.mark.asyncio
    async def test_filters_locators_below_score_threshold(self, mock_deps):
        """score < 60 的定位器应被过滤，元素无有效定位器则跳过"""
        session_id = str(uuid4())
        project_id = str(uuid4())

        # verify 返回低分定位器
        async def fake_verify_low(page, candidate, elem):
            return {"type": "css", "value": ".x", "score": 30, "unique": False, "verified": True}

        with patch.object(element_tasks_module, "PlaywrightService", return_value=mock_deps["pw"]), \
             patch.object(element_tasks_module, "scan_interactive_elements", mock_deps["fake_scan"]), \
             patch.object(element_tasks_module, "generate_locators_for_element", mock_deps["fake_generate"]), \
             patch.object(element_tasks_module, "verify_and_score_locator", fake_verify_low), \
             patch.object(element_tasks_module, "extract_semantic_info", mock_deps["fake_extract"]), \
             patch.object(element_tasks_module, "storage_client", mock_deps["storage"]), \
             patch.object(element_tasks_module, "SSEStream", return_value=mock_deps["sse"]), \
             patch.object(element_tasks_module, "ElementCacheService") as mock_cache_cls:
            mock_cache_cls.cache_page = AsyncMock()

            result = await _fetch_elements_async(
                session_id, project_id, "https://example.com", None, None
            )

        # 所有定位器 score=30 < 60，元素被跳过
        assert result["total_count"] == 0
        assert result["elements"] == []

    @pytest.mark.asyncio
    async def test_sends_error_message_on_exception(self, mock_deps):
        """异常时应发送 error 消息并 re-raise"""
        session_id = str(uuid4())
        project_id = str(uuid4())

        # 让 page.goto 抛异常
        mock_deps["page"].goto = AsyncMock(side_effect=Exception("network error"))

        with patch.object(element_tasks_module, "PlaywrightService", return_value=mock_deps["pw"]), \
             patch.object(element_tasks_module, "storage_client", mock_deps["storage"]), \
             patch.object(element_tasks_module, "SSEStream", return_value=mock_deps["sse"]), \
             patch.object(element_tasks_module, "ElementCacheService"):

            with pytest.raises(Exception, match="network error"):
                await _fetch_elements_async(
                    session_id, project_id, "https://example.com", None, None
                )

        # 验证发送了 error 消息
        sent_types = [call.kwargs.get("type") for call in mock_deps["sse"].send_message.call_args_list]
        assert "error" in sent_types

    @pytest.mark.asyncio
    async def test_closes_browser_resources_in_finally(self, mock_deps):
        """无论成功失败，finally 都应关闭 page/context/browser"""
        session_id = str(uuid4())
        project_id = str(uuid4())

        with patch.object(element_tasks_module, "PlaywrightService", return_value=mock_deps["pw"]), \
             patch.object(element_tasks_module, "scan_interactive_elements", mock_deps["fake_scan"]), \
             patch.object(element_tasks_module, "generate_locators_for_element", mock_deps["fake_generate"]), \
             patch.object(element_tasks_module, "verify_and_score_locator", mock_deps["fake_verify"]), \
             patch.object(element_tasks_module, "extract_semantic_info", mock_deps["fake_extract"]), \
             patch.object(element_tasks_module, "storage_client", mock_deps["storage"]), \
             patch.object(element_tasks_module, "SSEStream", return_value=mock_deps["sse"]), \
             patch.object(element_tasks_module, "ElementCacheService") as mock_cache_cls:
            mock_cache_cls.cache_page = AsyncMock()

            await _fetch_elements_async(
                session_id, project_id, "https://example.com", None, None
            )

        # 验证 finally 关闭了资源
        mock_deps["page"].close.assert_awaited_once()
        mock_deps["context"].close.assert_awaited_once()
        mock_deps["pw"].close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_calls_auto_login_when_credentials_provided(self, mock_deps):
        """提供 username/password 时应调用 _auto_login"""
        session_id = str(uuid4())
        project_id = str(uuid4())

        with patch.object(element_tasks_module, "PlaywrightService", return_value=mock_deps["pw"]), \
             patch.object(element_tasks_module, "scan_interactive_elements", mock_deps["fake_scan"]), \
             patch.object(element_tasks_module, "generate_locators_for_element", mock_deps["fake_generate"]), \
             patch.object(element_tasks_module, "verify_and_score_locator", mock_deps["fake_verify"]), \
             patch.object(element_tasks_module, "extract_semantic_info", mock_deps["fake_extract"]), \
             patch.object(element_tasks_module, "storage_client", mock_deps["storage"]), \
             patch.object(element_tasks_module, "SSEStream", return_value=mock_deps["sse"]), \
             patch.object(element_tasks_module, "ElementCacheService") as mock_cache_cls:
            mock_cache_cls.cache_page = AsyncMock()

            await _fetch_elements_async(
                session_id, project_id, "https://example.com", "admin", "pass123"
            )

        mock_deps["pw"]._auto_login.assert_awaited_once_with(mock_deps["page"], "admin", "pass123")

        # 验证发送了 login 阶段消息
        sent_stages = [call.kwargs.get("stage") for call in mock_deps["sse"].send_message.call_args_list]
        assert "login" in sent_stages

    @pytest.mark.asyncio
    async def test_screenshot_uploaded_with_correct_path(self, mock_deps):
        """截图应上传到 screenshots/{project_id}/{uuid}.png 路径"""
        session_id = str(uuid4())
        project_id = str(uuid4())

        with patch.object(element_tasks_module, "PlaywrightService", return_value=mock_deps["pw"]), \
             patch.object(element_tasks_module, "scan_interactive_elements", mock_deps["fake_scan"]), \
             patch.object(element_tasks_module, "generate_locators_for_element", mock_deps["fake_generate"]), \
             patch.object(element_tasks_module, "verify_and_score_locator", mock_deps["fake_verify"]), \
             patch.object(element_tasks_module, "extract_semantic_info", mock_deps["fake_extract"]), \
             patch.object(element_tasks_module, "storage_client", mock_deps["storage"]), \
             patch.object(element_tasks_module, "SSEStream", return_value=mock_deps["sse"]), \
             patch.object(element_tasks_module, "ElementCacheService") as mock_cache_cls:
            mock_cache_cls.cache_page = AsyncMock()

            await _fetch_elements_async(
                session_id, project_id, "https://example.com", None, None
            )

        upload_args = mock_deps["storage"].upload_bytes.call_args
        filename = upload_args[0][1]
        assert filename.startswith(f"screenshots/{project_id}/")
        assert filename.endswith(".png")


class TestFetchFilters:
    def test_text_filter_keeps_matching(self):
        """text_filter 逗号分隔, 任一词是 element_text 子串则保留."""
        from app.tasks.element_tasks import _apply_filters
        elems = [{"element_text": "新增设备"}, {"element_text": "删除"}, {"element_text": "搜索"}]
        out = _apply_filters(elems, text_filter="+,删除", type_filter="", debug_mode=False)
        assert len(out) == 1 and out[0]["element_text"] == "删除"

    def test_type_filter(self):
        from app.tasks.element_tasks import _apply_filters
        elems = [{"element_type": "button", "element_text": "a"},
                 {"element_type": "input", "element_text": "b"}]
        out = _apply_filters(elems, text_filter="", type_filter="button", debug_mode=False)
        assert len(out) == 1 and out[0]["element_type"] == "button"

    def test_debug_mode_bypasses_filters(self):
        from app.tasks.element_tasks import _apply_filters
        elems = [{"element_type": "span", "element_text": "x"}]
        out = _apply_filters(elems, text_filter="不存在", type_filter="button", debug_mode=True)
        assert len(out) == 1


class TestSemanticCoords:
    @pytest.mark.asyncio
    async def test_semantic_coords_are_bounding_box(self):
        """coords 必须来自 bounding_box (视口坐标), P2 高亮点选依赖."""
        from unittest.mock import AsyncMock, MagicMock
        from app.services.playwright_locator_core import extract_semantic_info

        elem = MagicMock()
        elem.evaluate = AsyncMock(return_value="button")  # tagName + parent/sibling 共用返回桩
        elem.inner_text = AsyncMock(return_value="text")
        elem.get_attribute = AsyncMock(return_value=None)
        elem.bounding_box = AsyncMock(
            return_value={"x": 10, "y": 20, "width": 30, "height": 40}
        )

        info = await extract_semantic_info(MagicMock(), elem)

        elem.bounding_box.assert_awaited_once()
        assert info["coords"] == {"x": 10, "y": 20, "width": 30, "height": 40}
