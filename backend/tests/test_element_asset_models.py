"""元素资产模型扩展测试（验证字段存在与 to_dict 输出）"""
from datetime import datetime
from app.models.element import ElementRepository, PageRepository


class TestModelFields:
    def test_page_repository_has_tree_fields(self):
        p = PageRepository()
        assert hasattr(p, "parent_id")
        assert hasattr(p, "sort_order")

    def test_element_repository_has_scope_and_recycled(self):
        el = ElementRepository()
        assert hasattr(el, "scope")
        assert hasattr(el, "recycled_at")

    def test_page_to_dict_contains_tree(self):
        p = PageRepository(id=None, parent_id=None, sort_order=3)
        d = p.to_dict()
        assert d["sort_order"] == 3
        assert "parent_id" in d

    def test_element_to_dict_contains_scope(self):
        el = ElementRepository(scope="global", recycled_at=datetime(2026, 9, 7, 10, 0))
        d = el.to_dict()
        assert d["scope"] == "global"
        assert d["recycled_at"] == "2026-09-07T10:00:00"

    def test_global_element_page_id_none_serialization(self):
        el = ElementRepository(scope="global", page_id=None)
        d = el.to_dict()
        assert d["page_id"] is None
