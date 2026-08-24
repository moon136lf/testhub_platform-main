"""
AI Gateway Service - Unified interface for multiple AI providers
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class AIProvider(ABC):
    """AI Provider 抽象基类"""

    def __init__(self, api_key: str, api_url: str):
        self.api_key = api_key
        self.api_url = api_url

    @abstractmethod
    async def chat_completion(self, messages: List[Dict], **kwargs) -> Dict:
        """
        聊天补全

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            **kwargs: 额外参数

        Returns:
            {"content": str, "tokens": int}
        """
        pass

    async def generate_embedding(self, text: str) -> List[float]:
        """
        生成文本向量 (Generate text embedding - only supported by Qwen provider)

        Args:
            text: 输入文本

        Returns:
            向量列表

        Raises:
            NotImplementedError: 如果 provider 不支持 embedding
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support embedding")


class GLMProvider(AIProvider):
    """GLM-4 Provider"""

    async def chat_completion(self, messages: List[Dict], **kwargs) -> Dict:
        """GLM-4 聊天补全"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": kwargs.get("model", "glm-4"),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 2000)
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                content = data["choices"][0]["message"]["content"]
                tokens = data["usage"]["total_tokens"]

                logger.info(f"GLM-4 chat completed, tokens: {tokens}")
                return {"content": content, "tokens": tokens}

        except Exception as e:
            logger.error(f"GLM-4 chat failed: {e}")
            raise


class QwenProvider(AIProvider):
    """Qwen Provider"""

    def __init__(self, api_key: str, api_url: str, embedding_url: str):
        super().__init__(api_key, api_url)
        self.embedding_url = embedding_url

    async def chat_completion(self, messages: List[Dict], **kwargs) -> Dict:
        """Qwen 聊天补全"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            # Convert messages to Qwen prompt format
            prompt = self._build_prompt(messages)

            payload = {
                "model": kwargs.get("model", "qwen-plus"),
                "input": {"prompt": prompt},
                "parameters": {
                    "temperature": kwargs.get("temperature", 0.7),
                    "max_tokens": kwargs.get("max_tokens", 2000)
                }
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                content = data["output"]["text"]
                tokens = data["usage"]["total_tokens"]

                logger.info(f"Qwen chat completed, tokens: {tokens}")
                return {"content": content, "tokens": tokens}

        except Exception as e:
            logger.error(f"Qwen chat failed: {e}")
            raise

    async def generate_embedding(self, text: str) -> List[float]:
        """Qwen 生成向量"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "text-embedding-v3",
                "input": {"texts": [text]}
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.embedding_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                embedding = data["output"]["embeddings"][0]["embedding"]

                logger.info(f"Qwen embedding generated, dim: {len(embedding)}")
                return embedding

        except Exception as e:
            logger.error(f"Qwen embedding failed: {e}")
            raise

    def _build_prompt(self, messages: List[Dict]) -> str:
        """将消息列表转换为 Qwen 的 prompt 格式"""
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        return "\n".join(prompt_parts)


class DeepSeekProvider(AIProvider):
    """DeepSeek Provider - OpenAI-compatible API"""

    async def chat_completion(self, messages: List[Dict], **kwargs) -> Dict:
        """DeepSeek 聊天补全"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": kwargs.get("model", "deepseek-chat"),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 2000)
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                content = data["choices"][0]["message"]["content"]
                tokens = data["usage"]["total_tokens"]

                logger.info(f"DeepSeek chat completed, tokens: {tokens}")
                return {"content": content, "tokens": tokens}

        except Exception as e:
            logger.error(f"DeepSeek chat failed: {e}")
            raise


class ClaudeProvider(AIProvider):
    """Claude Provider"""

    async def chat_completion(self, messages: List[Dict], **kwargs) -> Dict:
        """Claude 聊天补全"""
        try:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }

            # Separate system messages
            system_content = ""
            claude_messages = []

            for msg in messages:
                if msg["role"] == "system":
                    system_content = msg["content"]
                else:
                    claude_messages.append(msg)

            payload = {
                "model": kwargs.get("model", "claude-3-5-sonnet-20241022"),
                "messages": claude_messages,
                "max_tokens": kwargs.get("max_tokens", 2000),
                "temperature": kwargs.get("temperature", 0.7)
            }

            if system_content:
                payload["system"] = system_content

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                content = data["content"][0]["text"]
                tokens = data["usage"]["input_tokens"] + data["usage"]["output_tokens"]

                logger.info(f"Claude chat completed, tokens: {tokens}")
                return {"content": content, "tokens": tokens}

        except Exception as e:
            logger.error(f"Claude chat failed: {e}")
            raise


class AIGateway:
    """统一 AI 网关"""

    def __init__(self):
        """初始化所有 providers"""
        self._providers: Dict[str, AIProvider] = {}

        # Initialize GLM-4
        if settings.GLM_API_KEY:
            self._providers["glm-4"] = GLMProvider(
                api_key=settings.GLM_API_KEY,
                api_url=settings.GLM_API_URL
            )

        # Initialize Qwen
        if settings.QWEN_API_KEY:
            self._providers["qwen"] = QwenProvider(
                api_key=settings.QWEN_API_KEY,
                api_url=settings.QWEN_API_URL,
                embedding_url=settings.QWEN_EMBEDDING_URL
            )

        # Initialize DeepSeek
        if settings.DEEPSEEK_API_KEY:
            self._providers["deepseek"] = DeepSeekProvider(
                api_key=settings.DEEPSEEK_API_KEY,
                api_url=settings.DEEPSEEK_API_URL
            )

        # Initialize Claude
        if settings.CLAUDE_API_KEY:
            self._providers["claude"] = ClaudeProvider(
                api_key=settings.CLAUDE_API_KEY,
                api_url=settings.CLAUDE_API_URL
            )

        if not self._providers:
            logger.warning("No AI providers configured - check API keys in config")
        else:
            logger.info(f"AI Gateway initialized with providers: {list(self._providers.keys())}")

    async def chat(
        self,
        messages: List[Dict],
        provider: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """
        聊天接口

        Args:
            messages: 消息列表
            provider: 指定 provider，默认使用配置的默认 provider
            **kwargs: 额外参数

        Returns:
            {"content": str, "tokens": int}
        """
        provider_name = provider or settings.AI_DEFAULT_PROVIDER

        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not available. Check API key configuration in settings.")

        return await self._providers[provider_name].chat_completion(messages, **kwargs)

    async def with_fallback(
        self,
        messages: List[Dict],
        providers: Optional[List[str]] = None,
        **kwargs
    ) -> Dict:
        """
        带 fallback 的聊天接口

        Args:
            messages: 消息列表
            providers: provider 列表，按顺序尝试
            **kwargs: 额外参数

        Returns:
            {"content": str, "tokens": int}
        """
        if providers is None:
            providers = settings.AI_FALLBACK_PROVIDERS.split(",")

        last_error = None

        for provider_name in providers:
            provider_name = provider_name.strip()

            if provider_name not in self._providers:
                logger.warning(f"Provider '{provider_name}' not available, skipping")
                continue

            try:
                logger.info(f"Trying provider: {provider_name}")
                result = await self._providers[provider_name].chat_completion(messages, **kwargs)
                logger.info(f"Provider '{provider_name}' succeeded")
                return result

            except Exception as e:
                logger.warning(f"Provider '{provider_name}' failed: {e}")
                last_error = e
                continue

        # All providers failed
        raise Exception(f"All providers failed. Last error: {last_error}")

    async def embed(
        self,
        text: str,
        provider: Optional[str] = None
    ) -> List[float]:
        """
        生成向量

        Args:
            text: 输入文本
            provider: 指定 provider，默认使用配置的 embedding provider

        Returns:
            向量列表
        """
        provider_name = provider or settings.AI_EMBEDDING_PROVIDER

        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not available")

        return await self._providers[provider_name].generate_embedding(text)


# Global instance
ai_gateway = AIGateway()
