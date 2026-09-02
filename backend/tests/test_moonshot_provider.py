"""MoonshotProvider (kimi2.6 多模态) + GLM glm5.2 升级 测试."""
import asyncio
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def asyncio_run(coro): return asyncio.run(coro)


class TestMoonshotProvider:
    def test_moonshot_text_chat(self):
        from app.services.ai_gateway import MoonshotProvider
        provider = MoonshotProvider(api_key="sk-test", api_url="https://api.moonshot.cn/v1/chat/completions")
        # mock httpx 返回
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "choices": [{"message": {"content": "page.get_by_role(\"button\", name=\"登录\")"}}],
            "usage": {"total_tokens": 120}
        }
        with patch("app.services.ai_gateway.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
            result = asyncio_run(provider.chat_completion(
                [{"role": "user", "content": "找按钮"}], model="kimi-2.6"
            ))
        assert result["content"] == "page.get_by_role(\"button\", name=\"登录\")"
        assert result["tokens"] == 120

    def test_moonshot_multimodal_image(self):
        """多模态: messages content 含 image_url (base64)."""
        from app.services.ai_gateway import MoonshotProvider
        provider = MoonshotProvider(api_key="sk-test", api_url="https://api.moonshot.cn/v1/chat/completions")
        img_b64 = base64.b64encode(b"fake-png").decode()
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "找登录按钮"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]}
        ]
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "choices": [{"message": {"content": "page.get_by_role(\"button\")"}}],
            "usage": {"total_tokens": 200}
        }
        captured = {}
        with patch("app.services.ai_gateway.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=lambda url, json, headers: (captured.update(json=json) or fake_resp)
            )
            result = asyncio_run(provider.chat_completion(messages, model="kimi-2.6"))
        # 验证多模态 messages 原样传给 API
        assert captured["json"]["messages"][0]["content"][1]["type"] == "image_url"
        assert result["tokens"] == 200


class TestGLMModelUpgrade:
    def test_glm_default_model_is_glm52(self):
        from app.services.ai_gateway import GLMProvider
        provider = GLMProvider(api_key="sk", api_url="http://x")
        # mock 看 payload model 默认
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 5}}
        captured = {}
        with patch("app.services.ai_gateway.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=lambda url, json, headers: (captured.update(json=json) or fake_resp)
            )
            asyncio_run(provider.chat_completion([{"role": "user", "content": "hi"}]))
        assert captured["json"]["model"] == "glm-5.2"


class TestAIGatewayRegistersMoonshot:
    def test_gateway_has_moonshot_when_key_set(self):
        from app.services.ai_gateway import AIGateway
        with patch("app.services.ai_gateway.settings") as mock_settings:
            mock_settings.GLM_API_KEY = "glm-key"
            mock_settings.GLM_API_URL = "http://glm"
            mock_settings.MOONSHOT_API_KEY = "moon-key"
            mock_settings.MOONSHOT_API_URL = "https://api.moonshot.cn/v1/chat/completions"
            mock_settings.MOONSHOT_MODEL = "kimi-2.6"
            mock_settings.QWEN_API_KEY = ""
            mock_settings.DEEPSEEK_API_KEY = ""
            mock_settings.CLAUDE_API_KEY = ""
            mock_settings.QWEN_EMBEDDING_URL = ""
            gw = AIGateway()
            assert "moonshot" in gw._providers
            assert "glm-4" in gw._providers  # glm 仍注册(键名不变)

    def test_moonshot_model_from_settings_not_dead(self):
        """审查 #7: settings.MOONSHOT_MODEL 应注入 provider (非死配置)."""
        from app.services.ai_gateway import MoonshotProvider
        provider = MoonshotProvider(api_key="sk", api_url="http://x", model="kimi-custom")
        assert provider.model == "kimi-custom"
        # 未传 model 时默认 kimi-2.6
        provider2 = MoonshotProvider(api_key="sk", api_url="http://x")
        assert provider2.model == "kimi-2.6"
