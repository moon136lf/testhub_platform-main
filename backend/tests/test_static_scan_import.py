"""入库：页面树幂等建节点/元素写入/已存在刷新/ai_failed剔除"""
from unittest.mock import AsyncMock, MagicMock
import pytest
from uuid import uuid4
from app.services.static_scan_service import StaticScanService

PROJECT_ID = str(uuid4())


def _comp(elements=2):
    els = []
    for i in range(elements):
        els.append({"tag": "el-button", "text": f"按钮{i}", "v_model": None, "placeholder": None,
                    "id": None, "href": None, "name": None, "data_testid": None, "pos": i + 2,
                    "locator_strategies": {"strategies": [{"type": "css", "value": f".btn{i}", "priority": 1}]}})
    return {"file_path": "src/views/Cases.vue", "component_name": "Cases",
            "template_snippet": "<div/>", "content_hash": "h1",
            "elements": els, "ai_failed": False}


class TestElementId:
    def test_element_id_from_text(self):
        e = {"tag": "el-button", "text": "新建用例", "id": None, "name": None,
             "placeholder": None, "data_testid": None}
        eid = StaticScanService.build_element_id("src/views/Cases.vue", e)
        assert eid == "cases_新建用例"

    def test_element_id_falls_back_to_tag_pos(self):
        e = {"tag": "el-input", "text": None, "id": None, "name": None,
             "placeholder": None, "data_testid": None}
        eid = StaticScanService.build_element_id("src/views/Cases.vue", e, pos=7)
        assert eid == "cases_el-input_7"


class TestImport:
    @pytest.mark.asyncio
    async def test_import_writes_elements_with_static_scan_source(self):
        db = MagicMock()
        page = MagicMock()
        page.id = "page-1"
        page.project_id = PROJECT_ID
        page.element_count = 0
        # execute 按顺序: 查页面树根节点(None) → 查页面 → 查已有element_id
        db.execute = AsyncMock(side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 根节点查询
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 页面按url查询
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 新建页面 refresh
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # element_id 查询
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        page.id = uuid4()
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, PROJECT_ID, _comp(), route_path="/cases")
        assert imported == 2 and skipped == 0
        # 断言写入了 element 与 page
        added = [c.args[0] for c in db.add.call_args_list]
        from app.models.element import ElementRepository, PageRepository
        assert any(isinstance(a, PageRepository) for a in added)
        elements = [a for a in added if isinstance(a, ElementRepository)]
        assert len(elements) == 2
        assert all(e.source == "static_scan" for e in elements)
        assert all(e.confidence == 5 for e in elements)

    @pytest.mark.asyncio
    async def test_ai_failed_component_skipped(self):
        db = MagicMock()
        comp = _comp()
        comp["ai_failed"] = True
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, PROJECT_ID, comp, route_path=None)
        assert imported == 0
        db.add.assert_not_called()
