"""ElementAssetService 测试（mock db）—— 阶段1 引用计数 + CRUD/调序/回收站"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime as _dt

from app.services.element_asset_service import ElementAssetService


def _db():
    return MagicMock()


def _script(step_element_names):
    s = MagicMock()
    s.step_mapping = [{"element_name": n} for n in step_element_names]
    return s


def _exec_return(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute


class TestRefCount:
    @pytest.mark.asyncio
    async def test_counts_scripts_referencing_element(self):
        db = _db()
        scripts = [
            _script(["登录按钮", "用户名输入框"]),
            _script(["登录按钮"]),
            _script(["其他元素"]),
        ]
        db.execute = _exec_return(scripts)

        svc = ElementAssetService(db)
        n = await svc.count_references("p1", "登录按钮")
        assert n == 2

    @pytest.mark.asyncio
    async def test_one_script_counts_once_even_with_multiple_steps(self):
        """同一脚本多步骤引用同一元素，只计 1 次"""
        db = _db()
        scripts = [_script(["登录按钮", "登录按钮", "登录按钮"])]
        db.execute = _exec_return(scripts)

        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "登录按钮") == 1

    @pytest.mark.asyncio
    async def test_empty_name_returns_zero(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "") == 0
        assert await svc.count_references("p1", None) == 0

    @pytest.mark.asyncio
    async def test_ignores_malformed_step_mapping(self):
        db = _db()
        s = MagicMock()
        s.step_mapping = ["not-a-dict", {"other": 1}, {"element_name": "目标元素"}]
        db.execute = _exec_return([s])
        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "目标元素") == 1

    @pytest.mark.asyncio
    async def test_zero_when_no_scripts(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "x") == 0


class TestListReferringScripts:
    @pytest.mark.asyncio
    async def test_lists_script_id_and_name(self):
        db = _db()
        s1, s2 = _script(["a"]), _script(["b"])
        s1.id, s1.name = uuid4(), "脚本A"
        s2.id, s2.name = uuid4(), "脚本B"
        db.execute = _exec_return([s1, s2])

        svc = ElementAssetService(db)
        refs = await svc.list_referring_scripts("p1", "a")
        assert [x["name"] for x in refs] == ["脚本A"]
        assert str(s1.id) == refs[0]["id"]

    @pytest.mark.asyncio
    async def test_list_empty_name_returns_empty(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.list_referring_scripts("p1", "") == []
        assert await svc.list_referring_scripts("p1", None) == []

    @pytest.mark.asyncio
    async def test_empty_when_none_reference(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.list_referring_scripts("p1", "x") == []


class TestElementCRUD:
    @pytest.mark.asyncio
    async def test_update_element_name(self):
        db = _db()
        el = MagicMock()
        el.element_name = "旧名"

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.update_element(str(uuid4()), {"element_name": "新名"})
        assert el.element_name == "新名"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_field(self):
        db = _db()
        el = MagicMock()

        async def _get(cls, eid):
            return el
        db.get = _get
        svc = ElementAssetService(db)
        with pytest.raises(ValueError):
            await svc.update_element(str(uuid4()), {"hack_field": "x"})

    @pytest.mark.asyncio
    async def test_update_missing_element_raises(self):
        db = _db()

        async def _get(cls, eid):
            return None
        db.get = _get
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="不存在"):
            await svc.update_element(str(uuid4()), {"element_name": "x"})


class TestReorder:
    @pytest.mark.asyncio
    async def test_reorder_down_swaps_and_rescores(self):
        """调序 = 相邻交换，score 跟随位置重排（150-pos*10），排序即置信度"""
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 100, "unique": True, "verified": True},
            {"type": "css", "value": ".b", "score": 80, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.reorder_locator(str(uuid4()), 0, "down")
        sts = el.locator_strategies["strategies"]
        assert sts[0]["value"] == ".b"   # css 升到第一
        assert sts[0]["score"] == 150    # score 跟随位置
        assert sts[1]["value"] == "#a" and sts[1]["score"] == 140

    @pytest.mark.asyncio
    async def test_reorder_up(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
            {"type": "css", "value": ".b", "score": 140, "unique": True, "verified": True},
            {"type": "text", "value": "t", "score": 130, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.reorder_locator(str(uuid4()), 2, "up")  # 最后一条上移
        sts = el.locator_strategies["strategies"]
        assert [s["value"] for s in sts] == ["#a", "t", ".b"]

    @pytest.mark.asyncio
    async def test_reorder_at_boundary_is_noop(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reorder_index_out_of_range_noop(self):
        """index 越界（schema 只约束 ge=0），up/down 都静默不 commit"""
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        for direction in ("up", "down"):
            el.locator_strategies = {"strategies": [
                {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
            ]}
            await svc.reorder_locator(str(uuid4()), 5, direction)
        assert el.locator_strategies["strategies"][0]["value"] == "#a"
        db.commit.assert_not_awaited()


class TestAddLocator:
    @pytest.mark.asyncio
    async def test_add_custom_locator(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": []}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.add_locator(str(uuid4()), "css", ".my-custom", score=50)
        sts = el.locator_strategies["strategies"]
        assert len(sts) == 1
        assert sts[0]["value"] == ".my-custom"
        assert sts[0]["source"] == "manual"
        assert sts[0]["unique"] is False

    @pytest.mark.asyncio
    async def test_add_locator_empty_value_raises(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError):
            await svc.add_locator(str(uuid4()), "css", "  ")


class TestRecycleBin:
    @pytest.mark.asyncio
    async def test_soft_delete_sets_recycled_at(self):
        db = _db()
        el = MagicMock()
        el.status = "active"

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.recycle_element(str(uuid4()))
        assert el.status == "deleted"
        assert el.recycled_at is not None

    @pytest.mark.asyncio
    async def test_restore_from_recycle(self):
        db = _db()
        el = MagicMock()
        el.status = "deleted"
        el.recycled_at = _dt(2026, 9, 1)

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.restore_element(str(uuid4()))
        assert el.status == "active"
        assert el.recycled_at is None

    @pytest.mark.asyncio
    async def test_list_recycled_filters_project_and_deleted(self):
        db = _db()
        els = [MagicMock(), MagicMock()]
        db.execute = _exec_return(els)

        svc = ElementAssetService(db)
        out = await svc.list_recycled("p1")
        assert out == els


class TestPageTree:
    @pytest.mark.asyncio
    async def test_create_sub_page_validates_name(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="名称"):
            await svc.create_sub_page("p1", None, "   ")  # 空白名

    @pytest.mark.asyncio
    async def test_create_sub_page_with_parent(self):
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        # PageRepository 构造是 ORM，直接让它进 added
        svc = ElementAssetService(db)
        page = await svc.create_sub_page("p1", "11111111-1111-1111-1111-111111111111", "登录页")
        assert added[0].parent_id is not None
        assert added[0].page_name == "登录页"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_sub_page_placeholder_url(self):
        """不传 page_url 时兜底为占位标记 URL（Task 7 快速校验识别用）"""
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.create_sub_page("p1", None, "登录页")
        assert added[0].page_url.startswith("/__placeholder__/")

    @pytest.mark.asyncio
    async def test_rename_page(self):
        db = _db()
        page = MagicMock()
        page.page_name = "旧名"

        async def _get(cls, pid):
            return page
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.rename_page(str(uuid4()), "新名")
        assert page.page_name == "新名"

    @pytest.mark.asyncio
    async def test_move_page_swaps_sort_order(self):
        db = _db()
        p1, p2 = MagicMock(), MagicMock()
        p1.id, p2.id = uuid4(), uuid4()
        p1.sort_order, p2.sort_order = 1, 2

        async def _get(cls, pid):
            return p1
        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [p1, p2]
            return r
        db.get = _get
        db.execute = _execute
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.move_page(str(p1.id), "down")
        assert p1.sort_order == 2 and p2.sort_order == 1

    @pytest.mark.asyncio
    async def test_move_page_at_boundary_noop(self):
        db = _db()
        p1 = MagicMock()
        p1.id = uuid4()
        p1.sort_order = 1

        async def _get(cls, pid):
            return p1
        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [p1]
            return r
        db.get = _get
        db.execute = _execute
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.move_page(str(p1.id), "up")  # 已在最上
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_page_with_children_blocked(self):
        db = _db()
        page = MagicMock(id=uuid4())
        child = MagicMock(parent_id=page.id)

        async def _get(cls, pid):
            return page
        async def _execute(q):
            # 第一次调用查 children 返回 [child]
            r = MagicMock()
            r.scalars.return_value.all.return_value = [child]
            return r
        db.get = _get
        db.execute = _execute

        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="子页面"):
            await svc.delete_page(str(page.id))

    @pytest.mark.asyncio
    async def test_delete_page_with_elements_requires_target_or_force(self):
        """页面下有元素时：不给迁移目标且不 force → 拒绝"""
        db = _db()
        page = MagicMock(id=uuid4())

        async def _get(cls, pid):
            return page
        async def _execute(q):
            r = MagicMock()
            # 查 children（空）→ 查元素数用 scalar
            r.scalars.return_value.all.return_value = []
            r.scalar.return_value = 3  # 有 3 个元素
            return r
        db.get = _get
        db.execute = _execute

        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="迁移"):
            await svc.delete_page(str(page.id), move_to_page_id=None, force=False)

    @pytest.mark.asyncio
    async def test_delete_page_move_elements_to_target(self):
        db = _db()
        page = MagicMock(id=uuid4())
        target_id = uuid4()

        async def _get(cls, pid):
            return page
        async def _exec(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            r.scalar.return_value = 3
            return r
        db.get = _get
        db.execute = AsyncMock(side_effect=_exec)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.delete_page(str(page.id), move_to_page_id=str(target_id), force=False)
        # 验证 update 语句执行了两次（迁移元素 + 删除页面前的所有 execute）
        assert db.execute.await_count >= 2
        db.delete.assert_awaited_once()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_page_move_to_missing_target_rejected(self):
        """迁移目标页面不存在 → 拒绝（children 空、元素数 3、目标计数 0）"""
        db = _db()
        page = MagicMock(id=uuid4())
        target_id = uuid4()

        async def _get(cls, pid):
            return page
        # 用调用序区分：第1次 children([])，第2次 count(3)，第3次目标存在性(0)
        calls = {"i": 0}
        async def _exec_seq(q):
            calls["i"] += 1
            r = MagicMock()
            if calls["i"] == 1:
                r.scalars.return_value.all.return_value = []
            elif calls["i"] == 2:
                r.scalar.return_value = 3
            else:
                r.scalar.return_value = 0
            return r
        db.get = _get
        db.execute = AsyncMock(side_effect=_exec_seq)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="迁移目标页面不存在"):
            await svc.delete_page(str(page.id), move_to_page_id=str(target_id), force=False)
        db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_page_force_recycles_elements(self):
        db = _db()
        page = MagicMock(id=uuid4())

        async def _get(cls, pid):
            return page
        async def _exec(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            r.scalar.return_value = 2
            return r
        db.get = _get
        db.execute = AsyncMock(side_effect=_exec)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.delete_page(str(page.id), force=True)
        db.delete.assert_awaited_once()


class TestGlobalElements:
    @pytest.mark.asyncio
    async def test_create_global_element_no_page(self):
        """全局元素不挂页面：page_id 为空 + scope=global"""
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.commit = AsyncMock()
        db.flush = AsyncMock()

        svc = ElementAssetService(db)
        el = await svc.create_element(
            project_id="p1", name="左侧菜单-设备管理", etype="link",
            text="设备管理", scope="global", page_id=None,
            locators=[{"type": "text", "value": "设备管理", "score": 80, "unique": True, "verified": True}],
        )
        assert added[0].scope == "global"
        assert added[0].page_id is None
        assert added[0].element_name == "左侧菜单-设备管理"
        assert added[0].source == "manual"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_page_element_requires_page(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="页面"):
            await svc.create_element("p1", "x", "button", "", scope="page", page_id=None)

    @pytest.mark.asyncio
    async def test_global_element_rejects_page(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="全局"):
            await svc.create_element("p1", "x", "button", "", scope="global", page_id="some-id")

    @pytest.mark.asyncio
    async def test_list_elements_scope_filter(self):
        db = _db()
        els = [MagicMock(scope="global"), MagicMock(scope="page")]
        db.execute = _exec_return(els)

        svc = ElementAssetService(db)
        out = await svc.list_elements("p1", scope="global")
        # mock db 不做 SQL 过滤，此处验证 scope 条件构造不报错且透传结果
        assert out == els

    @pytest.mark.asyncio
    async def test_list_elements_by_page_includes_global(self):
        """选中某页面：该页面元素 + 全局元素（mock 层验证传入的 or_ 条件构造不报错）"""
        db = _db()
        els = [MagicMock(), MagicMock()]
        db.execute = _exec_return(els)

        svc = ElementAssetService(db)
        out = await svc.list_elements("p1", page_id="11111111-1111-1111-1111-111111111111")
        assert len(out) == 2

    @pytest.mark.asyncio
    async def test_list_elements_keyword(self):
        db = _db()
        els = [MagicMock()]
        db.execute = _exec_return(els)

        svc = ElementAssetService(db)
        out = await svc.list_elements("p1", keyword="菜单")
        assert out == els

    @pytest.mark.asyncio
    async def test_list_elements_invalid_page_id_raises(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError):
            await svc.list_elements("p1", page_id="not-a-uuid")


class TestImportExport:
    @pytest.mark.asyncio
    async def test_export_shape(self):
        db = _db()
        el = MagicMock()
        el.to_dict.return_value = {
            "element_name": "登录按钮", "element_type": "button", "scope": "page",
            "element_text": "登录", "locator_strategies": {"strategies": [
                {"type": "id", "value": "#login", "score": 100}]},
        }
        db.execute = _exec_return([el])

        svc = ElementAssetService(db)
        data = await svc.export_elements("p1")
        assert data["version"] == 1
        assert "exported_at" in data
        assert data["elements"][0]["element_name"] == "登录按钮"
        assert "locator_strategies" in data["elements"][0]

    @pytest.mark.asyncio
    async def test_export_empty_project(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        data = await svc.export_elements("p1")
        assert data["elements"] == []

    @pytest.mark.asyncio
    async def test_import_creates_elements(self):
        db = _db()
        svc = ElementAssetService(db)
        svc.create_element = AsyncMock(return_value=MagicMock())
        payload = {"version": 1, "elements": [
            {"element_name": "x", "element_type": "button", "scope": "page",
             "page_id": "11111111-1111-1111-1111-111111111111", "element_text": "",
             "locator_strategies": {"strategies": []}}]}
        n = await svc.import_elements("p1", payload)
        assert n == 1
        svc.create_element.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_skips_bad_rows(self):
        """无名字的行跳过；单行异常不中断整体"""
        db = _db()
        svc = ElementAssetService(db)
        svc.create_element = AsyncMock(side_effect=[MagicMock(), ValueError("页面级元素必须指定页面")])
        payload = {"version": 1, "elements": [
            {"element_type": "button"},  # 无名字 → 跳过（不调 create_element）
            {"element_name": "ok", "element_type": "button", "scope": "page",
             "page_id": "11111111-1111-1111-1111-111111111111"},
            {"element_name": "bad", "element_type": "button", "scope": "page", "page_id": None},  # create 抛错 → 跳过
        ]}
        n = await svc.import_elements("p1", payload)
        assert n == 1
        assert svc.create_element.await_count == 2  # 无名字那行未调用

    @pytest.mark.asyncio
    async def test_import_empty_payload(self):
        db = _db()
        svc = ElementAssetService(db)
        assert await svc.import_elements("p1", {}) == 0
        assert await svc.import_elements("p1", None) == 0


class TestGlobalLookup:
    @pytest.mark.asyncio
    async def test_find_by_name_finds_global(self):
        """全局元素（page_id=None）同项目下可被 find_by_name 命中——现有逻辑天然支持，回归锁定"""
        from app.services.element_service import ElementService
        db = _db()
        el = MagicMock()
        el.element_name = "左侧菜单"
        el.element_text = "设备管理"

        async def _execute(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = el
            return r
        db.execute = _execute

        svc = ElementService(db)
        found = await svc.find_by_name("11111111-1111-1111-1111-111111111111", "设备管理")
        assert found is el
