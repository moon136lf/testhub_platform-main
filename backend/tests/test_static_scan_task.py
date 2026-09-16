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
    run_locator_scan_task,
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
            result = _run(_locator_branch("scan-1", "proj-1", str(zip_path) + "_work",
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
            result = _run(_locator_branch("scan-1", "proj-1", str(zip_path) + "_work",
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
            result = _run(_locator_branch("scan-1", "proj-1", str(zip_path) + "_work",
                                          svc=svc, prior_loader=prior_loader))
        assert result["ai_failed"] == 1
        assert result["imported"] == 0
        svc.import_component.assert_not_awaited()
        mock_record.assert_awaited_once()  # ai_failed 组件仍落 hash 表


class TestExtractBeforeBranches:
    """缺陷2：解压提前到双支路提交之前同步执行，B 支路内不再解压（消除与 semgrep 的竞态）"""

    def test_extract_done_before_branch_submit(self, zip_path):
        """_safe_extract 在 a_branch 启动前已执行完"""
        import app.tasks.code_scan_tasks as m
        order = []
        work_dir_holder = {}

        def fake_extract(zp, dest):
            order.append("extract")
            work_dir_holder["dest"] = dest
            # 模拟真实解压，A 支路可断言文件已存在
            os.makedirs(os.path.join(dest, "src"), exist_ok=True)

        def a_branch():
            order.append("a")
            assert os.path.isdir(work_dir_holder["dest"]), "解压未在支路提交前完成"
            return {"ok": True}

        b_branch = MagicMock(side_effect=lambda: order.append("b") or {"ok": True})
        with patch.object(m, "_safe_extract", side_effect=fake_extract):
            run_locator_scan_task_inner("scan-1", "proj-1", zip_path,
                                        a_branch=a_branch, b_branch=b_branch)
        assert order[0] == "extract"

    def test_b_branch_no_extract_inside(self, zip_path, fake_db):
        """B 支路内部无解压调用（解压已上移）"""
        svc = _make_svc()
        prior_loader = AsyncMock(return_value={})
        with patch("app.tasks.code_scan_tasks._record_component", AsyncMock()), \
             patch("app.tasks.code_scan_tasks._safe_extract") as mock_ex:
            _run(_locator_branch("scan-1", "proj-1", str(zip_path) + "_work",
                                 svc=svc, prior_loader=prior_loader))
        mock_ex.assert_not_called()


class TestSingleBranchFailureTerminalState:
    """缺陷1：单支路失败时终态应为 done（stage done / progress 100），error_msg 记录该支路错误；双失败才 failed"""

    def _patch_common(self, mock_svc_cls):
        scan = {"id": "scan-1", "project_id": "proj-1"}
        db = MagicMock()
        mock_svc = MagicMock()
        mock_svc.mark_scan_done = AsyncMock(return_value=None)
        mock_svc.get_scan = AsyncMock(return_value=scan)
        mock_svc.update_progress = AsyncMock()
        mock_svc.mark_scan_failed = AsyncMock(return_value=None)
        mock_svc_cls.return_value = mock_svc
        return mock_svc

    def test_a_fail_b_done_terminal(self, zip_path):
        """A 失败 B 成功：终态 done + error_msg 写 A 支路错误"""
        import app.tasks.code_scan_tasks as m
        with patch.object(m, "AsyncSessionLocal", _FakeSessionCM()), \
             patch("app.services.code_scan_service.CodeScanService") as svc_cls:
            mock_svc = self._patch_common(svc_cls)
            result = run_locator_scan_task_inner(
                "scan-1", "proj-1", zip_path,
                a_branch=MagicMock(side_effect=RuntimeError("semgrep boom")),
                b_branch=MagicMock(return_value={"components": 1}),
            )
        assert result["static"] == {"components": 1}
        # 覆盖 A 支路 mark_scan_failed 造成的 failed 终态
        mock_svc.mark_scan_done.assert_awaited_once()
        kwargs = mock_svc.mark_scan_done.await_args.kwargs
        assert kwargs["error_msg"] and "semgrep boom" in kwargs["error_msg"]

    def test_b_fail_a_done_terminal(self, zip_path):
        """B 失败 A 成功：终态 done + error_msg 写 B 支路错误"""
        import app.tasks.code_scan_tasks as m
        with patch.object(m, "AsyncSessionLocal", _FakeSessionCM()), \
             patch("app.services.code_scan_service.CodeScanService") as svc_cls:
            mock_svc = self._patch_common(svc_cls)
            result = run_locator_scan_task_inner(
                "scan-1", "proj-1", zip_path,
                a_branch=MagicMock(return_value={"total": 3}),
                b_branch=MagicMock(side_effect=RuntimeError("locator boom")),
            )
        assert result["semgrep"] == {"total": 3}
        mock_svc.mark_scan_done.assert_awaited_once()
        kwargs = mock_svc.mark_scan_done.await_args.kwargs
        assert kwargs["error_msg"] and "locator boom" in kwargs["error_msg"]


class TestTempCleanupOnFailure:
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
