# backend/app/tasks/code_scan_tasks.py
"""Whitescan Celery task: async code scan (git clone -> semgrep -> issues)."""
import logging
import os
import re
import tempfile
import shutil

from app.tasks import celery_app
from app.core.database import AsyncSessionLocal
from app.services.code_scan_service import CodeScanService

logger = logging.getLogger(__name__)


def _run_async(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="code_scan.run_scan")
def run_scan_task(scan_id: str, project_id: str, repo_url: str, branch: str = "main"):
    """Clone repo (shallow) + semgrep + persist issues. DB writes reuse the
    sync-orchestrated service with its own session."""

    # review I6: repo_url is user input — block git option injection (leading
    # '-') and non-https/ssh transports (ext:: RCE). Defense-in-depth beyond
    # the list-form subprocess call.
    if not re.match(r"^(https?://|git@|ssh://)", repo_url):
        raise ValueError(f"repo_url must be http(s)/ssh/git@ URL, got: {repo_url[:100]}")
    if not re.match(r"^[A-Za-z0-9._/\\-]+$", branch):
        raise ValueError(f"invalid branch name: {branch[:50]}")
    repo_path = tempfile.mkdtemp(prefix="whitescan_")
    try:
        import subprocess

        # 进度上报 helper: 每阶段独立 session (进度不因后续阶段失败而丢失)
        def _progress(progress: int, stage: str):
            async def _p():
                async with AsyncSessionLocal() as db:
                    await CodeScanService(db).update_progress(scan_id, progress, stage)
            try:
                _run_async(_p())
            except Exception as e:
                logger.warning(f"progress {progress}% report failed: {e}")

        # 阶段1: docker pull semgrep 镜像 (首次较慢, 10%)
        _progress(10, "pulling")
        subprocess.run(
            ["docker", "pull", "returntocorp/semgrep"],
            capture_output=True, text=True, timeout=600,
        )

        # 阶段2: git clone (30%)
        _progress(30, "clone")
        # '--' separator: repo_url can never be parsed as a git option
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", branch, "--", repo_url, repo_path],
            capture_output=True, text=True, timeout=240,
            env={**os.environ, "GIT_ALLOW_PROTOCOL": "https:http:ssh"},
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed: {clone.stderr[:500]}")

        # 阶段3+4: semgrep 扫描 + 解析入库 (30→90→100, run_scan_sync 内部更新)
        async def _impl():
            async with AsyncSessionLocal() as db:
                svc = CodeScanService(db)
                scan = await svc.get_scan(scan_id)
                if not scan:
                    raise RuntimeError(f"scan {scan_id} not found")
                return await svc.run_scan_sync(scan, repo_path,
                                               progress_cb=_progress)

        return _run_async(_impl())
    except Exception as e:
        logger.error(f"scan task {scan_id} failed: {e}")
        # mark failed with its own session (run may have died mid-way)
        try:
            async def _fail():
                async with AsyncSessionLocal() as db:
                    await CodeScanService(db).mark_scan_failed(scan_id, str(e))
            _run_async(_fail())
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(repo_path, ignore_errors=True)
