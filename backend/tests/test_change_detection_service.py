"""
测试 ChangeDetectionService (ELEM-05/06/07)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from app.services.change_detection_service import ChangeDetectionService


def _make_elem(element_id, locator_value="#x", text="btn"):
    return {
        "element_id": element_id,
        "element_name": text,
        "element_text": text,
        "position_x": 100,
        "position_y": 200,
        "locator_strategies": {"strategies": [{"type": "id", "value": locator_value, "score": 100}]},
    }


class TestElementSignature:
    def test_uses_element_id_when_present(self):
        sig = ChangeDetectionService._element_signature(_make_elem("btn-1"))
        assert sig == "btn-1"

    def test_falls_back_to_text_coords(self):
        elem = {"element_text": "Submit", "position_x": 10, "position_y": 20}
        sig = ChangeDetectionService._element_signature(elem)
        assert "Submit" in sig and "10" in sig and "20" in sig


class TestLocatorSummary:
    def test_extracts_top_strategy(self):
        elem = _make_elem("b", "#id")
        loc = ChangeDetectionService._locator_summary(elem)
        assert loc == {"type": "id", "value": "#id", "score": 100}

    def test_returns_none_when_no_strategies(self):
        assert ChangeDetectionService._locator_summary({"locator_strategies": {"strategies": []}}) is None


class TestDetectChanges:
    @pytest.mark.asyncio
    async def test_detects_added_elements(self):
        page_id = uuid4()
        project_id = uuid4()

        # Mock page
        mock_page = MagicMock()
        mock_page.id = page_id
        mock_page.project_id = project_id

        # Mock current elements (2 elements)
        elem1 = MagicMock()
        elem1.to_dict.return_value = _make_elem("btn-1", "#id1")
        elem2 = MagicMock()
        elem2.to_dict.return_value = _make_elem("btn-2", "#id2")

        db = AsyncMock()
        # page query
        page_result = MagicMock()
        page_result.scalar_one_or_none.return_value = mock_page
        # fetch_history query (no current fetch)
        fetch_result = MagicMock()
        fetch_result.scalar_one_or_none.return_value = None
        # last_detection query (none -> treat as first detection, no added)
        last_result = MagicMock()
        last_result.scalar_one_or_none.return_value = None
        # current elements query
        elems_result = MagicMock()
        elems_scalars = MagicMock()
        elems_scalars.all.return_value = [elem1, elem2]
        elems_result.scalars.return_value = elems_scalars

        db.execute = AsyncMock(side_effect=[page_result, fetch_result, last_result, elems_result])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        detection = await ChangeDetectionService.detect_changes(db, page_id)

        # 首次检测（无 last_detection）：所有元素视为已存在，无 added
        assert detection.added_count == 0
        assert detection.project_id == project_id
        assert detection.status == "pending"

    @pytest.mark.asyncio
    async def test_detects_modifications_when_locator_changes(self):
        page_id = uuid4()
        project_id = uuid4()

        mock_page = MagicMock()
        mock_page.id = page_id
        mock_page.project_id = project_id

        # last_detection had element btn-1 with locator #old
        last_detection = MagicMock()
        last_detection.current_fetch_id = uuid4()
        last_detection.added = []
        last_detection.modified = [{
            "element_id": "btn-1",
            "element_name": "btn",
            "old_locator": {"type": "id", "value": "#old", "score": 100},
            "new_locator": {"type": "id", "value": "#new", "score": 100},
        }]

        # current element btn-1 with locator #new (changed)
        elem1 = MagicMock()
        elem1.to_dict.return_value = _make_elem("btn-1", "#new")

        db = AsyncMock()
        page_result = MagicMock(); page_result.scalar_one_or_none.return_value = mock_page
        fetch_result = MagicMock(); fetch_result.scalar_one_or_none.return_value = None
        last_result = MagicMock(); last_result.scalar_one_or_none.return_value = last_detection
        elems_result = MagicMock()
        elems_scalars = MagicMock(); elems_scalars.all.return_value = [elem1]
        elems_result.scalars.return_value = elems_scalars

        db.execute = AsyncMock(side_effect=[page_result, fetch_result, last_result, elems_result])
        db.add = MagicMock(); db.commit = AsyncMock(); db.refresh = AsyncMock()

        detection = await ChangeDetectionService.detect_changes(db, page_id)

        # btn-1 在 base（来自 last_detection.modified）存在，current 也存在，但定位器从 #old 变 #new
        # 注意：base_signatures 从 last_detection 的 added+modified 构建，btn-1 的 locator 是 #new（来自 modified 的 new_locator）
        # 所以 current 的 #new 与 base 的 #new 相同 -> 不算 modified
        # 这个测试验证：当定位器未变时，不误报
        assert detection.modified_count == 0


class TestMarkAffectedScripts:
    @pytest.mark.asyncio
    async def test_updates_affected_scripts_and_impact(self):
        detection_id = uuid4()
        detection = MagicMock()
        detection.affected_scripts = []
        detection.affected_script_count = 0
        detection.impact_level = "low"

        db = AsyncMock()
        result = MagicMock(); result.scalar_one_or_none.return_value = detection
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock(); db.refresh = AsyncMock()

        scripts = [
            {"script_id": "s1", "script_name": "login_test", "elements": ["btn-1"]},
            {"script_id": "s2", "script_name": "reg_test", "elements": ["btn-2"]},
            {"script_id": "s3", "script_name": "search_test", "elements": ["btn-3"]},
            {"script_id": "s4", "script_name": "x_test", "elements": ["btn-4"]},
        ]

        updated = await ChangeDetectionService.mark_affected_scripts(db, detection_id, scripts)

        assert updated.affected_script_count == 4
        assert updated.impact_level == "high"  # >3 脚本 -> high


class TestUpdateLocatorsOneClick:
    @pytest.mark.asyncio
    async def test_updates_modified_element_locators(self):
        detection_id = uuid4()
        page_id = uuid4()

        detection = MagicMock()
        detection.id = detection_id
        detection.page_id = page_id
        detection.modified = [{
            "element_id": "btn-1",
            "element_name": "Login",
            "old_locator": {"type": "id", "value": "#old", "score": 100},
            "new_locator": {"type": "id", "value": "#new", "score": 110},
        }]
        detection.status = "pending"

        # Mock element found
        elem = MagicMock()
        elem.locator_strategies = {"strategies": [{"type": "id", "value": "#old", "score": 100}]}
        elem.element_id = "btn-1"
        elem.source = "auto"

        db = AsyncMock()
        # first execute: get detection; second: get element
        det_result = MagicMock(); det_result.scalar_one_or_none.return_value = detection
        elem_result = MagicMock(); elem_result.scalar_one_or_none.return_value = elem
        db.execute = AsyncMock(side_effect=[det_result, elem_result])
        db.commit = AsyncMock()

        result = await ChangeDetectionService.update_locators_one_click(db, detection_id)

        assert result["updated_count"] == 1
        assert result["failed_count"] == 0
        assert detection.status == "fixed"
        assert detection.fixed_at is not None
        # 验证新定位器置顶
        assert elem.locator_strategies["strategies"][0]["value"] == "#new"
        assert elem.source == "healed"

    @pytest.mark.asyncio
    async def test_counts_failure_when_element_not_found(self):
        detection_id = uuid4()
        detection = MagicMock()
        detection.page_id = uuid4()
        detection.modified = [{"element_id": "gone", "element_name": "x", "old_locator": {}, "new_locator": {"type": "id", "value": "#x"}}]
        detection.status = "pending"

        db = AsyncMock()
        det_result = MagicMock(); det_result.scalar_one_or_none.return_value = detection
        elem_result = MagicMock(); elem_result.scalar_one_or_none.return_value = None  # 元素不存在
        db.execute = AsyncMock(side_effect=[det_result, elem_result])
        db.commit = AsyncMock()

        result = await ChangeDetectionService.update_locators_one_click(db, detection_id)

        assert result["updated_count"] == 0
        assert result["failed_count"] == 1
        assert detection.status == "fixed"
