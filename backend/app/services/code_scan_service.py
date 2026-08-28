"""Code scan service: semgrep(Docker) trigger + scan/issue queries + status flow.

WHITE-04: false-positive issues are ignored by fingerprint on re-scan.
"""
import hashlib
import json
import logging
import subprocess
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.whitescan import CodeScan, CodeIssue

logger = logging.getLogger(__name__)


def _run_semgrep(repo_path: str, timeout: int = 300) -> dict:
    """Run semgrep via Docker (spec 方案 B: works on Windows Desktop + Linux).
    First run pulls returntocorp/semgrep image automatically."""
    result = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{repo_path}:/src",
         "returntocorp/semgrep",
         "semgrep", "scan", "--config", "auto", "--json", "/src"],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"semgrep failed (rc={result.returncode}): {result.stderr[:500]}")
    return json.loads(result.stdout)


def _compute_fingerprint(rule_id: str, file_path: str, line_no: int, code: str) -> str:
    """Stable issue fingerprint: rule + location + code hash (WHITE-04)."""
    raw = f"{rule_id}|{file_path}|{line_no}|{code.strip()}"
    return f"{rule_id}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


class CodeScanService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_scan(self, project_id: str, repo_url: str, branch: str = "main") -> dict:
        scan = CodeScan(project_id=UUID(project_id), repo_url=repo_url, branch=branch)
        self.db.add(scan)
        await self.db.commit()
        await self.db.refresh(scan)
        return scan.to_dict()

    async def get_scan(self, scan_id: str) -> Optional[dict]:
        q = select(CodeScan).where(CodeScan.id == UUID(scan_id))
        scan = (await self.db.execute(q)).scalar_one_or_none()
        return scan.to_dict() if scan else None

    async def list_scans(self, project_id: str, page: int = 1, page_size: int = 20) -> dict:
        pid = UUID(project_id)
        total = (await self.db.execute(
            select(func.count()).select_from(CodeScan).where(CodeScan.project_id == pid)
        )).scalar() or 0
        q = (select(CodeScan).where(CodeScan.project_id == pid)
             .order_by(CodeScan.created_at.desc())
             .offset((page - 1) * page_size).limit(page_size))
        rows = (await self.db.execute(q)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [r.to_dict() for r in rows]}

    async def list_issues(self, scan_id: str, severity: Optional[str] = None,
                          status: Optional[str] = None) -> List[dict]:
        q = select(CodeIssue).where(CodeIssue.scan_id == UUID(scan_id))
        if severity:
            q = q.where(CodeIssue.severity == severity)
        if status:
            q = q.where(CodeIssue.status == status)
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def update_issue(self, issue_id: str, status: str,
                           handled_by: str = "system") -> Optional[dict]:
        if status not in ("open", "fixed", "false_positive"):
            raise ValueError(f"invalid status: {status}")
        q = select(CodeIssue).where(CodeIssue.id == UUID(issue_id))
        issue = (await self.db.execute(q)).scalar_one_or_none()
        if not issue:
            return None
        issue.status = status
        issue.handled_by = handled_by
        from datetime import datetime, timezone
        issue.handled_at = datetime.now(timezone.utc)
        await self.db.commit()
        return issue.to_dict()

    async def get_ignored_fingerprints(self, scan_id: str) -> List[str]:
        """Fingerprints previously marked false_positive in this project's scans."""
        q = (
            select(CodeIssue.fingerprint)
            .join(CodeScan, CodeIssue.scan_id == CodeScan.id)
            .where(CodeScan.id == UUID(scan_id),
                   CodeIssue.status == "false_positive")
        )
        rows = (await self.db.execute(q)).all()
        return [r[0] for r in rows if r[0]]

    async def mark_scan_done(self, scan_id: str, *, total: int, high: int,
                             mid: int, low: int, file_count: int,
                             duration_ms: int) -> Optional[dict]:
        q = select(CodeScan).where(CodeScan.id == UUID(scan_id))
        scan = (await self.db.execute(q)).scalar_one_or_none()
        if not scan:
            return None
        scan.status = "done"
        scan.total_issues = total
        scan.high_count = high
        scan.mid_count = mid
        scan.low_count = low
        scan.file_count = file_count
        scan.duration_ms = duration_ms
        await self.db.commit()
        return scan.to_dict()

    async def mark_scan_failed(self, scan_id: str, error_msg: str) -> Optional[dict]:
        q = select(CodeScan).where(CodeScan.id == UUID(scan_id))
        scan = (await self.db.execute(q)).scalar_one_or_none()
        if not scan:
            return None
        scan.status = "failed"
        scan.error_msg = error_msg[:2000]
        await self.db.commit()
        return scan.to_dict()

    # severity mapping: semgrep ERROR/WARNING/INFO -> high/mid/low
    _SEV_MAP = {"ERROR": "high", "WARNING": "mid", "INFO": "low"}

    async def run_scan_sync(self, scan_dict: dict, repo_path: str) -> dict:
        """Synchronous scan orchestration (called by Celery task with its own
        session). scan_dict: create_scan() output."""
        import time

        scan_id = scan_dict["id"]
        started = time.time()
        try:
            ignored = set(await self.get_ignored_fingerprints(scan_id))
            semgrep = _run_semgrep(repo_path)
            counts = {"high": 0, "mid": 0, "low": 0}
            files = set()
            for r in semgrep.get("results", []):
                fp = _compute_fingerprint(
                    r.get("check_id", ""),
                    r.get("path", ""),
                    (r.get("start") or {}).get("line", 0),
                    (r.get("extra") or {}).get("lines", ""),
                )
                if fp in ignored:
                    continue
                sev = self._SEV_MAP.get((r.get("extra") or {}).get("severity", "INFO"), "low")
                counts[sev] += 1
                files.add(r.get("path", ""))
                issue = CodeIssue(
                    scan_id=UUID(scan_id),
                    severity=sev,
                    file_path=r.get("path", ""),
                    line_no=(r.get("start") or {}).get("line"),
                    title=(r.get("check_id", "")).split(".")[-1][:200] or "issue",
                    description=(r.get("extra") or {}).get("message", ""),
                    example_code=(r.get("extra") or {}).get("lines", ""),
                    fingerprint=fp,
                )
                self.db.add(issue)
            duration_ms = int((time.time() - started) * 1000)
            await self.db.commit()
            await self.mark_scan_done(
                scan_id, total=sum(counts.values()),
                high=counts["high"], mid=counts["mid"], low=counts["low"],
                file_count=len(files), duration_ms=duration_ms,
            )
            return {"total_issues": sum(counts.values()),
                    "high_count": counts["high"], "mid_count": counts["mid"],
                    "low_count": counts["low"],
                    "file_count": len(files), "duration_ms": duration_ms}
        except Exception as e:
            await self.mark_scan_failed(scan_id, str(e))
            raise
