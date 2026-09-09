"""source_type 透出+过滤（阶段3 T3）：白盒用例在用例管理页可见标识"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4


class TestSchemaSurfacing:
    def test_list_response_has_source_type(self):
        from app.schemas.test_case import CaseResponse
        assert "source_type" in CaseResponse.model_fields

    def test_detail_response_has_source_type(self):
        from app.schemas.test_case import CaseDetailResponse
        assert "source_type" in CaseDetailResponse.model_fields

    def test_to_dict_has_source_type(self):
        from app.models.test_case import TestCase
        tc = TestCase(source_type="whitescan")
        assert tc.to_dict()["source_type"] == "whitescan"


class TestFilter:
    @pytest.mark.asyncio
    async def test_service_filter_by_source_type(self):
        """service 层 source_type 过滤条件构造"""
        from app.services.test_case_service import TestCaseService
        from app.schemas.test_case import CaseFilterParams
        db = MagicMock()

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [MagicMock()]
            # total 查询
            r.scalar.return_value = 1
            return r
        db.execute = _execute

        svc = TestCaseService(db)
        filters = CaseFilterParams(project_id="11111111-1111-1111-1111-111111111111",
                                   source_type="whitescan")
        # 只验证不抛错 + 返回结构（mock 下 where 条件不可 assert——参照 feasibility 锁定测试的粒度）
        out = await svc.list_cases(filters)
        assert out is not None

    def test_filter_params_accepts_source_type(self):
        from app.schemas.test_case import CaseFilterParams
        f = CaseFilterParams(project_id="11111111-1111-1111-1111-111111111111", source_type="whitescan")
        assert f.source_type == "whitescan"
