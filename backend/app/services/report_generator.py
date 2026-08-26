"""Report generator: Jinja2 HTML + weasyprint PDF + MinIO upload + report_url writeback."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionRecord, ExecutionDetail
from app.core.storage import storage_client
from app.services.notifier import notify_report_ready

logger = logging.getLogger(__name__)

# Import weasyprint at module level so tests can patch `report_generator.HTML`.
# If weasyprint is unavailable, degrade gracefully (PDF skipped at render time).
try:
    from weasyprint import HTML
except Exception:  # pragma: no cover - env-dependent
    HTML = None


def render_template(template_name: str, **context) -> str:
    """Render a Jinja2 template. Imported lazily so tests can mock it."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    import os
    tmpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(tmpl_dir), autoescape=select_autoescape(["html"]))
    tmpl = env.get_template(template_name)
    return tmpl.render(**context)


class ReportGenerator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_report(self, exec_id: str, *, force: bool = False) -> dict:
        rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
        rec = (await self.db.execute(rec_q)).scalar_one_or_none()
        if not rec:
            return None

        # idempotent: skip if already generated unless force
        if rec.report_url and not force:
            return {"html_url": rec.report_url, "pdf_url": self._pdf_key(exec_id), "regenerated": False}

        # fetch fail details
        det_q = (select(ExecutionDetail)
                 .where(ExecutionDetail.execution_record_id == rec.id,
                        ExecutionDetail.status == "fail")
                 .order_by(ExecutionDetail.step))
        details = (await self.db.execute(det_q)).scalars().all()

        env_info = rec.env_info if isinstance(rec.env_info, dict) else {}
        env_str = env_info.get("browser", "-")
        duration_sec = round((rec.duration_ms or 0) / 1000, 1)

        # render HTML
        html = render_template(
            "report.html",
            record=rec.to_dict(),
            details=[d.to_dict() for d in details],
            env_info=env_str,
            duration_sec=duration_sec,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        # render PDF
        try:
            if HTML is None:
                raise ImportError("weasyprint not installed")
            pdf_bytes = HTML(string=html).write_pdf()
        except Exception as e:
            logger.warning(f"weasyprint failed (non-fatal, PDF skipped): {e}")
            pdf_bytes = None

        # upload to MinIO
        html_key = f"reports/{exec_id}.html"
        html_url = await storage_client.upload_bytes(html.encode("utf-8"), html_key)
        if html_url is None:
            html_url = html_key
        pdf_key = None
        if pdf_bytes:
            pdf_key = f"reports/{exec_id}.pdf"
            pdf_url = await storage_client.upload_bytes(pdf_bytes, pdf_key)
            if pdf_url is None:
                pdf_url = pdf_key
        else:
            pdf_url = None

        # write back report_url
        rec.report_url = html_url
        await self.db.commit()

        # notify (P1 stub)
        await notify_report_ready(exec_id, {"html_url": html_url, "pdf_url": pdf_url})

        return {"html_url": html_url, "pdf_url": pdf_url, "regenerated": True}

    def _pdf_key(self, exec_id: str) -> str:
        return f"reports/{exec_id}.pdf"
