"""StaticScanComponent 模型字段与 to_dict 契约"""
from app.models.whitescan import StaticScanComponent


class TestStaticScanComponent:
    def test_to_dict_contract(self):
        c = StaticScanComponent(
            project_id="00000000-0000-0000-0000-000000000001",
            scan_id="00000000-0000-0000-0000-000000000002",
            file_path="src/views/Cases.vue",
            component_name="Cases",
            content_hash="abc123",
            element_count=5,
            ai_generated=True,
            reused=False,
            ai_failed=False,
        )
        d = c.to_dict()
        assert d["file_path"] == "src/views/Cases.vue"
        assert d["component_name"] == "Cases"
        assert d["element_count"] == 5
        assert d["ai_generated"] is True
        assert d["reused"] is False
        assert d["page_id"] is None  # 未设 page_id 时 to_dict 不崩
