"""AI fix suggestion service: issue -> AIGateway.chat -> ai_suggestion JSONB."""
import json
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.whitescan import CodeIssue

logger = logging.getLogger(__name__)

_PROMPT = """你是资深安全工程师。针对以下代码问题给出修复建议。

【问题】{title}
【文件】{file_path}:{line_no}
【描述】{description}
【问题代码】
{example_code}

只输出 JSON（不要 markdown 围栏）：
{{"suggestion": "修复思路（一句话）", "fixed_code": "修复后代码", "original_code": "原问题代码"}}"""


class AIFixService:
    def __init__(self, db: AsyncSession, gateway):
        self.db = db
        self.gateway = gateway

    async def generate_fix(self, issue_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        q = select(CodeIssue).where(CodeIssue.id == UUID(issue_id))
        issue = (await self.db.execute(q)).scalar_one_or_none()
        if not issue:
            return None

        messages = [{"role": "user", "content": _PROMPT.format(
            title=issue.title, file_path=issue.file_path,
            line_no=issue.line_no or 0, description=issue.description or "",
            example_code=(issue.example_code or "")[:2000],
        )}]
        try:
            resp = await self.gateway.chat(
                messages,
                project_id=project_id or None,
                stage="whitescan_ai_fix",
            )
        except Exception as e:
            logger.error(f"AI fix gateway call failed: {e}")
            raise

        content = (resp or {}).get("content", "")
        try:
            parsed = json.loads(content)
            suggestion = {
                "suggestion": parsed.get("suggestion", ""),
                "fixed_code": parsed.get("fixed_code", ""),
                "original_code": parsed.get("original_code", issue.example_code or ""),
            }
        except (json.JSONDecodeError, AttributeError):
            # degraded: keep raw text so the user still sees something
            suggestion = {"suggestion": content[:1000], "fixed_code": "", "original_code": ""}

        issue.ai_suggestion = suggestion
        await self.db.commit()
        return issue.to_dict()
