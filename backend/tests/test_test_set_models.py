"""TestSet 模型测试（字段存在性 + to_dict）"""
from app.models.test_set import TestSet


class TestTestSetModel:
    def test_fields_exist(self):
        ts = TestSet()
        for f in ("name", "source", "case_ids", "last_pass_rate", "last_exec_id", "status"):
            assert hasattr(ts, f)

    def test_to_dict_shape(self):
        ts = TestSet(name="冒烟集", source="manual", case_ids=["a", "b"], status="pending")
        d = ts.to_dict()
        assert d["name"] == "冒烟集"
        assert d["case_ids"] == ["a", "b"]
        assert d["source"] == "manual"
        assert d["last_pass_rate"] == 0
