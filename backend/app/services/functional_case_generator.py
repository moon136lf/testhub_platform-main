"""功能回归用例生成器 (#9 增强): 静态解析代码结构 → AI 批量生成 → 落 test_case.

替换原 regression_case_generator (按安全问题生成). 用户需求: 读取被测系统
前后端代码, 生成每个菜单的功能回归用例 + 基础功能/增删改查用例.
"""
import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.test_case import TestCase
from app.services.code_structure_analyzer import CodeStructureAnalyzer

logger = logging.getLogger(__name__)

MENU_BATCH_SIZE = 3   # 每批菜单数 (一次 AI 调用)
API_BATCH_SIZE = 8    # 每批 API 数
BATCH_SLEEP = 1.0     # 批间隔秒 (避免打爆网关)
NAME_MAX_LEN = 100    # test_case.name 列宽
EXPECTED_MAX_LEN = 200  # test_case.expected_result 列宽
VALID_PRIORITIES = {"P1", "P2"}

# 非业务端点(健康检查/文档/内部通道)不生成接口用例
NOISE_API_PATTERNS = ("health", "ping", "/stream", "/docs", "/openapi", "/redoc", "/static", "/sse",
                      "健康检查", "存活探活", "liveness", "readiness")


class FunctionalCaseGenerator:
    def __init__(self, db, gateway):
        self.db = db
        self.gateway = gateway
        self.analyzer = CodeStructureAnalyzer()

    async def generate_from_repo(self, project_id: str, repo_path: str,
                                 source_id=None) -> dict:
        from app.services.case_batch_service import CaseBatchService
        batch_svc = CaseBatchService(self.db)
        ui_batch = await batch_svc.create_batch(project_id, "whitescan_ui", source_id=source_id)
        api_batch = await batch_svc.create_batch(project_id, "whitescan_api", source_id=source_id)
        menus = self.analyzer.analyze_frontend(repo_path)
        apis = self.analyzer.analyze_backend(repo_path)
        ui_generated, api_generated, failed = 0, 0, 0

        # 菜单批
        for i in range(0, len(menus), MENU_BATCH_SIZE):
            batch = menus[i:i + MENU_BATCH_SIZE]
            ok, n = await self._gen_menu_batch(project_id, batch, batch_id=ui_batch.id)
            ui_generated += n
            failed += 0 if ok else 1
            await asyncio.sleep(BATCH_SLEEP)

        # API 批
        for i in range(0, len(apis), API_BATCH_SIZE):
            batch = apis[i:i + API_BATCH_SIZE]
            ok, n = await self._gen_api_batch(project_id, batch, batch_id=api_batch.id)
            api_generated += n
            failed += 0 if ok else 1
            await asyncio.sleep(BATCH_SLEEP)

        await batch_svc.update_case_count(ui_batch.id, ui_generated)
        await batch_svc.update_case_count(api_batch.id, api_generated)

        return {"generated": ui_generated + api_generated, "failed": failed,
                "menus_found": len(menus), "apis_found": len(apis)}

    async def _gen_menu_batch(self, project_id, batch, batch_id=None) -> tuple:
        prompt = (
            "以下是 Web 系统的前端菜单列表(JSON)。为每个菜单生成 UI 页面功能回归测试用例, "
            "每个菜单 2-5 条, 覆盖: ①页面可访问(菜单点击后正常加载); "
            "②基础增删改查(按菜单业务语义裁剪, 如列表加载/新增/编辑/删除); "
            "③1 条主流程用例(多步操作串联, 从进入到完成关键业务动作)。"
            "只返回 JSON 数组, 每元素: {title, precondition, priority(P1/P2), "
            "steps: [{step, action, expected}]}。菜单列表:\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        return await self._call_and_save(project_id, prompt, "菜单", batch_id=batch_id)

    async def _gen_api_batch(self, project_id, batch, batch_id=None) -> tuple:
        # 过滤健康检查/文档/SSE 等非业务端点
        batch = [a for a in batch
                 if not any(p in f"{a.get('method')} {a.get('path')} {a.get('desc')}".lower()
                            for p in NOISE_API_PATTERNS)]
        if not batch:
            return True, 0
        prompt = (
            "以下是后端 API 端点列表(JSON)。为每个端点生成接口功能测试用例"
            "(正常调用+关键参数校验)。只返回 JSON 数组, 每元素: {title, "
            "precondition, priority(P1/P2), steps: [{step, action, expected}]}。"
            "端点列表:\n" + json.dumps(batch, ensure_ascii=False)
        )
        return await self._call_and_save(project_id, prompt, "API", prefix="[回归-接口]",
                                         batch_id=batch_id)

    async def _call_and_save(self, project_id, prompt, kind, prefix="[回归]",
                             batch_id=None) -> tuple:
        """调 AI → 解析 JSON → 逐条去重落库. 返回 (ok, generated_count)."""
        try:
            resp = await self.gateway.chat([{"role": "user", "content": prompt}],
                                           max_tokens=3000,
                                           stage="functional_case_gen",
                                           project_id=project_id or None)
        except Exception as e:
            logger.warning(f"{kind} batch AI call failed | project_id={project_id} prompt_len={len(prompt)}: {e}")
            return False, 0
        cases = self._parse_json_array(resp.get("content", ""))
        if cases is None:
            return False, 0
        n = 0
        seen_titles: set[str] = set()  # 同批去重, 防唯一约束 IntegrityError
        for c in cases:
            if not isinstance(c, dict) or not c.get("title"):
                continue
            title = f"{prefix} {c.get('title', '')}"[:NAME_MAX_LEN]
            if title in seen_titles or await self._case_title_exists(project_id, title):
                continue
            steps = self._normalize_steps(c.get("steps"))
            expected = steps[-1].get("expected", "") if steps else ""
            priority = c.get("priority")
            if priority not in VALID_PRIORITIES:
                priority = "P2"
            tc = TestCase(
                project_id=project_id,
                name=title,
                priority=priority,
                case_type="functional",
                precondition=c.get("precondition", "已登录系统"),
                steps=steps,
                expected_result=str(expected)[:EXPECTED_MAX_LEN],
                is_finalized=False,
                batch_id=batch_id,
            )
            self.db.add(tc)
            seen_titles.add(title)
            n += 1
        try:
            # savepoint 隔离: 单批 flush 失败只回滚本批, 不影响外层事务(批次行/已落库批)
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError as e:
            logger.warning(f"{kind} batch flush failed (duplicate title): {e}")
            return False, 0
        return True, n

    async def _case_title_exists(self, project_id, title) -> bool:
        r = await self.db.execute(
            select(TestCase.id).where(TestCase.project_id == project_id,
                                      TestCase.name == title,
                                      TestCase.is_deleted.is_(False)).limit(1))
        return r.scalar_one_or_none() is not None

    @staticmethod
    def _normalize_steps(raw) -> list:
        """LLM steps → StepSchema 兼容: 过滤非法项, 重编号 1..n; 全非法返回 []."""
        if not isinstance(raw, list):
            return []
        valid = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            action, expected = s.get("action"), s.get("expected")
            if not isinstance(action, str) or not action.strip():
                continue
            if not isinstance(expected, str) or not expected.strip():
                continue
            valid.append({"step": 0, "action": action[:200], "expected": expected[:200]})
        for i, s in enumerate(valid, 1):
            s["step"] = i
        return valid

    @staticmethod
    def _parse_json_array(raw: str):
        """LLM 输出 → JSON 数组. 取第一个平衡的 [...] (支持嵌套), 失败返回 None 并告警."""
        start = raw.find("[")
        if start == -1:
            logger.warning(f"functional case LLM output has no JSON array: {raw[:200]!r}")
            return None
        depth = 0
        in_str = False
        esc = False
        end = None
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            logger.warning(f"functional case LLM output has unbalanced JSON array: {raw[:200]!r}")
            return None
        try:
            data = json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"functional case LLM output JSON parse failed: {e}; raw: {raw[:200]!r}")
            return None
        return data if isinstance(data, list) else None
