"""
AI Gateway Tests
"""

import pytest
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Add backend directory to path FIRST so real `app` package is importable
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Mock ONLY the specific config/settings dependency (not the whole app package),
# so AIGateway can be imported without real API keys.
mock_settings = MagicMock()
mock_settings.AI_DEFAULT_PROVIDER = "glm-4"
mock_settings.AI_FALLBACK_PROVIDERS = "glm-4,qwen,deepseek"
mock_settings.AI_EMBEDDING_PROVIDER = "qwen"
mock_settings.GLM_API_KEY = ""
mock_settings.GLM_API_URL = "https://test.com"
mock_settings.QWEN_API_KEY = ""
mock_settings.QWEN_API_URL = "https://test.com"
mock_settings.QWEN_EMBEDDING_URL = "https://test.com/embed"
mock_settings.DEEPSEEK_API_KEY = ""
mock_settings.DEEPSEEK_API_URL = "https://test.com"
mock_settings.CLAUDE_API_KEY = ""
mock_settings.CLAUDE_API_URL = "https://test.com"

import importlib.util

# Save real config so the global sys.modules replacement below doesn't leak
# into other test modules (e.g. test_security reads settings.JWT_SECRET_KEY).
_real_config = sys.modules.get('app.core.config')
sys.modules['app.core.config'] = MagicMock(settings=mock_settings)

ai_gateway_path = backend_path / "app" / "services" / "ai_gateway.py"
spec = importlib.util.spec_from_file_location("ai_gateway", ai_gateway_path)
ai_gateway_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_gateway_module)

# Restore the real config module so downstream tests see the genuine settings.
if _real_config is not None:
    sys.modules['app.core.config'] = _real_config
else:
    del sys.modules['app.core.config']

# Import the classes from the loaded module
AIProvider = ai_gateway_module.AIProvider
GLMProvider = ai_gateway_module.GLMProvider
QwenProvider = ai_gateway_module.QwenProvider
DeepSeekProvider = ai_gateway_module.DeepSeekProvider
ClaudeProvider = ai_gateway_module.ClaudeProvider
AIGateway = ai_gateway_module.AIGateway


class TestGLMProvider:
    """测试 GLM-4 Provider"""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_chat_completion_success(self, mock_client_class):
        """测试 GLM-4 聊天成功"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from GLM-4"}}],
            "usage": {"total_tokens": 50}
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = GLMProvider(api_key="test_key", api_url="https://test.com")
        result = await provider.chat_completion([{"role": "user", "content": "Hi"}])

        assert result["content"] == "Hello from GLM-4"
        assert result["tokens"] == 50

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_chat_completion_error(self, mock_client_class):
        """测试 GLM-4 请求失败"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        provider = GLMProvider(api_key="test_key", api_url="https://test.com")

        with pytest.raises(Exception) as exc_info:
            await provider.chat_completion([{"role": "user", "content": "Hi"}])

        assert "API Error" in str(exc_info.value)


class TestQwenProvider:
    """测试 Qwen Provider"""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_chat_completion_success(self, mock_client_class):
        """测试 Qwen 聊天成功"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "output": {"text": "Hello from Qwen"},
            "usage": {"total_tokens": 60}
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = QwenProvider(
            api_key="test_key",
            api_url="https://test.com",
            embedding_url="https://test.com/embed"
        )
        result = await provider.chat_completion([{"role": "user", "content": "Hi"}])

        assert result["content"] == "Hello from Qwen"
        assert result["tokens"] == 60

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_generate_embedding_success(self, mock_client_class):
        """测试 Qwen 生成向量成功"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "output": {"embeddings": [{"embedding": [0.1, 0.2, 0.3]}]}
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = QwenProvider(
            api_key="test_key",
            api_url="https://test.com",
            embedding_url="https://test.com/embed"
        )
        result = await provider.generate_embedding("Test text")

        assert result == [0.1, 0.2, 0.3]


class TestDeepSeekProvider:
    """测试 DeepSeek Provider"""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_chat_completion_success(self, mock_client_class):
        """测试 DeepSeek 聊天成功"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from DeepSeek"}}],
            "usage": {"total_tokens": 45}
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = DeepSeekProvider(api_key="test_key", api_url="https://test.com")
        result = await provider.chat_completion([{"role": "user", "content": "Hi"}])

        assert result["content"] == "Hello from DeepSeek"
        assert result["tokens"] == 45


class TestClaudeProvider:
    """测试 Claude Provider"""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_chat_completion_success(self, mock_client_class):
        """测试 Claude 聊天成功"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "content": [{"text": "Hello from Claude"}],
            "usage": {"input_tokens": 20, "output_tokens": 10}
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = ClaudeProvider(api_key="test_key", api_url="https://test.com")
        result = await provider.chat_completion([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"}
        ])

        assert result["content"] == "Hello from Claude"
        assert result["tokens"] == 30


class TestAIGateway:
    """测试 AI Gateway"""

    @pytest.mark.asyncio
    async def test_chat_with_default_provider(self):
        """测试使用默认 provider 聊天"""
        mock_provider = AsyncMock()
        mock_provider.chat_completion.return_value = {
            "content": "Test response",
            "tokens": 100
        }

        gateway = AIGateway()
        gateway._providers = {"test": mock_provider}

        result = await gateway.chat(
            messages=[{"role": "user", "content": "Hi"}],
            provider="test"
        )

        assert result["content"] == "Test response"
        assert result["tokens"] == 100
        mock_provider.chat_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_fallback_first_succeeds(self):
        """测试 fallback 机制 - 第一个成功"""
        mock_provider1 = AsyncMock()
        mock_provider1.chat_completion.return_value = {
            "content": "Success from provider1",
            "tokens": 50
        }
        mock_provider2 = AsyncMock()

        gateway = AIGateway()
        gateway._providers = {"provider1": mock_provider1, "provider2": mock_provider2}

        result = await gateway.with_fallback(
            messages=[{"role": "user", "content": "Hi"}],
            providers=["provider1", "provider2"]
        )

        assert result["content"] == "Success from provider1"
        mock_provider1.chat_completion.assert_called_once()
        mock_provider2.chat_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_fallback_first_fails_second_succeeds(self):
        """测试 fallback 机制 - 第一个失败，第二个成功"""
        mock_provider1 = AsyncMock()
        mock_provider1.chat_completion.side_effect = Exception("Provider 1 failed")
        mock_provider2 = AsyncMock()
        mock_provider2.chat_completion.return_value = {
            "content": "Success from provider2",
            "tokens": 60
        }

        gateway = AIGateway()
        gateway._providers = {"provider1": mock_provider1, "provider2": mock_provider2}

        result = await gateway.with_fallback(
            messages=[{"role": "user", "content": "Hi"}],
            providers=["provider1", "provider2"]
        )

        assert result["content"] == "Success from provider2"
        mock_provider1.chat_completion.assert_called_once()
        mock_provider2.chat_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_fallback_all_fail(self):
        """测试 fallback 机制 - 全部失败"""
        mock_provider1 = AsyncMock()
        mock_provider1.chat_completion.side_effect = Exception("Provider 1 failed")
        mock_provider2 = AsyncMock()
        mock_provider2.chat_completion.side_effect = Exception("Provider 2 failed")

        gateway = AIGateway()
        gateway._providers = {"provider1": mock_provider1, "provider2": mock_provider2}

        with pytest.raises(Exception) as exc_info:
            await gateway.with_fallback(
                messages=[{"role": "user", "content": "Hi"}],
                providers=["provider1", "provider2"]
            )

        assert "All providers failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_embed_success(self):
        """测试 embedding 成功"""
        mock_provider = AsyncMock()
        mock_provider.generate_embedding.return_value = [0.1, 0.2, 0.3]

        gateway = AIGateway()
        gateway._providers = {"test": mock_provider}

        result = await gateway.embed(text="Test text", provider="test")

        assert result == [0.1, 0.2, 0.3]
        mock_provider.generate_embedding.assert_called_once_with("Test text")

    @pytest.mark.asyncio
    async def test_gateway_init_partial_providers(self):
        """测试部分 provider 配置 - 只有 GLM 和 Qwen 有 API key"""
        # Create a new mock settings with only some API keys set
        partial_settings = MagicMock()
        partial_settings.AI_DEFAULT_PROVIDER = "glm-4"
        partial_settings.AI_FALLBACK_PROVIDERS = "glm-4,qwen,deepseek"
        partial_settings.AI_EMBEDDING_PROVIDER = "qwen"
        partial_settings.GLM_API_KEY = "test-glm-key"
        partial_settings.GLM_API_URL = "https://test.com"
        partial_settings.QWEN_API_KEY = "test-qwen-key"
        partial_settings.QWEN_API_URL = "https://test.com"
        partial_settings.QWEN_EMBEDDING_URL = "https://test.com/embed"
        partial_settings.DEEPSEEK_API_KEY = ""  # Empty - not configured
        partial_settings.DEEPSEEK_API_URL = "https://test.com"
        partial_settings.CLAUDE_API_KEY = ""  # Empty - not configured
        partial_settings.CLAUDE_API_URL = "https://test.com"

        # Mock the config module for this test
        sys.modules['app.core.config'] = MagicMock(settings=partial_settings)

        # Reload the module to pick up new settings
        import importlib.util
        backend_path = Path(__file__).parent.parent
        ai_gateway_path = backend_path / "app" / "services" / "ai_gateway.py"
        spec = importlib.util.spec_from_file_location("ai_gateway_partial", ai_gateway_path)
        ai_gateway_partial = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ai_gateway_partial)

        gateway = ai_gateway_partial.AIGateway()

        # Verify only GLM and Qwen are initialized
        assert "glm-4" in gateway._providers
        assert "qwen" in gateway._providers
        assert "deepseek" not in gateway._providers
        assert "claude" not in gateway._providers
        assert len(gateway._providers) == 2

        # Verify trying to use DeepSeek fails with appropriate error
        with pytest.raises(ValueError) as exc_info:
            await gateway.chat(
                messages=[{"role": "user", "content": "Hi"}],
                provider="deepseek"
            )

        error_msg = str(exc_info.value).lower()
        assert "deepseek" in error_msg
        assert "not available" in error_msg
        assert "check api key" in error_msg

