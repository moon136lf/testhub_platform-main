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

            def _run():
                _run_async(_p())

            import threading
            try:
                _run_async(_p())
            except RuntimeError:
                # run_scan_sync 的 callback 在 _impl() 的事件循环内被调用，
                # 此处无法再嵌套 loop —— 用独立线程跑，主循环不阻塞等它
                threading.Thread(target=_run, daemon=True).start()
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
        logger.error(f"【白盒扫描】扫描失败 | scan={scan_id} 原因={e} 建议=检查仓库地址可达性与分支")
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


# ---------------- 源码定位器链路（缺口3）: Task 6 双支路编排 ----------------

# 解压安全上限（必查项 d）
MAX_ZIP_ENTRIES = 5000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200MB


def _safe_extract(zip_path: str, dest_dir: str,
                  max_entries: int = MAX_ZIP_ENTRIES,
                  max_total_bytes: int = MAX_UNCOMPRESSED_BYTES) -> None:
    """解压前置校验：路径穿越/绝对路径条目 + 条目数/解压膨胀上限兜底。"""
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if len(names) > max_entries:
            raise ValueError(f"zip entries exceed cap: {len(names)} > {max_entries}")
        total = 0
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or name.startswith("\\"):
                raise ValueError(f"absolute path in zip: {name}")
            norm = os.path.normpath(name)
            if norm.startswith("..") or ":/" in norm or ":\\" in norm:
                raise ValueError(f"path traversal in zip: {name}")
            total += info.file_size
            if total > max_total_bytes:
                raise ValueError(f"zip uncompressed size exceeds cap: {total} > {max_total_bytes}")
        zf.extractall(dest_dir)


def _normalize_prior(prior: dict) -> dict:
    """JSONB 往返后 strategies_by_index 的键会变字符串 "0"——统一转回 int
    （必查项 a：否则 decide_reuse 的 int 键查找静默 miss，hash 增量复用失效）。"""
    for record in (prior or {}).values():
        sbi = record.get("strategies_by_index")
        if isinstance(sbi, dict):
            record["strategies_by_index"] = {
                int(k) if not isinstance(k, int) else k: v for k, v in sbi.items()
            }
    return prior


def _match_route_factory(work_dir: str):
    """路由表匹配工厂：组件名（文件名去后缀）→ 路由 path；无全局态（计划推荐方案）。"""
    try:
        from app.services.code_structure_analyzer import CodeStructureAnalyzer
        routes = CodeStructureAnalyzer().analyze_frontend(work_dir)
    except Exception as e:
        logger.warning(f"【源码定位器】路由表解析失败，全部走 static: 前缀 | {e}")
        routes = []
    by_name = {os.path.splitext(os.path.basename(r.get("name") or ""))[0].lower(): r.get("path")
               for r in routes if r.get("name")}
    return lambda comp: by_name.get((comp.get("component_name") or "").lower())


async def _load_prior_components(project_id: str) -> dict:
    """历史组件 hash + 定位器索引（任务内实现，用 AsyncSessionLocal，StaticScanService 不持 db）。"""
    from sqlalchemy import select as _select
    from app.models.whitescan import StaticScanComponent
    from app.models.element import ElementRepository
    async with AsyncSessionLocal() as db:
        q = _select(StaticScanComponent).where(
            StaticScanComponent.project_id == _uuid(project_id)
        ).order_by(StaticScanComponent.updated_at.desc())
        rows = (await db.execute(q)).scalars().all()
        prior: dict = {}
        for r in rows:
            if r.file_path in prior:
                continue  # 取最近一条
            strategies_by_index: dict = {}
            if r.page_id:
                els = (await db.execute(
                    _select(ElementRepository).where(ElementRepository.page_id == r.page_id)
                )).scalars().all()
                for i, e in enumerate(els):
                    chain = (e.locator_strategies or {}).get("strategies") or []
                    if chain:
                        strategies_by_index[i] = {"strategies": chain}
            prior[r.file_path] = {"content_hash": r.content_hash,
                                  "strategies_by_index": strategies_by_index}
    return _normalize_prior(prior)


async def _record_component(project_id: str, scan_id: str, comp: dict,
                            page_id, reused: bool) -> None:
    """组件 hash 表 upsert（任务内实现，独立 session）。"""
    from sqlalchemy import select as _select
    from app.models.whitescan import StaticScanComponent
    async with AsyncSessionLocal() as db:
        q = _select(StaticScanComponent).where(
            StaticScanComponent.project_id == _uuid(project_id),
            StaticScanComponent.file_path == comp["file_path"])
        row = (await db.execute(q)).scalar_one_or_none()
        fields = dict(
            scan_id=_uuid(scan_id),
            content_hash=comp.get("content_hash"),
            page_id=_uuid(page_id) if isinstance(page_id, str) else page_id,
            element_count=len([e for e in comp.get("elements") or [] if "locator_strategies" in e]),
            ai_generated=not reused and not comp.get("ai_failed"),
            reused=reused,
            ai_failed=bool(comp.get("ai_failed")),
        )
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
        else:
            db.add(StaticScanComponent(
                project_id=_uuid(project_id),
                file_path=comp["file_path"],
                component_name=comp.get("component_name"),
                **fields,
            ))
        await db.commit()


def _uuid(v):
    from uuid import UUID
    return v if isinstance(v, UUID) else UUID(str(v))


async def _locator_branch(scan_id: str, project_id: str, work_dir: str,
                          svc=None, prior_loader=None) -> dict:
    """B 支路编排（svc/prior_loader 可注入供测试）：提取→hash增量→AI→入库→组件记录。
    （zip 已由编排层在支路提交前同步解压到 work_dir，此处不再解压——缺陷2竞态修复）"""
    from app.services.static_scan_service import StaticScanService

    svc = svc or StaticScanService(gateway=_build_gateway())
    prior = await (prior_loader or _load_prior_components)(project_id)
    match_route = _match_route_factory(work_dir)

    comps = svc.extract_components(work_dir)
    imported_total, reused_n, ai_failed_n = 0, 0, 0
    for comp in comps:
        decision = svc.decide_reuse(comp, prior)
        if decision:
            reused_n += 1
        else:
            comp = await svc.generate_component(comp)
            if comp.get("ai_failed"):
                ai_failed_n += 1
        # 路由表命中传 path，未命中 None → import_component 统一走 static: 前缀（必查项 c：单一形态）
        if comp.get("ai_failed"):
            await _record_component(project_id, scan_id, comp, None, reused=False)
            continue
        route_path = match_route(comp)
        async with AsyncSessionLocal() as db:
            page_id, imported, _skipped = await svc.import_component(db, project_id, comp, route_path)
        await _record_component(project_id, scan_id, comp, page_id, reused=bool(decision))
        imported_total += imported
    return {"components": len(comps), "imported": imported_total,
            "reused": reused_n, "ai_failed": ai_failed_n}


def _build_gateway():
    from app.services.ai_gateway import AIGateway
    return AIGateway()


def _a_branch(scan_id: str, work_dir: str) -> dict:
    """A 支路：semgrep（zip 已在 work_dir 解压，直接扫）。"""
    async def _run():
        async with AsyncSessionLocal() as db:
            svc = CodeScanService(db)
            scan = await svc.get_scan(scan_id)
            if not scan:
                raise RuntimeError(f"scan {scan_id} not found")
            return await svc.run_scan_sync(scan, work_dir)
    return _run_async(_run())


def run_locator_scan_task_inner(scan_id: str, project_id: str, zip_path: str,
                                a_branch=None, b_branch=None) -> dict:
    """双支路并行编排（可注入 a/b 支路供测试）。双失败才 raise，单失败另一支路结果有效。

    解压（_safe_extract）在提交双支路之前同步执行——缺陷2：消除 B 支路解压与
    A 支路 semgrep 扫同一 work_dir 的竞态。"""
    from concurrent.futures import ThreadPoolExecutor
    work_dir = tempfile.mkdtemp(prefix="static_scan_work_")
    try:
        # 解压先于支路提交：A 支路扫解压产物，B 支路直接读 work_dir
        _safe_extract(zip_path, work_dir)
        a_branch = a_branch or (lambda: _a_branch(scan_id, work_dir))
        b_branch = b_branch or (lambda: _run_async(
            _locator_branch(scan_id, project_id, work_dir)))
        # B 支路需要 zip 原样（_safe_extract 校验+解压），A 支路扫解压产物
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(a_branch)
            fb = pool.submit(b_branch)
            a_result, b_result = None, None
            a_err, b_err = None, None
            try:
                a_result = fa.result()
            except Exception as e:
                a_err = str(e)
                logger.error(f"【源码定位器】semgrep支路失败 | scan={scan_id}: {e}")
            try:
                b_result = fb.result()
            except Exception as e:
                b_err = str(e)
                logger.error(f"【源码定位器】定位器支路失败 | scan={scan_id}: {e}")
        if a_err and b_err:
            raise RuntimeError(f"both branches failed: a={a_err} b={b_err}")
        # 缺陷1：单支路失败不污染终态——run_scan_sync 的 except 可能已把 scan
        # 标为 failed（A 支路）；此处用独立 session 覆盖回终态 done 并写 error_msg
        if a_err or b_err:
            err_msg = a_err or b_err

            async def _done():
                from app.services.code_scan_service import CodeScanService
                async with AsyncSessionLocal() as db:
                    await CodeScanService(db).mark_scan_done(
                        scan_id, total=0, high=0, mid=0, low=0,
                        file_count=0, duration_ms=0, error_msg=err_msg)
            try:
                _run_async(_done())
            except Exception as e:
                logger.warning(f"【源码定位器】单失败终态覆盖失败 | scan={scan_id}: {e}")
        return {"semgrep": a_result if a_result is not None else {"error": a_err},
                "static": b_result if b_result is not None else {"error": b_err}}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        # 上传暂存目录（Task 5 遗留：成功派发路径端点不删，任务侧统一清理——必查项 b）
        shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)


@celery_app.task(name="code_scan.run_locator_scan")
def run_locator_scan_task(scan_id: str, project_id: str, zip_path: str):
    """zip 上传扫描：A 支路 semgrep 与 B 支路静态定位器并行，互不阻断。

    双失败才 failed；单失败另一支路结果有效。finally 清理解压目录与上传暂存目录。
    """
    logger.info(f"【源码定位器】任务触发 | scan={scan_id} zip={zip_path}")

    def _progress(progress: int, stage: str):
        try:
            async def _p():
                async with AsyncSessionLocal() as db:
                    await CodeScanService(db).update_progress(scan_id, progress, stage)
            _run_async(_p())
        except Exception as e:
            logger.warning(f"progress {progress}% report failed: {e}")

    try:
        _progress(10, "locating")
        result = run_locator_scan_task_inner(scan_id, project_id, zip_path)
        _progress(100, "done")
        return result
    except Exception as e:
        logger.error(f"【源码定位器】扫描失败 | scan={scan_id} 原因={e}")
        try:
            async def _fail():
                async with AsyncSessionLocal() as db:
                    await CodeScanService(db).mark_scan_failed(scan_id, str(e))
            _run_async(_fail())
        except Exception:
            pass
        raise
