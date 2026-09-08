"""登录态复用：storage_state 生成/缓存/TTL/失效重登（阶段3 T4）"""
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.login_state_service import LoginStateService, LoginError

LOGIN_CFG = {
    "login_url": "/login",
    "username_selector": "input[name=u]", "username": "admin",
    "password_selector": "input[name=p]", "password": "pass",
    "submit_selector": "button[type=submit]",
    "success_check": "dashboard",
    "state_ttl_minutes": 120,
}


def _mock_page(final_url="https://x.com/dashboard", content="<html>dashboard</html>"):
    page = MagicMock()
    page.goto = AsyncMock()
    page.locator.return_value.fill = AsyncMock()
    page.locator.return_value.click = AsyncMock()
    page.url = final_url
    page.content = AsyncMock(return_value=content)
    page.context.storage_state = AsyncMock(return_value={"cookies": [{"name": "sid"}], "origins": []})
    page.wait_for_timeout = AsyncMock()
    return page


class TestLoginState:
    @pytest.mark.asyncio
    async def test_generate_state_via_login_flow(self):
        """首次：走登录流程（goto→fill→click→success_check）→ 返回 storage_state"""
        page = _mock_page()
        svc = LoginStateService()
        state = await svc.ensure_state("env1", {"login": LOGIN_CFG}, page, base_url="https://x.com")
        assert "cookies" in state
        page.goto.assert_any_call("https://x.com/login")
        calls = [c.args[0] for c in page.locator.call_args_list]
        assert "input[name=u]" in calls and "input[name=p]" in calls
        fills = [c.args[0] for c in page.locator.return_value.fill.await_args_list]
        assert "admin" in fills and "pass" in fills

    @pytest.mark.asyncio
    async def test_success_check_fails_raises(self):
        """登录后 success_check 未命中 → LoginError（配置错/凭据错）"""
        page = _mock_page(final_url="https://x.com/login", content="<html>login</html>")
        svc = LoginStateService()
        with pytest.raises(LoginError):
            await svc.ensure_state("env1", {"login": LOGIN_CFG}, page, base_url="https://x.com")

    @pytest.mark.asyncio
    async def test_cache_hit_within_ttl(self):
        """TTL 内二次调用命中缓存不重登"""
        svc = LoginStateService()
        fake_state = {"cookies": [1], "origins": []}
        svc._cache["env1"] = {"state": fake_state, "ts": time.time(), "ttl": 120}
        state = await svc.ensure_state("env1", {"login": LOGIN_CFG}, MagicMock(), base_url="https://x.com")
        assert state == fake_state

    @pytest.mark.asyncio
    async def test_expired_relogins(self):
        """过期 → 重新登录"""
        svc = LoginStateService()
        svc._cache["env1"] = {"state": {"cookies": [1]}, "ts": time.time() - 7200, "ttl": 120}
        page = _mock_page()
        state = await svc.ensure_state("env1", {"login": LOGIN_CFG}, page, base_url="https://x.com")
        page.goto.assert_any_call("https://x.com/login")  # 重新走了登录
        assert state["cookies"] == [{"name": "sid"}]

    @pytest.mark.asyncio
    async def test_invalidate(self):
        svc = LoginStateService()
        svc._cache["env1"] = {"state": {}, "ts": time.time(), "ttl": 1}
        await svc.invalidate("env1")
        assert "env1" not in svc._cache

    @pytest.mark.asyncio
    async def test_missing_login_config_raises(self):
        svc = LoginStateService()
        with pytest.raises(LoginError, match="login"):
            await svc.ensure_state("env1", {}, MagicMock(), base_url="https://x.com")
