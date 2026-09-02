"""功能回归用例生成器 (#9 增强): 静态解析代码结构 → AI 批量生成 → 落 test_case.

替换原 regression_case_generator (按安全问题生成). 用户需求: 读取被测系统
前后端代码, 生成每个菜单的功能回归用例 + 基础功能/增删改查用例.
"""
import asyncio
import json
import logging
import re

from app.models.test_case import TestCase
from app.services.code_structure_analyzer import CodeStructureAnalyzer

logger = logging.getLogger(__name__)

MENU_BATCH_SIZE = 3   # 每批菜单数 (一次 AI 调用)
API_BATCH_SIZE = 8    # 每批 API 数
BATCH_SLEEP = 1.0     # 批间隔秒 (避免打爆网关)


class FunctionalCaseGenerator:
    def __init__(self, db, gateway):
        self.db = db
        self.gateway = gateway
        self.analyzer = CodeStructureAnalyzer()

    async def generate_from_repo(self, project_id: str, repo_path: str) -> dict:
        menus = self.analyzer.analyze_frontend(repo_path)
        apis = self.analyzer.analyze_backend(repo_path)
        generated, failed = 0, 0

        # 菜单批
        for i in range(0, len(menus), MENU_BATCH_SIZE):
            batch = menus[i:i + MENU_BATCH_SIZE]
            ok, n = await self._gen_menu_batch(project_id, batch)
            generated += n
            failed += 0 if ok else 1
            await asyncio.sleep(BATCH_SLEEP)

        # API 批
        for i in range(0, len(apis), API_BATCH_SIZE):
            batch = apis[i:i + API_BATCH_SIZE]
            ok, n = await self._gen_api_batch(project_id, batch)
            generated += n
            failed += 0 if ok else 1
            await asyncio.sleep(BATCH_SLEEP)

        return {"generated": generated, "failed": failed,
                "menus_found": len(menus), "apis_found": len(apis)}

    async def _gen_menu_batch(self, project_id, batch) -> tuple:
        prompt = (
            "以下是 Web 系统的前端菜单列表(JSON)。为每个菜单生成功能回归测试用例"
            "(页面可访问+核心功能操作, 如增删改查入口)。"
            "只返回 JSON 数组, 每元素: {title, precondition, priority(P1/P2), "
            "steps: [{step, action, expected}]}。菜单列表:\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        return await self._call_and_save(project_id, prompt, "菜单")

    async def _gen_api_batch(self, project_id, batch) -> tuple:
        prompt = (
            "以下是后端 API 端点列表(JSON)。为每个端点生成接口功能测试用例"
            "(正常调用+关键参数校验)。只返回 JSON 数组, 每元素: {title, "
            "precondition, priority(P1/P2), steps: [{step, action, expected}]}。"
            "端点列表:\n" + json.dumps(batch, ensure_ascii=False)
        )
        return await self._call_and_save(project_id, prompt, "API")

    async def _call_and_save(self, project_id, prompt, kind) -> tuple:
        """调 AI → 解析 JSON → 逐条去重落库. 返回 (ok, generated_count)."""
        try:
            resp = await self.gateway.chat([{"role": "user", "content": prompt}],
                                           max_tokens=3000)
        except Exception as e:
            logger.warning(f"{kind} batch AI call failed: {e}")
            return False, 0
        cases = self._parse_json_array(resp.get("content", ""))
        if cases is None:
            return False, 0
        n = 0
        for c in cases:
            title = f"[回归] {c.get('title', '')}"[:100]
            if not c.get("title") or await self._case_title_exists(project_id, title):
                continue
            tc = TestCase(
                project_id=project_id,
                name=title,
                priority=c.get("priority", "P2"),
                case_type="regression",
                precondition=c.get("precondition", "已登录系统"),
                steps=c.get("steps", []),
                expected_result=c.get("steps", [{}])[-1].get("expected", "") if c.get("steps") else "",
                is_finalized=False,
            )
            self.db.add(tc)
            n += 1
        await self.db.flush()
        return True, n

    async def _case_title_exists(self, project_id, title) -> bool:
        from sqlalchemy import select
        r = await self.db.execute(
            select(TestCase.id).where(TestCase.project_id == project_id,
                                      TestCase.name == title,
                                      TestCase.is_deleted.is_(False)).limit(1))
        return r.scalar_one_or_none() is not None

    @staticmethod
    def _parse_json_array(raw: str):
        """LLM 输出 → JSON 数组. 失败返回 None."""
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, ValueError):
            return None
