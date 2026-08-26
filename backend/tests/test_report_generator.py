"""ReportGenerator tests (weasyprint/Jinja2/storage all mocked)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.report_generator import ReportGenerator


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def record_with_detail(mock_db):
    rec = MagicMock()
    rec.id = uuid4()
    rec.exec_id = "EXEC-20260826-1"
    rec.project_id = uuid4()
    rec.exec_type = "ui_regression"
    rec.status = "success"
    rec.total_cases = 10
    rec.passed_count = 8
    rec.fail_count = 2
    rec.pass_rate = 80.0
    rec.duration_ms = 154000
    rec.tokens_used = 3457
    rec.env_info = {"browser": "chromium"}
    rec.report_url = None
    rec.started_at = None
    rec.finished_at = None
    rec.to_dict = MagicMock(return_value={
        "exec_id": "EXEC-20260826-1", "exec_type": "ui_regression", "total_cases": 10,
        "passed_count": 8, "fail_count": 2, "pass_rate": 80.0, "tokens_used": 3457,
        "started_at": None, "env_info": {"browser": "chromium"},
    })
    detail = MagicMock()
    detail.to_dict = MagicMock(return_value={
        "step": 2, "action": "click", "error_type": "locate_failed",
        "error_msg": "not found", "screenshot_url": "http://minio/x.png",
        "stack_trace": "Traceback...",
    })
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[detail])))),
    ]
    return rec


class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_generate_renders_and_uploads(self, mock_db, record_with_detail):
        gen = ReportGenerator(mock_db)
        with patch("app.services.report_generator.render_template", return_value="<html>report</html>") as mock_render, \
             patch("app.services.report_generator.storage_client") as mock_storage, \
             patch("app.services.report_generator.notify_report_ready", new=AsyncMock()):
            mock_storage.upload_bytes = AsyncMock(side_effect=[
                "reports/exec.html", "reports/exec.pdf"
            ])
            with patch("app.services.report_generator.HTML") as mock_html_cls:
                mock_html = MagicMock()
                mock_html.write_pdf.return_value = b"%PDF-fake"
                mock_html_cls.return_value = mock_html
                result = await gen.generate_report("EXEC-20260826-1")
        assert result["html_url"] == "reports/exec.html"
        assert result["pdf_url"] == "reports/exec.pdf"
        assert result["regenerated"] is True
        assert record_with_detail.report_url == "reports/exec.html"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_generate_skips_when_already_generated(self, mock_db, record_with_detail):
        record_with_detail.report_url = "reports/exec.html"
        gen = ReportGenerator(mock_db)
        result = await gen.generate_report("EXEC-20260826-1")
        assert result["regenerated"] is False
        assert result["html_url"] == "reports/exec.html"

    @pytest.mark.asyncio
    async def test_force_regenerates(self, mock_db, record_with_detail):
        record_with_detail.report_url = "reports/old.html"
        gen = ReportGenerator(mock_db)
        with patch("app.services.report_generator.render_template", return_value="<html>new</html>"), \
             patch("app.services.report_generator.storage_client") as mock_storage, \
             patch("app.services.report_generator.notify_report_ready", new=AsyncMock()), \
             patch("app.services.report_generator.HTML") as mock_html_cls:
            mock_storage.upload_bytes = AsyncMock(side_effect=["reports/exec.html", "reports/exec.pdf"])
            mock_html_cls.return_value.write_pdf.return_value = b"%PDF"
            result = await gen.generate_report("EXEC-20260826-1", force=True)
        assert result["regenerated"] is True

    @pytest.mark.asyncio
    async def test_generate_missing_record_returns_none(self, mock_db):
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        gen = ReportGenerator(mock_db)
        assert await gen.generate_report("no-such") is None
