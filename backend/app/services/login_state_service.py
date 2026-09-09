"""登录态复用服务（阶段3 T4）：storage_state 生成/缓存/TTL/失效。

设计：登录一次 → storage_state 缓存（内存，按 env_id 键）→ 每条脚本
独立 context 注入免登录；TTL 过期自动重登；执行失败跳登录页 → invalidate。
登录配置存 test_env.credentials["login"]（JSONB）：
{login_url, username_selector, username, password_selector, password,
 submit_selector, success_check, state_ttl_minutes}"""
import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)


class LoginError(Exception):
    """登录失败（配置缺失/凭据错/success_check 未命中）"""


class LoginStateService:
    def __init__(self):
        self._cache: Dict[str, Dict] = {}  # env_id → {state, ts, ttl}

    async def ensure_state(self, env_id: str, credentials: Dict, page,
                           base_url: str = "") -> Dict:
        """确保登录态可用：缓存命中（TTL 内）直接返回；否则走登录流程。"""
        cfg = (credentials or {}).get("login") or {}
        if not cfg.get("login_url"):
            raise LoginError("环境未配置 login 登录块（credentials.login），无法复用登录态")

        cached = self._cache.get(env_id)
        if cached and (time.time() - cached["ts"]) < cached["ttl"] * 60:
            return cached["state"]

        login_url = cfg["login_url"] if cfg["login_url"].startswith("http") else base_url.rstrip("/") + cfg["login_url"]
        await page.goto(login_url)
        await page.locator(cfg["username_selector"]).fill(cfg.get("username", ""))
        await page.locator(cfg["password_selector"]).fill(cfg.get("password", ""))
        await page.locator(cfg["submit_selector"]).click()
        await page.wait_for_timeout(1500)  # 等跳转

        check = cfg.get("success_check", "")
        current = (getattr(page, "url", "") or "")
        if hasattr(page, "content"):
            content = await page.content()
            current += content if isinstance(content, str) else ""
        if check and check not in current:
            raise LoginError(f"登录后未检测到成功标识「{check}」，请检查凭据/选择器配置")

        state = await page.context.storage_state()
        ttl = cfg.get("state_ttl_minutes", 120)
        self._cache[env_id] = {"state": state, "ts": time.time(), "ttl": ttl}
        logger.info(f"登录态已生成并缓存 env={env_id} ttl={ttl}min")
        return state

    async def inject_state(self, state: Dict, page) -> None:
        """把 storage_state 注入 page 所属 context（免登录）。

        cookies 走 add_cookies；localStorage 走 add_init_script（需在导航前生效；JS 生成接线时改用 json.dumps，
        导航后调用则下次导航生效——对登录复用场景足够）。"""
        context = page.context
        if state.get("cookies"):
            await context.add_cookies(state["cookies"])
        origins = state.get("origins") or []
        if origins:
            init_js = ";".join(
                f"try{{for(const [k,v] of Object.entries({o['localStorage']!r} as object)) localStorage.setItem(k,String(v))}}catch(e){{}}"
                for o in origins if o.get("origin") and o.get("localStorage")
            )
            if init_js:
                await context.add_init_script(init_js)

    async def invalidate(self, env_id: str) -> None:
        """失效登录态（执行失败跳登录页时调用）。"""
        self._cache.pop(env_id, None)


# 模块级共享单例（对齐 ai_gateway/redis_client 惯例）：
# TTL 缓存/invalidate 跨执行生效，避免每次执行都重新登录
login_state_service = LoginStateService()
