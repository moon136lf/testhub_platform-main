"""Scan artifact export: BUG清单.xlsx / issues markdown (WHITE-05 subset)."""
import io
import logging
from typing import List

logger = logging.getLogger(__name__)


class ScanExportService:
    """Stateless exporter; openpyxl imported lazily (already in requirements)."""

    def export_buglist_xlsx(self, issues: List[dict]) -> bytes:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "BUG清单"
        ws.append(["等级", "文件路径", "行号", "标题", "描述", "状态"])
        sev_cn = {"high": "高危", "mid": "中危", "low": "低危"}
        for it in issues:
            ws.append([
                sev_cn.get(it.get("severity"), it.get("severity", "")),
                it.get("file_path", ""), it.get("line_no", ""),
                it.get("title", ""), it.get("description", ""),
                it.get("status", ""),
            ])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def export_issues_markdown(self, issues: List[dict], title: str = "BUG清单") -> str:
        lines = [f"# {title}", ""]
        sev_cn = {"high": "高危", "mid": "中危", "low": "低危"}
        status_cn = {"open": "待处理", "fixed": "已修复", "false_positive": "误报"}
        for it in issues:
            lines.append(f"## [{sev_cn.get(it.get('severity'), '')}] {it.get('title', '')}")
            lines.append(f"- 文件：`{it.get('file_path', '')}:{it.get('line_no', '')}`")
            lines.append(f"- 状态：{status_cn.get(it.get('status'), it.get('status', ''))}")
            if it.get("description"):
                lines.append(f"- 描述：{it['description']}")
            lines.append("")
        return "\n".join(lines)
