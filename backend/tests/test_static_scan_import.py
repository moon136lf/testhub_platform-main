"""入库：页面树幂等建节点/元素写入/已存在刷新/ai_failed剔除"""
from unittest.mock import AsyncMock, MagicMock
import pytest
from uuid import uuid4
from app.services.static_scan_service import StaticScanService

PROJECT_ID = str(uuid4())


def _db_with_select_results(select_results):
    """db mock：execute 对 Select 语句按序返回 select_results，对 Update 语句返回空 MagicMock。"""
    from sqlalchemy.sql.dml import Update as _Update
    db = MagicMock()
    queue = list(select_results)

    async def _execute(stmt, *a, **kw):
        if isinstance(stmt, _Update):
            return MagicMock()
        return queue.pop(0)
    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


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
    async def test_existing_element_with_new_locator_updated(self):
        """I-1: 已存在元素 + 定位器不同 → 刷新 locator_strategies，不静默丢弃"""
        db = MagicMock()
        old_locator = {"strategies": [{"type": "css", "value": ".old", "priority": 1}]}
        existing_row = ("cases_按钮0", old_locator)
        db = _db_with_select_results([
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 页面按url查询→新建
            MagicMock(all=MagicMock(return_value=[existing_row])),        # 已有元素查询(element_id, locator)
        ])
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, PROJECT_ID, _comp(), route_path="/cases")
        # 按钮0 定位器不同 → 更新（不计入 imported，走 UPDATE 语句）；按钮1 新元素 → imported
        from sqlalchemy.sql.dml import Update as _Upd
        upd_stmts = [c.args[0] for c in db.execute.call_args_list
                     if isinstance(c.args[0], _Upd)
                     and c.args[0].table.name == "element_repository"]
        assert len(upd_stmts) == 1
        assert imported == 1 and skipped == 0  # 按钮0 走 UPDATE 分支，按钮1 新建
        # 不应为已存在元素新建行
        from app.models.element import ElementRepository
        new_elems = [a for a in (c.args[0] for c in db.add.call_args_list)
                     if isinstance(a, ElementRepository)]
        assert len(new_elems) == 1
        assert new_elems[0].element_id == "cases_按钮1"

    @pytest.mark.asyncio
    async def test_existing_element_with_same_locator_skipped(self):
        """I-1: 已存在元素 + 定位器相同 → 维持 skip，不重复写"""
        db = MagicMock()
        same_locator = {"strategies": [{"type": "css", "value": ".btn0", "priority": 1}]}
        existing_row = ("cases_按钮0", same_locator)
        db = _db_with_select_results([
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(all=MagicMock(return_value=[existing_row])),
        ])
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, PROJECT_ID, _comp(), route_path="/cases")
        assert imported == 1 and skipped == 1
        from app.models.element import ElementRepository
        new_elems = [a for a in (c.args[0] for c in db.add.call_args_list)
                     if isinstance(a, ElementRepository)]
        assert len(new_elems) == 1 and new_elems[0].element_id == "cases_按钮1"

    @pytest.mark.asyncio
    async def test_element_count_updated_after_import(self):
        """I-2: 入库后 page.element_count 回填本次成功数"""
        db = MagicMock()
        page = MagicMock()
        page.element_count = 0
        db = _db_with_select_results([
            MagicMock(scalar_one_or_none=MagicMock(return_value=page)),   # 页面已存在
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        svc = StaticScanService()
        await svc.import_component(db, PROJECT_ID, _comp(), route_path="/cases")
        # element_count 走 SQL UPDATE（coalesce+imported），断言 UPDATE 语句发出
        from sqlalchemy.sql.dml import Update as _Upd
        upd_stmts = [c.args[0] for c in db.execute.call_args_list
                     if isinstance(c.args[0], _Upd)
                     and c.args[0].table.name == "page_repository"]
        assert len(upd_stmts) == 1

    @pytest.mark.asyncio
    async def test_element_count_accumulates_on_reimport(self):
        """I-2: 已有元素 + 新导入元素 → element_count 累加（不覆盖旧值）"""
        db = MagicMock()
        page = MagicMock()
        page.element_count = 5  # 库里已有 5 个元素
        same_locator = {"strategies": [{"type": "css", "value": ".btn0", "priority": 1}]}
        existing_elem = ("cases_按钮0", same_locator)
        db = _db_with_select_results([
            MagicMock(scalar_one_or_none=MagicMock(return_value=page)),   # 页面已存在
            MagicMock(all=MagicMock(return_value=[existing_elem])),       # 已有元素查询
        ])
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, PROJECT_ID, _comp(), route_path="/cases")
        assert imported == 1 and skipped == 1
        # element_count 累加：UPDATE page_repository SET element_count=coalesce+1
        from sqlalchemy.sql.dml import Update as _Upd
        upd_stmts = [c.args[0] for c in db.execute.call_args_list
                     if isinstance(c.args[0], _Upd)
                     and c.args[0].table.name == "page_repository"]
        assert len(upd_stmts) == 1
        compiled = str(upd_stmts[0].compile(compile_kwargs={"literal_binds": True}))
        assert "coalesce" in compiled and "+ 1" in compiled

    @pytest.mark.asyncio
    async def test_ai_failed_component_skipped(self):
        db = MagicMock()
        comp = _comp()
        comp["ai_failed"] = True
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, PROJECT_ID, comp, route_path=None)
        assert imported == 0
        db.add.assert_not_called()
