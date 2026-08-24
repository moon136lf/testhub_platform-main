"""
Core configuration settings
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # Application
    APP_NAME: str = "MoonTest"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql://moontest:moontest123@localhost:5432/moontest"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage
    STORAGE_ENDPOINT: str = "http://localhost:9000"
    STORAGE_ACCESS_KEY: str = "admin"
    STORAGE_SECRET_KEY: str = "password123"
    STORAGE_BUCKET: str = "moontest"

    # AI Model
    MODEL_API_URL: str = ""
    MODEL_API_KEY: str = ""
    MODEL_NAME: str = "qwen-plus"
    MODEL_DEBUG_NAME: str = "glm-4"

    # AI Gateway Configuration
    AI_DEFAULT_PROVIDER: str = "glm-4"
    AI_FALLBACK_PROVIDERS: str = "glm-4,qwen,deepseek"
    AI_EMBEDDING_PROVIDER: str = "qwen"

    # GLM-4 Configuration
    GLM_API_KEY: str = ""
    GLM_API_URL: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    # Qwen Configuration
    QWEN_API_KEY: str = ""
    QWEN_API_URL: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    QWEN_EMBEDDING_URL: str = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"

    # DeepSeek Configuration
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/v1/chat/completions"

    # Claude Configuration
    CLAUDE_API_KEY: str = ""
    CLAUDE_API_URL: str = "https://api.anthropic.com/v1/messages"

    # Token Configuration
    TOKEN_QUOTA: int = 100000
    TOKEN_WARNING_RATE: float = 0.1

    # Execution Configuration
    EXECUTION_TIMEOUT: int = 600
    MAX_RETRY_COUNT: int = 3
    SSE_TIMEOUT: int = 1800

    # Self-Healing Configuration
    HEAL_CACHE_TTL_SUCCESS: int = 30
    HEAL_CACHE_TTL_FAIL: int = 1
    HEAL_CONFIDENCE_THRESHOLD: int = 3

    # Security
    JWT_SECRET_KEY: str = "your_jwt_secret_key_change_this_in_production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
