"""Task 6: Celery 双支路编排——B支路流程/失败不阻断A/临时清理/JSONB键归一/解压安全"""
import json
import os
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.code_scan_tasks import (
    _locator_branch,
    _normalize_prior,
    _safe_extract,
    run_locator_scan_task_inner,
)


@pytest.fixture
def zip_path(tmp_path):
    z = tmp_path / "front.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("src/views/A.vue", "<template><el-button @click='a'>按钮A</el-button></template>")
        f.writestr("src/views/B.vue", "<template><el-input v-model='x' placeholder='输入' /></template>")
    return str(z)


def _make_svc(decision=None, ai_failed=False):
    svc = MagicMock()
    svc.extract_components = MagicMock(return_value=[
        {"file_path": "src/views/A.vue", "component_name": "A",
         "template_snippet": "<div/>", "content_hash": "h1",
         "elements": [{"tag": "el-button", "text": "按钮A", "pos": 1}]},
    ])
    svc.decide_reuse = MagicMock(return_value=decision)
    svc.generate_component = AsyncMock(side_effect=lambda c: {**c, "ai_failed": ai_failed})
    svc.import_component = AsyncMock(return_value=("page-1", 1, 0))
    svc.record_component = AsyncMock()
    return svc


class _FakeSessionCM:
    def __init__(self):
        self.db = MagicMock()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def fake_db():
    with patch("app.tasks.code_scan_tasks.AsyncSessionLocal", _FakeSessionCM()):
        yield


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


class TestLocatorBranch:
    def test_b_branch_pipeline(self, zip_path, fake_db):
        """B 支路：提取→AI→入库→组件记录，全部协调完成"""
        mock_record = AsyncMock()
        svc = _make_svc()
        prior_loader = AsyncMock(return_value={})
        with patch("app.tasks.code_scan_tasks._record_component", mock_record):
            result = _run(_locator_branch("scan-1", "proj-1", zip_path, str(zip_path) + "_work",
                                          svc=svc, prior_loader=prior_loader))
        assert result["components"] == 1
        assert result["imported"] == 1
        assert result["reused"] == 0
        assert result["ai_failed"] == 0
        svc.generate_component.assert_awaited_once()
        svc.import_component.assert_awaited_once()
        mock_record.assert_awaited_once()

    def test_reuse_skips_ai(self, zip_path, fake_db):
        """hash 未变：decide_reuse 命中 → 跳过 AI，计 reused"""
        svc = _make_svc(decision={"reused": True})
        prior_loader = AsyncMock(return_value={})
        with patch("app.tasks.code_scan_tasks._record_component", AsyncMock()):
            result = _run(_locator_branch("scan-1", "proj-1", zip_path, str(zip_path) + "_work",
                                          svc=svc, prior_loader=prior_loader))
        assert result["reused"] == 1
        svc.generate_component.assert_not_awaited()
        svc.import_component.assert_awaited_once()

    def test_ai_failed_component_not_imported(self, zip_path, fake_db):
        """AI 失败：不入元素库，计 ai_failed，但仍记录组件 hash 行"""
        svc = _make_svc(ai_failed=True)
        prior_loader = AsyncMock(return_value={})
        mock_record = AsyncMock()
        with patch("app.tasks.code_scan_tasks._record_component", mock_record):
            result = _run(_locator_branch("scan-1", "proj-1", zip_path, str(zip_path) + "_work",
                                          svc=svc, prior_loader=prior_loader))
        assert result["ai_failed"] == 1
        assert result["imported"] == 0
        svc.import_component.assert_not_awaited()
        mock_record.assert_awaited_once()  # ai_failed 组件仍落 hash 表


class TestInnerOrchestration:
    def test_single_branch_failure_does_not_raise(self, zip_path):
        """A 支路失败不阻断：B 成功则任务正常返回且带 a 错误信息"""
        staging = os.path.dirname(zip_path)
        result = run_locator_scan_task_inner(
            "scan-1", "proj-1", zip_path,
            a_branch=MagicMock(side_effect=RuntimeError("semgrep down")),
            b_branch=MagicMock(return_value={"components": 2, "imported": 2}),
        )
        assert result["static"] == {"components": 2, "imported": 2}
        assert "semgrep down" in result["semgrep"]["error"]

    def test_both_branches_fail_raises(self, zip_path):
        with pytest.raises(RuntimeError, match="both branches failed"):
            run_locator_scan_task_inner(
                "scan-1", "proj-1", zip_path,
                a_branch=MagicMock(side_effect=RuntimeError("a boom")),
                b_branch=MagicMock(side_effect=RuntimeError("b boom")),
            )

    def test_temp_cleanup_on_failure(self, tmp_path):
        """任务结束（无论成败）清理解压目录 + 上传暂存目录（必查项 b）"""
        staging = tmp_path / "static_scan_stage"
        staging.mkdir()
        zp = staging / "upload.zip"
        with zipfile.ZipFile(zp, "w") as f:
            f.writestr("src/A.vue", "<template><button>x</button></template>")
        import glob
        import tempfile as _tempfile
        before = set(glob.glob(os.path.join(_tempfile.gettempdir(), "static_scan_work_*")))
        with pytest.raises(RuntimeError):
            run_locator_scan_task_inner(
                "scan-1", "proj-1", str(zp),
                a_branch=MagicMock(side_effect=RuntimeError("a boom")),
            )
        after = set(glob.glob(os.path.join(_tempfile.gettempdir(), "static_scan_work_*")))
        assert not (after - before), "work_dir 残留"
        assert not staging.exists(), "上传暂存目录残留"


class TestJsonbKeyNormalization:
    def test_jsonb_roundtrip_keys_reuse(self):
        """必查项 a：prior 经 JSONB 往返后键变字符串 "0"，归一后 decide_reuse 仍复用"""
        prior = {"src/views/A.vue": {
            "content_hash": "h1",
            "strategies_by_index": {0: {"strategies": [{"type": "css", "value": "button", "priority": 1}]}},
        }}
        # 模拟 JSONB 持久化往返：int 键 → "0"
        roundtripped = json.loads(json.dumps(prior))
        assert "0" in roundtripped["src/views/A.vue"]["strategies_by_index"]  # 前提成立
        from app.services.static_scan_service import StaticScanService
        comp = {"file_path": "src/views/A.vue", "content_hash": "h1",
                "elements": [{"tag": "button", "text": "x", "pos": 1}]}
        # 未归一：静默 miss（复现 Task 3 审查缺陷 1）
        assert StaticScanService.decide_reuse(comp, roundtripped) is None
        # 归一后：复用成功
        normalized = _normalize_prior(roundtripped)
        assert StaticScanService.decide_reuse(comp, normalized) == {"reused": True}


class TestSafeExtract:
    def test_rejects_path_traversal(self, tmp_path):
        zp = tmp_path / "evil.zip"
        with zipfile.ZipFile(zp, "w") as f:
            f.writestr("../evil.vue", "x")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValueError, match="path traversal"):
            _safe_extract(str(zp), str(dest))

    def test_rejects_absolute_path(self, tmp_path):
        zp = tmp_path / "evil.zip"
        with zipfile.ZipFile(zp, "w") as f:
            f.writestr("/abs/evil.vue", "x")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValueError, match="absolute path"):
            _safe_extract(str(zp), str(dest))

    def test_entry_count_cap(self, tmp_path):
        zp = tmp_path / "many.zip"
        with zipfile.ZipFile(zp, "w") as f:
            for i in range(5):
                f.writestr(f"f{i}.vue", "x")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValueError, match="entries"):
            _safe_extract(str(zp), str(dest), max_entries=3)

    def test_uncompressed_size_cap(self, tmp_path):
        zp = tmp_path / "big.zip"
        with zipfile.ZipFile(zp, "w") as f:
            f.writestr("a.vue", "x" * 1000)
            f.writestr("b.vue", "y" * 1000)
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValueError, match="uncompressed"):
            _safe_extract(str(zp), str(dest), max_total_bytes=1500)

    def test_ok_extract(self, tmp_path, zip_path):
        dest = tmp_path / "out"
        dest.mkdir()
        _safe_extract(zip_path, str(dest))
        assert (dest / "src" / "views" / "A.vue").exists()
