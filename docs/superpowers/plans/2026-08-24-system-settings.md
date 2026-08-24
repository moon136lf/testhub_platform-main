# 系统设置（#10）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 #10 系统设置模块的 5 子项（AI设置/运行配置/环境管理/Token成本管理/操作日志），provider 配置可热改，AI 调用统一埋点入 Token 统计，前端补 3 个死链页 + Token 仪表盘 + 预警横幅。

**Architecture:** 后端单 router `system.py`（prefix `/system`）；KV 配置表 system_setting（AI + runtime 共用）+ test_env + token_quota + operation_log + 补建 ai_call_log；ai_gateway 保守加可选埋点参数；Token 用量从 ai_call_log 聚合（used 不存表）；敏感字段 pycryptodome AES 加密。延续 mock 测试策略，无真实 DB/LLM。

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pycryptodome (AES-GCM), pytest, pytest-asyncio, Vue3, Element Plus, ECharts。

**Spec:** `docs/superpowers/specs/2026-08-24-system-settings-design.md`

**测试约定：** 后端测试在 `backend/` 下用 `PYTHONUTF8=1 python -m pytest` 跑（Windows GBK 控制台须加 `PYTHONUTF8=1`，否则 emoji/中文报 UnicodeEncodeError）。conftest.py 已 mock sys.path。无 DB 连接时用 mock AsyncSession；纯算术逻辑直接测。

**Git 约定：** worktree 分支 `worktree-module10-system-settings`。每个 task 末尾 commit。commit message 前缀 `feat(system):`/`fix(system):`/`refactor(system):`/`test(system):`/`chore(system):`。

**并行隔离：** 本会话不碰 `test_case.py`（#4 在改 ScriptAsset）、`ai_case_tasks.py`、`tasks/`、`models/script.py`。`ai_gateway.py` 是共享文件，仅纯加可选参数 + 新私有方法。

---

## File Structure（新建/修改文件总览）

**后端新建：**
- `backend/app/core/security.py` — AES-GCM 加解密 helper（pycryptodome）
- `backend/app/models/system.py` — SystemSetting / TestEnv / TokenQuota / OperationLog model
- `backend/app/schemas/system.py` — 5 子项全部 schema
- `backend/app/services/system_setting_service.py` — KV 读写 + 加解密 + 进程缓存
- `backend/app/services/token_service.py` — 配额/状态聚合/预警
- `backend/app/services/test_env_service.py` — 被测环境 CRUD
- `backend/app/services/operation_log_service.py` — 操作日志 helper
- `backend/app/api/v1/system.py` — 单 router，prefix /system
- `backend/migrations/add_system_settings_tables.sql` — 5 表 idempotent
- `backend/tests/test_security.py`
- `backend/tests/test_system_setting_service.py`
- `backend/tests/test_token_service.py`
- `backend/tests/test_test_env_service.py`
- `backend/tests/test_operation_log_service.py`
- `backend/tests/test_api_system.py`
- `backend/tests/test_ai_gateway_logging.py`

**后端修改：**
- `backend/app/models/__init__.py` — 注册 4 个新 model
- `backend/app/api/__init__.py` — 注册 system router
- `backend/app/services/ai_gateway.py` — chat 加可选 project_id/stage/operator + _log_ai_call（保守）
- `backend/app/services/test_point_generator.py` — 传 project_id/stage
- `backend/app/services/test_case_generator.py` — 传 project_id/stage
- `backend/requirements.txt` — 确认 pycryptodome（已装，无需加）

**前端新建：**
- `frontend/src/api/system.js` — 全部 API 封装
- `frontend/src/views/system/AISettings.vue`
- `frontend/src/views/system/RuntimeConfig.vue`
- `frontend/src/views/system/EnvManagement.vue`
- `frontend/src/views/system/TokenDashboard.vue`
- `frontend/src/components/TokenWarningBanner.vue`

**前端修改：**
- `frontend/src/router/index.js` — 补 4 个路由
- `frontend/src/layouts/MainLayout.vue` — 菜单加 Token成本管理
- `frontend/src/App.vue` — 挂载预警横幅

---

## Task 1: AES 加解密 helper (core/security.py)

**Files:**
- Create: `backend/app/core/security.py`
- Test: `backend/tests/test_security.py`

- [ ] **Step 1: 写失败测试 — 加解密 round-trip + 密钥派生稳定**

Create `backend/tests/test_security.py`:

```python
"""Security helper tests (AES-GCM via pycryptodome)."""
import pytest
from app.core.security import encrypt_value, decrypt_value, derive_key


def test_encrypt_decrypt_roundtrip():
    plain = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
    cipher = encrypt_value(plain)
    assert cipher != plain
    assert decrypt_value(cipher) == plain


def test_encrypt_different_each_call():
    """AES-GCM 随机 nonce，同一明文两次密文不同。"""
    a = encrypt_value("same-secret")
    b = encrypt_value("same-secret")
    assert a != b
    assert decrypt_value(a) == decrypt_value(b) == "same-secret"


def test_derive_key_stable_from_secret():
    """同 secret 派生同 key（PBKDF2 确定性）。"""
    k1 = derive_key("my-jwt-secret")
    k2 = derive_key("my-jwt-secret")
    assert k1 == k2
    assert len(k1) == 32  # AES-256


def test_decrypt_invalid_cipher_raises():
    with pytest.raises(Exception):
        decrypt_value("not-a-valid-cipher")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_security.py -v`
Expected: FAIL（`app.core.security` 不存在）

- [ ] **Step 3: 实现 core/security.py**

Create `backend/app/core/security.py`:

```python
"""
Symmetric encryption for secrets stored in system_setting / test_env.

Uses AES-256-GCM via pycryptodome. Key derived once from JWT_SECRET_KEY
(PBKDF2-HMAC-SHA256, 32 bytes) so no new config key is needed.
"""
import base64
import hashlib
import os

from Crypto.Cipher import AES

from app.core.config import settings

# Fixed salt (not secret; security comes from JWT_SECRET_KEY being private in prod).
_SALT = b"moontest-system-settings-salt"
_PBKDF2_ITER = 100_000


def derive_key(secret: str) -> bytes:
    """Derive a 32-byte AES key from a passphrase via PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _SALT, _PBKDF2_ITER, dklen=32)


def _key() -> bytes:
    return derive_key(settings.JWT_SECRET_KEY)


def encrypt_value(plain: str) -> str:
    """Encrypt a plaintext string. Returns base64(nonce + ciphertext + tag)."""
    nonce = os.urandom(12)
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(plain.encode("utf-8"))
    blob = nonce + ct + tag
    return base64.b64encode(blob).decode("ascii")


def decrypt_value(token: str) -> str:
    """Decrypt a value produced by encrypt_value. Raises on tamper / bad input."""
    blob = base64.b64decode(token)
    nonce, ct, tag = blob[:12], blob[12:-16], blob[-16:]
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ct, tag).decode("utf-8")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_security.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/core/security.py tests/test_security.py
git commit -m "feat(system): AES-GCM encryption helper for secrets (W10)"
```

---

## Task 2: system model (4 张表)

**Files:**
- Create: `backend/app/models/system.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_system_model.py`

- [ ] **Step 1: 写失败测试 — model 字段声明**

Create `backend/tests/test_system_model.py`:

```python
"""System settings model tests."""
from app.models.system import SystemSetting, TestEnv, TokenQuota, OperationLog


def test_system_setting_fields():
    cols = {c.name for c in SystemSetting.__table__.columns}
    assert {"id", "category", "key", "value", "value_encrypted",
            "value_type", "is_secret", "description", "updated_by", "updated_at"} <= cols
    assert "ai" in str(SystemSetting.__table__.c.category.type)
    # unique constraint on (category, key)
    uqs = [str(c) for c in SystemSetting.__table__.constraints
           if c.__class__.__name__ == "UniqueConstraint"]
    assert any("category" in u and "key" in u for u in uqs)


def test_test_env_fields():
    cols = {c.name for c in TestEnv.__table__.columns}
    assert {"id", "name", "url", "env_type", "status", "credentials",
            "created_by", "created_at", "updated_at"} <= cols
    # credentials is JSONB
    assert TestEnv.__table__.c.credentials.type.__class__.__name__ == "JSONB"


def test_token_quota_fields():
    cols = {c.name for c in TokenQuota.__table__.columns}
    assert {"id", "project_id", "total_quota", "alert_threshold", "updated_at"} <= cols
    assert TokenQuota.__table__.c.total_quota.default.arg == 100000
    assert TokenQuota.__table__.c.alert_threshold.default.arg == 10


def test_operation_log_fields():
    cols = {c.name for c in OperationLog.__table__.columns}
    assert {"id", "module", "action", "target_type", "target_id",
            "detail", "operator", "ip", "created_at"} <= cols
    assert OperationLog.__table__.c.detail.type.__class__.__name__ == "JSONB"


def test_models_registered_in_init():
    import app.models as m
    assert hasattr(m, "SystemSetting")
    assert hasattr(m, "TestEnv")
    assert hasattr(m, "TokenQuota")
    assert hasattr(m, "OperationLog")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_system_model.py -v`
Expected: FAIL（`app.models.system` 不存在）

- [ ] **Step 3: 写 models/system.py**

Create `backend/app/models/system.py`:

```python
"""
System settings models: KV config, test env, token quota, operation log.
"""
import uuid

from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class SystemSetting(Base):
    """KV configuration store. category = ai | runtime. Secrets encrypted."""
    __tablename__ = "system_setting"
    __table_args__ = (
        UniqueConstraint("category", "key", name="uq_system_setting_category_key"),
        Index("idx_system_setting_category", "category"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(20), nullable=False)  # ai / runtime
    key = Column(String(100), nullable=False)
    value = Column(Text)
    value_encrypted = Column(Text)
    value_type = Column(String(20), default="string")  # string/int/float/bool/json
    is_secret = Column(Boolean, default=False)
    description = Column(String(500))
    updated_by = Column(String(50))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self, reveal_secret: bool = False) -> dict:
        from app.core.security import decrypt_value
        if self.is_secret:
            shown = None
            if reveal_secret and self.value_encrypted:
                try:
                    shown = decrypt_value(self.value_encrypted)
                except Exception:
                    shown = None
            return {
                "id": str(self.id), "category": self.category, "key": self.key,
                "value": shown if reveal_secret else "***",
                "value_type": self.value_type, "is_secret": True,
                "description": self.description,
                "updated_by": self.updated_by,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }
        return {
            "id": str(self.id), "category": self.category, "key": self.key,
            "value": self.value,
            "value_type": self.value_type, "is_secret": False,
            "description": self.description,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TestEnv(Base):
    """Target test environment (dev/staging/prod)."""
    __tablename__ = "test_env"
    __table_args__ = (
        Index("idx_test_env_type", "env_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False)
    url = Column(String(500), nullable=False)
    env_type = Column(String(20), nullable=False, default="dev")  # dev/staging/prod
    status = Column(String(20), default="active")  # active/inactive
    credentials = Column(JSONB)  # encrypted-sensitive fields kept as JSON with encrypted values
    created_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self, reveal_secret: bool = False) -> dict:
        return {
            "id": str(self.id), "name": self.name, "url": self.url,
            "env_type": self.env_type, "status": self.status,
            "credentials": self.credentials or {},
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TokenQuota(Base):
    """Per-project token quota. `used` is aggregated from ai_call_log, not stored."""
    __tablename__ = "token_quota"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_token_quota_project"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    total_quota = Column(Integer, default=100000)
    alert_threshold = Column(Integer, default=10)  # percentage
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id), "project_id": str(self.project_id),
            "total_quota": self.total_quota, "alert_threshold": self.alert_threshold,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OperationLog(Base):
    """Operation audit log."""
    __tablename__ = "operation_log"
    __table_args__ = (
        Index("idx_op_log_created", "created_at"),
        Index("idx_op_log_module", "module"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    target_type = Column(String(50))
    target_id = Column(String(100))
    detail = Column(JSONB)
    operator = Column(String(50))
    ip = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id), "module": self.module, "action": self.action,
            "target_type": self.target_type, "target_id": self.target_id,
            "detail": self.detail, "operator": self.operator, "ip": self.ip,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

- [ ] **Step 4: 注册到 models/__init__.py**

Modify `backend/app/models/__init__.py`，在 import 区加：

```python
from app.models.system import SystemSetting, TestEnv, TokenQuota, OperationLog
```

`__all__` 列表加 `"SystemSetting"`, `"TestEnv"`, `"TokenQuota"`, `"OperationLog"`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_system_model.py -v`
Expected: PASS（5 tests）

- [ ] **Step 6: 跑全量确认无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（无回归）

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/models/system.py app/models/__init__.py tests/test_system_model.py
git commit -m "feat(system): SystemSetting/TestEnv/TokenQuota/OperationLog models (W10)"
```

---

## Task 3: 幂等迁移脚本

**Files:**
- Create: `backend/migrations/add_system_settings_tables.sql`

- [ ] **Step 1: 写迁移脚本**

Create `backend/migrations/add_system_settings_tables.sql`:

```sql
-- W10: system settings tables (idempotent)
-- 1. system_setting
CREATE TABLE IF NOT EXISTS system_setting (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(20) NOT NULL,
    key VARCHAR(100) NOT NULL,
    value TEXT,
    value_encrypted TEXT,
    value_type VARCHAR(20) DEFAULT 'string',
    is_secret BOOLEAN DEFAULT FALSE,
    description VARCHAR(500),
    updated_by VARCHAR(50),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_system_setting_category_key') THEN
    ALTER TABLE system_setting ADD CONSTRAINT uq_system_setting_category_key UNIQUE (category, key);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_system_setting_category ON system_setting(category);

-- 2. test_env
CREATE TABLE IF NOT EXISTS test_env (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL,
    url VARCHAR(500) NOT NULL,
    env_type VARCHAR(20) NOT NULL DEFAULT 'dev',
    status VARCHAR(20) DEFAULT 'active',
    credentials JSONB,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_test_env_type ON test_env(env_type);

-- 3. token_quota
CREATE TABLE IF NOT EXISTS token_quota (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    total_quota INTEGER DEFAULT 100000,
    alert_threshold INTEGER DEFAULT 10,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_token_quota_project') THEN
    ALTER TABLE token_quota ADD CONSTRAINT uq_token_quota_project UNIQUE (project_id);
  END IF;
END $$;

-- 3a. default quota row for every existing project
INSERT INTO token_quota (project_id, total_quota, alert_threshold)
SELECT p.id, 100000, 10
FROM project p
WHERE NOT EXISTS (
  SELECT 1 FROM token_quota tq WHERE tq.project_id = p.id
);

-- 4. operation_log
CREATE TABLE IF NOT EXISTS operation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(100),
    detail JSONB,
    operator VARCHAR(50),
    ip VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_op_log_created ON operation_log(created_at);
CREATE INDEX IF NOT EXISTS idx_op_log_module ON operation_log(module);

-- 5. ai_call_log (model exists in execution.py:54, table never created before)
CREATE TABLE IF NOT EXISTS ai_call_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
    model VARCHAR(50) NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    tokens_cost NUMERIC(10,4) DEFAULT 0,
    stage VARCHAR(30) NOT NULL,
    status VARCHAR(20) DEFAULT 'success',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_project ON ai_call_log(project_id);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_created ON ai_call_log(created_at);
```

- [ ] **Step 2: 验证文件存在（无 DB 时不执行）**

Run: `cd backend && ls migrations/add_system_settings_tables.sql`
Expected: 列出文件

- [ ] **Step 3: Commit**

```bash
cd backend
git add migrations/add_system_settings_tables.sql
git commit -m "feat(system): idempotent migration for 5 tables (W10)"
```

---

## Task 4: system schema

**Files:**
- Create: `backend/app/schemas/system.py`

- [ ] **Step 1: 写 schema**

Create `backend/app/schemas/system.py`:

```python
"""System settings schemas."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ---- system_setting ----
class SettingUpdate(BaseModel):
    value: str
    value_type: str = Field("string", pattern="^(string|int|float|bool|json)$")
    is_secret: bool = False
    description: Optional[str] = Field(None, max_length=500)
    updated_by: Optional[str] = Field(None, max_length=50)


class SettingResponse(BaseModel):
    id: str
    category: str
    key: str
    value: Optional[Any] = None
    value_type: str = "string"
    is_secret: bool = False
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class TestConnectionRequest(BaseModel):
    provider: str = Field(..., description="provider name: glm-4/qwen/deepseek/claude")


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None


# ---- runtime config ----
class RuntimeConfigResponse(BaseModel):
    """Aggregated runtime config for display."""
    heal_strategy: str = "SMART"
    heal_confidence_threshold: int = 3
    heal_cache_ttl_success: int = 30
    heal_cache_ttl_fail: int = 1
    execution_timeout: int = 600
    max_retry_count: int = 3
    sse_timeout: int = 1800
    model_config = ConfigDict(from_attributes=True)


# ---- test_env ----
class TestEnvCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    url: str = Field(..., min_length=1, max_length=500)
    env_type: str = Field("dev", pattern="^(dev|staging|prod)$")
    status: str = Field("active", pattern="^(active|inactive)$")
    credentials: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = Field(None, max_length=50)


class TestEnvUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    url: Optional[str] = Field(None, min_length=1, max_length=500)
    env_type: Optional[str] = Field(None, pattern="^(dev|staging|prod)$")
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")
    credentials: Optional[Dict[str, Any]] = None


class TestEnvResponse(BaseModel):
    id: str
    name: str
    url: str
    env_type: str
    status: str
    credentials: Dict[str, Any] = {}
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ---- operation_log ----
class OperationLogResponse(BaseModel):
    id: str
    module: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    operator: Optional[str] = None
    ip: Optional[str] = None
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ---- token ----
class TokenQuotaUpdate(BaseModel):
    total_quota: Optional[int] = Field(None, ge=0)
    alert_threshold: Optional[int] = Field(None, ge=0, le=100)


class TokenQuotaResponse(BaseModel):
    project_id: str
    total_quota: int
    alert_threshold: int
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class TokenStatusResponse(BaseModel):
    """Aligned with requirement §9.2.6."""
    total_quota: int
    used: int
    remaining: int
    percentage: float
    is_warning: bool
    warning_threshold: int
    recent_daily_avg: float
    estimated_days_remaining: Optional[int] = None


class TokenUsageItem(BaseModel):
    label: str  # stage or model
    tokens: int
    model_config = ConfigDict(from_attributes=True)


class TokenUsageResponse(BaseModel):
    by_stage: List[TokenUsageItem]
    by_model: List[TokenUsageItem]
    daily: List[Dict[str, Any]]  # [{date, tokens}]
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: 验证可导入**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.schemas.system import SettingResponse, TokenStatusResponse, TestEnvCreate; print('schemas OK')"`
Expected: `schemas OK`

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/schemas/system.py
git commit -m "feat(system): pydantic schemas for settings/env/tokens/oplog (W10)"
```

---

## Task 5: SystemSettingService (KV + 加解密 + 缓存)

**Files:**
- Create: `backend/app/services/system_setting_service.py`
- Test: `backend/tests/test_system_setting_service.py`

- [ ] **Step 1: 写失败测试 — KV 读写 + 加解密 + 缓存失效**

Create `backend/tests/test_system_setting_service.py`:

```python
"""SystemSettingService tests."""
import time
import pytest
from unittest.mock import AsyncMock, Mock

from app.services.system_setting_service import SystemSettingService, _settings_cache


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = Mock()
    db.refresh = AsyncMock()
    _settings_cache.clear()  # reset cache between tests
    return db


class TestGetSet:
    @pytest.mark.asyncio
    async def test_get_plain_value(self, mock_db):
        row = Mock()
        row.id = "id1"; row.category = "runtime"; row.key = "heal.strategy"
        row.value = "SMART"; row.value_encrypted = None
        row.value_type = "string"; row.is_secret = False
        row.description = None; row.updated_by = None; row.updated_at = None
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))

        svc = SystemSettingService(mock_db)
        val = await svc.get("heal.strategy")
        assert val == "SMART"

    @pytest.mark.asyncio
    async def test_get_secret_value_decrypts(self, mock_db):
        from app.core.security import encrypt_value
        cipher = encrypt_value("sk-real-key")
        row = Mock()
        row.id = "id2"; row.category = "ai"; row.key = "glm-4.api_key"
        row.value = None; row.value_encrypted = cipher
        row.value_type = "string"; row.is_secret = True
        row.description = None; row.updated_by = None; row.updated_at = None
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))

        svc = SystemSettingService(mock_db)
        val = await svc.get("glm-4.api_key")
        assert val == "sk-real-key"

    @pytest.mark.asyncio
    async def test_get_missing_returns_default(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = SystemSettingService(mock_db)
        assert await svc.get("no.such.key", default="fallback") == "fallback"

    @pytest.mark.asyncio
    async def test_set_plain_persists_and_invalidates_cache(self, mock_db):
        # cache has stale value
        _settings_cache.set(("runtime", "heal.strategy"), "OLD", time.time() + 60)
        row = Mock()
        row.id = "id1"; row.category = "runtime"; row.key = "heal.strategy"
        row.value = "OLD"; row.value_encrypted = None
        row.value_type = "string"; row.is_secret = False
        row.description = None; row.updated_by = None; row.updated_at = None
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))

        svc = SystemSettingService(mock_db)
        await svc.set("runtime", "heal.strategy", "SMART", value_type="string", updated_by="admin")

        # cache entry for this key removed
        assert ("runtime", "heal.strategy") not in _settings_cache
        # row value updated + committed
        assert row.value == "SMART"
        assert row.is_secret is False
        assert mock_db.commit.called


class TestCache:
    @pytest.mark.asyncio
    async def test_cache_hits_avoid_db(self, mock_db):
        # prime cache
        _settings_cache.set(("runtime", "heal.strategy"), "SMART", time.time() + 60)
        svc = SystemSettingService(mock_db)
        val = await svc.get("heal.strategy", category="runtime")
        assert val == "SMART"
        # db.execute NOT called (cache hit)
        assert not mock_db.execute.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_system_setting_service.py -v`
Expected: FAIL（service 不存在）

- [ ] **Step 3: 实现 service**

Create `backend/app/services/system_setting_service.py`:

```python
"""System setting KV service with encryption + process cache."""
import time
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemSetting
from app.core.security import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

# Module-level process cache: (category, key) -> (value, expiry_ts)
_settings_cache: dict = {}
_CACHE_TTL = 30  # seconds


class SystemSettingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str, *, category: Optional[str] = None, default=None):
        """Get a setting value (decrypted if secret). Uses process cache (30s TTL)."""
        cat = category or self._guess_category(key)
        cached = _settings_cache.get((cat, key))
        if cached and cached[1] > time.time():
            return cached[0]

        row = await self._fetch_row(cat, key)
        if not row:
            return default
        val = self._read_value(row)
        _settings_cache[(cat, key)] = (val, time.time() + _CACHE_TTL)
        return val

    async def list(self, category: str):
        """List settings in a category (secrets masked)."""
        q = select(SystemSetting).where(SystemSetting.category == category)
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict(reveal_secret=False) for r in rows]

    async def set(self, category: str, key: str, value, *,
                  value_type: str = "string", is_secret: bool = False,
                  description: Optional[str] = None, updated_by: Optional[str] = None):
        """Upsert a setting. Encrypts if is_secret. Invalidates cache for the key."""
        row = await self._fetch_row(category, key)
        if row is None:
            row = SystemSetting(category=category, key=key)
            self.db.add(row)
        if is_secret:
            row.value = None
            row.value_encrypted = encrypt_value(str(value))
        else:
            row.value = str(value)
            row.value_encrypted = None
        row.value_type = value_type
        row.is_secret = is_secret
        if description is not None:
            row.description = description
        if updated_by:
            row.updated_by = updated_by
        await self.db.commit()
        # invalidate cache
        _settings_cache.pop((category, key), None)
        return row

    async def delete(self, category: str, key: str) -> bool:
        row = await self._fetch_row(category, key)
        if not row:
            return False
        await self.db.delete(row)
        await self.db.commit()
        _settings_cache.pop((category, key), None)
        return True

    # ---- internals ----
    async def _fetch_row(self, category: str, key: str) -> Optional[SystemSetting]:
        q = select(SystemSetting).where(
            SystemSetting.category == category,
            SystemSetting.key == key,
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    def _read_value(self, row: SystemSetting):
        if row.is_secret and row.value_encrypted:
            try:
                return decrypt_value(row.value_encrypted)
            except Exception as e:
                logger.warning(f"Failed to decrypt setting {row.key}: {e}")
                return None
        # cast by value_type
        v = row.value
        if v is None:
            return None
        if row.value_type == "int":
            try: return int(v)
            except ValueError: return v
        if row.value_type == "float":
            try: return float(v)
            except ValueError: return v
        if row.value_type == "bool":
            return v.lower() in ("true", "1", "yes")
        return v

    def _guess_category(self, key: str) -> str:
        """Heuristic: ai.* keys -> ai, else runtime."""
        # provider keys like 'glm-4.api_key' or 'ai.default_provider'
        if key.startswith("ai.") or any(seg in key for seg in (".api_key", ".api_url")):
            return "ai"
        return "runtime"


def clear_cache():
    """Clear the whole process cache (used after bulk config changes)."""
    _settings_cache.clear()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_system_setting_service.py -v`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/system_setting_service.py tests/test_system_setting_service.py
git commit -m "feat(system): SystemSettingService KV + encryption + cache (W10)"
```

---

## Task 6: TestEnvService + OperationLogService

**Files:**
- Create: `backend/app/services/test_env_service.py`
- Create: `backend/app/services/operation_log_service.py`
- Test: `backend/tests/test_test_env_service.py`
- Test: `backend/tests/test_operation_log_service.py`

- [ ] **Step 1: 写失败测试 — env CRUD + oplog**

Create `backend/tests/test_test_env_service.py`:

```python
"""TestEnvService tests."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.services.test_env_service import TestEnvService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = Mock()
    db.refresh = AsyncMock()
    return db


class TestEnvCRUD:
    @pytest.mark.asyncio
    async def test_list_returns_all(self, mock_db):
        e1 = Mock(); e1.to_dict = Mock(return_value={"id": "1", "name": "dev"})
        e2 = Mock(); e2.to_dict = Mock(return_value={"id": "2", "name": "staging"})
        mock_db.execute.return_value = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[e1, e2]))))
        svc = TestEnvService(mock_db)
        result = await svc.list()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_create_persists(self, mock_db):
        async def fake_refresh(obj):
            obj.id = uuid4()
        mock_db.refresh.side_effect = fake_refresh
        svc = TestEnvService(mock_db)
        env = await svc.create({"name": "dev-env", "url": "http://x", "env_type": "dev",
                                "status": "active", "credentials": {}, "created_by": "admin"})
        assert mock_db.add.called
        assert mock_db.commit.called
        assert env["name"] == "dev-env"

    @pytest.mark.asyncio
    async def test_update_applies_fields(self, mock_db):
        env = Mock()
        env.to_dict = Mock(return_value={"id": "1", "name": "new", "url": "http://y"})
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=env))
        svc = TestEnvService(mock_db)
        result = await svc.update("1", {"name": "new", "url": "http://y"})
        assert env.name == "new"
        assert env.url == "http://y"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = TestEnvService(mock_db)
        assert await svc.update("1", {"name": "x"}) is None

    @pytest.mark.asyncio
    async def test_delete_soft(self, mock_db):
        env = Mock()
        env.status = "active"
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=env))
        svc = TestEnvService(mock_db)
        ok = await svc.delete("1")
        assert ok is True
        assert env.status == "inactive"
        assert mock_db.commit.called
```

Create `backend/tests/test_operation_log_service.py`:

```python
"""OperationLogService tests."""
import pytest
from unittest.mock import AsyncMock, Mock

from app.services.operation_log_service import OperationLogService, log_operation


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = Mock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_log_operation_persists(mock_db):
    svc = OperationLogService(mock_db)
    await svc.log("system", "update_setting", target_type="setting", target_id="heal.strategy",
                  detail={"old": "HEURISTIC", "new": "SMART"}, operator="admin", ip="127.0.0.1")
    assert mock_db.add.called
    added = mock_db.add.call_args[0][0]
    assert added.module == "system"
    assert added.action == "update_setting"
    assert added.detail["new"] == "SMART"
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_log_failure_does_not_raise(mock_db):
    """Log failure must not break the caller's flow."""
    mock_db.commit.side_effect = Exception("db down")
    svc = OperationLogService(mock_db)
    # should NOT raise
    await svc.log("system", "x", target_type=None, target_id=None,
                  detail=None, operator=None, ip=None)


@pytest.mark.asyncio
async def test_module_level_helper(mock_db, monkeypatch):
    """log_operation module helper wraps the service."""
    called = {}
    class FakeFactory:
        def __call__(self, db):
            svc = OperationLogService(db)
            svc.log = AsyncMock(return_value=None)
            called["svc"] = svc
            return svc
    import app.services.operation_log_service as mod
    monkeypatch.setattr(mod, "_build_service", FakeFactory())
    await log_operation(mock_db, "system", "create_env", "test_env", "1", {"name": "dev"}, "admin")
    assert called["svc"].log.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_test_env_service.py tests/test_operation_log_service.py -v`
Expected: FAIL（services 不存在）

- [ ] **Step 3: 实现 TestEnvService**

Create `backend/app/services/test_env_service.py`:

```python
"""Test environment CRUD service."""
import logging
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import TestEnv

logger = logging.getLogger(__name__)


class TestEnvService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self) -> list:
        q = select(TestEnv).order_by(TestEnv.created_at.desc())
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def get(self, env_id: str) -> Optional[dict]:
        q = select(TestEnv).where(TestEnv.id == UUID(env_id))
        row = (await self.db.execute(q)).scalar_one_or_none()
        return row.to_dict() if row else None

    async def create(self, data: Dict[str, Any]) -> dict:
        env = TestEnv(
            name=data["name"], url=data["url"], env_type=data.get("env_type", "dev"),
            status=data.get("status", "active"), credentials=data.get("credentials"),
            created_by=data.get("created_by", "system"),
        )
        self.db.add(env)
        await self.db.commit()
        await self.db.refresh(env)
        return env.to_dict()

    async def update(self, env_id: str, data: Dict[str, Any]) -> Optional[dict]:
        q = select(TestEnv).where(TestEnv.id == UUID(env_id))
        env = (await self.db.execute(q)).scalar_one_or_none()
        if not env:
            return None
        for f in ("name", "url", "env_type", "status", "credentials"):
            if f in data and data[f] is not None:
                setattr(env, f, data[f])
        await self.db.commit()
        await self.db.refresh(env)
        return env.to_dict()

    async def delete(self, env_id: str) -> bool:
        q = select(TestEnv).where(TestEnv.id == UUID(env_id))
        env = (await self.db.execute(q)).scalar_one_or_none()
        if not env:
            return False
        env.status = "inactive"  # soft delete
        await self.db.commit()
        return True
```

Create `backend/app/services/operation_log_service.py`:

```python
"""Operation log service. Best-effort: logging failure must not break callers."""
import logging
from typing import Optional, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import OperationLog

logger = logging.getLogger(__name__)


class OperationLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(self, module: str, action: str, *,
                  target_type: Optional[str] = None, target_id: Optional[str] = None,
                  detail: Optional[Any] = None, operator: Optional[str] = None,
                  ip: Optional[str] = None):
        try:
            entry = OperationLog(
                module=module, action=action, target_type=target_type,
                target_id=target_id, detail=detail, operator=operator or "system", ip=ip,
            )
            self.db.add(entry)
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Operation log failed (non-blocking): {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass


def _build_service(db: AsyncSession) -> OperationLogService:
    return OperationLogService(db)


async def log_operation(db: AsyncSession, module: str, action: str,
                        target_type=None, target_id=None, detail=None,
                        operator=None, ip=None):
    """Module-level convenience helper."""
    svc = _build_service(db)
    await svc.log(module, action, target_type=target_type, target_id=target_id,
                  detail=detail, operator=operator, ip=ip)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_test_env_service.py tests/test_operation_log_service.py -v`
Expected: PASS（8 tests）

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/test_env_service.py app/services/operation_log_service.py tests/test_test_env_service.py tests/test_operation_log_service.py
git commit -m "feat(system): TestEnvService + OperationLogService (W10)"
```

---

## Task 7: TokenService (配额 + 状态聚合 + 预警)

**Files:**
- Create: `backend/app/services/token_service.py`
- Test: `backend/tests/test_token_service.py`

- [ ] **Step 1: 写失败测试 — 聚合算术**

Create `backend/tests/test_token_service.py`:

```python
"""TokenService tests — pure arithmetic with mocked db."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.services.token_service import TokenService


def _mock_scalar(value):
    """Mock a result whose .scalar() returns value."""
    return Mock(scalar=Mock(return_value=value))


def _mock_scalars(values):
    return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=values))))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_basic_status_no_warning(self, mock_db):
        pid = str(uuid4())
        # 1st execute: token_quota row -> total 100000, threshold 10
        quota_row = Mock(); quota_row.total_quota = 100000; quota_row.alert_threshold = 10
        # 2nd: SUM tokens_used -> 5000
        # 3rd: recent 7-day sum -> 7000
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=quota_row)),
            _mock_scalar(5000),
            _mock_scalar(7000),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.total_quota == 100000
        assert st.used == 5000
        assert st.remaining == 95000
        assert st.percentage == pytest.approx(5.0, abs=0.01)
        assert st.is_warning is False
        assert st.recent_daily_avg == pytest.approx(1000.0, abs=0.01)
        assert st.estimated_days_remaining == 95

    @pytest.mark.asyncio
    async def test_warning_when_below_threshold(self, mock_db):
        pid = str(uuid4())
        quota_row = Mock(); quota_row.total_quota = 100000; quota_row.alert_threshold = 10
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=quota_row)),
            _mock_scalar(95000),  # used 95000 -> remaining 5000 -> 5% <= 10% -> warning
            _mock_scalar(7000),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.is_warning is True
        assert st.remaining == 5000

    @pytest.mark.asyncio
    async def test_no_quota_row_uses_default(self, mock_db):
        """No token_quota row -> default 100000 from settings.TOKEN_QUOTA."""
        pid = str(uuid4())
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=None)),
            _mock_scalar(0),
            _mock_scalar(0),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.total_quota == 100000
        assert st.used == 0
        assert st.is_warning is False
        # daily avg 0 -> estimated_days_remaining None
        assert st.estimated_days_remaining is None

    @pytest.mark.asyncio
    async def test_zero_usage_no_warning(self, mock_db):
        pid = str(uuid4())
        quota_row = Mock(); quota_row.total_quota = 100000; quota_row.alert_threshold = 10
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=quota_row)),
            _mock_scalar(0),
            _mock_scalar(0),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.used == 0
        assert st.is_warning is False


class TestQuotaUpsert:
    @pytest.mark.asyncio
    async def test_update_quota_creates_if_missing(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = TokenService(mock_db)
        await svc.update_quota(str(uuid4()), total_quota=200000, alert_threshold=15)
        assert mock_db.add.called
        added = mock_db.add.call_args[0][0]
        assert added.total_quota == 200000
        assert added.alert_threshold == 15

    @pytest.mark.asyncio
    async def test_update_quota_updates_existing(self, mock_db):
        row = Mock(); row.total_quota = 100000; row.alert_threshold = 10
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))
        svc = TokenService(mock_db)
        await svc.update_quota(str(uuid4()), total_quota=500000)
        assert row.total_quota == 500000
        assert row.alert_threshold == 10  # unchanged
        assert not mock_db.add.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_token_service.py -v`
Expected: FAIL（service 不存在）

- [ ] **Step 3: 实现 TokenService**

Create `backend/app/services/token_service.py`:

```python
"""Token quota + status aggregation + warning (req §11.4 / §9.2.6)."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import TokenQuota, OperationLog
from app.models.execution import AICallLog
from app.core.config import settings
from app.schemas.system import TokenStatusResponse, TokenUsageItem, TokenUsageResponse

logger = logging.getLogger(__name__)


class TokenService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_quota(self, project_id: str) -> dict:
        q = select(TokenQuota).where(TokenQuota.project_id == UUID(project_id))
        row = (await self.db.execute(q)).scalar_one_or_none()
        if not row:
            return {
                "project_id": project_id, "total_quota": settings.TOKEN_QUOTA,
                "alert_threshold": int(settings.TOKEN_WARNING_RATE * 100),
                "updated_at": None,
            }
        return row.to_dict()

    async def update_quota(self, project_id: str, *,
                           total_quota: Optional[int] = None,
                           alert_threshold: Optional[int] = None) -> dict:
        q = select(TokenQuota).where(TokenQuota.project_id == UUID(project_id))
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            row = TokenQuota(
                project_id=UUID(project_id),
                total_quota=total_quota if total_quota is not None else settings.TOKEN_QUOTA,
                alert_threshold=alert_threshold if alert_threshold is not None else int(settings.TOKEN_WARNING_RATE * 100),
            )
            self.db.add(row)
        else:
            if total_quota is not None:
                row.total_quota = total_quota
            if alert_threshold is not None:
                row.alert_threshold = alert_threshold
        await self.db.commit()
        await self.db.refresh(row)
        return row.to_dict()

    async def get_status(self, project_id: str) -> TokenStatusResponse:
        """Aggregate token usage status (§9.2.6)."""
        pid = UUID(project_id)
        # 1. quota
        q = select(TokenQuota).where(TokenQuota.project_id == pid)
        quota = (await self.db.execute(q)).scalar_one_or_none()
        total = quota.total_quota if quota else settings.TOKEN_QUOTA
        threshold = quota.alert_threshold if quota else int(settings.TOKEN_WARNING_RATE * 100)

        # 2. total used (SUM)
        used_q = select(func.coalesce(func.sum(AICallLog.tokens_used), 0)).where(
            AICallLog.project_id == pid
        )
        used = (await self.db.execute(used_q)).scalar() or 0

        # 3. recent 7-day sum
        since = datetime.now(timezone.utc) - timedelta(days=7)
        recent_q = select(func.coalesce(func.sum(AICallLog.tokens_used), 0)).where(
            AICallLog.project_id == pid,
            AICallLog.created_at >= since,
        )
        recent_7d = (await self.db.execute(recent_q)).scalar() or 0
        daily_avg = recent_7d / 7.0

        remaining = max(0, total - used)
        percentage = (used / total * 100) if total > 0 else 0.0
        is_warning = (remaining / total * 100) <= threshold if total > 0 else False
        est_days = int(remaining / daily_avg) if daily_avg > 0 else None

        return TokenStatusResponse(
            total_quota=total, used=used, remaining=remaining,
            percentage=round(percentage, 2), is_warning=is_warning,
            warning_threshold=threshold, recent_daily_avg=round(daily_avg, 2),
            estimated_days_remaining=est_days,
        )

    async def get_usage(self, project_id: str, days: int = 7) -> TokenUsageResponse:
        """Usage breakdown by stage / model / day for charts."""
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)

        by_stage_q = (
            select(AICallLog.stage, func.coalesce(func.sum(AICallLog.tokens_used), 0))
            .where(AICallLog.project_id == pid, AICallLog.created_at >= since)
            .group_by(AICallLog.stage)
        )
        by_model_q = (
            select(AICallLog.model, func.coalesce(func.sum(AICallLog.tokens_used), 0))
            .where(AICallLog.project_id == pid, AICallLog.created_at >= since)
            .group_by(AICallLog.model)
        )
        by_stage = [
            TokenUsageItem(label=r[0] or "unknown", tokens=r[1])
            for r in (await self.db.execute(by_stage_q)).all()
        ]
        by_model = [
            TokenUsageItem(label=r[0] or "unknown", tokens=r[1])
            for r in (await self.db.execute(by_model_q)).all()
        ]

        # daily buckets
        daily_q = (
            select(
                func.date_trunc("day", AICallLog.created_at).label("d"),
                func.coalesce(func.sum(AICallLog.tokens_used), 0),
            )
            .where(AICallLog.project_id == pid, AICallLog.created_at >= since)
            .group_by("d").order_by("d")
        )
        daily = [
            {"date": str(r[0].date()) if r[0] else "", "tokens": r[1]}
            for r in (await self.db.execute(daily_q)).all()
        ]
        return TokenUsageResponse(by_stage=by_stage, by_model=by_model, daily=daily)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_token_service.py -v`
Expected: PASS（6 tests）

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/token_service.py tests/test_token_service.py
git commit -m "feat(system): TokenService quota + status aggregation + warning (W10)"
```

---

## Task 8: ai_gateway 埋点改造（保守，纯加可选参数）

**Files:**
- Modify: `backend/app/services/ai_gateway.py`
- Modify: `backend/app/services/test_point_generator.py`
- Modify: `backend/app/services/test_case_generator.py`
- Test: `backend/tests/test_ai_gateway_logging.py`

- [ ] **Step 1: 写失败测试 — 埋点写入 + None 不写 + 失败不阻塞**

Create `backend/tests/test_ai_gateway_logging.py`:

```python
"""AI gateway token logging tests (W10埋点)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_gateway import AIGateway


@pytest.fixture
def gateway_with_mock_provider():
    """Build an AIGateway with a single mock provider registered."""
    gw = AIGateway.__new__(AIGateway)
    gw._providers = {"glm-4": MagicMock()}
    gw._providers["glm-4"].chat_completion = AsyncMock(return_value={"content": "hi", "tokens": 150})
    return gw


@pytest.mark.asyncio
async def test_chat_with_project_id_writes_log(gateway_with_mock_provider):
    gw = gateway_with_mock_provider
    with patch("app.services.ai_gateway.log_ai_call", new=AsyncMock()) as mock_log:
        result = await gw.chat(
            [{"role": "user", "content": "x"}],
            provider="glm-4",
            project_id="00000000-0000-0000-0000-000000000001",
            stage="identify_point",
        )
        assert result["content"] == "hi"
        mock_log.assert_awaited_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["project_id"] == "00000000-0000-0000-0000-000000000001"
        assert call_kwargs["provider_name"] == "glm-4"
        assert call_kwargs["tokens"] == 150
        assert call_kwargs["stage"] == "identify_point"


@pytest.mark.asyncio
async def test_chat_without_project_id_skips_log(gateway_with_mock_provider):
    gw = gateway_with_mock_provider
    with patch("app.services.ai_gateway.log_ai_call", new=AsyncMock()) as mock_log:
        await gw.chat([{"role": "user", "content": "x"}], provider="glm-4")
        mock_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_failure_does_not_break_chat(gateway_with_mock_provider):
    gw = gateway_with_mock_provider
    with patch("app.services.ai_gateway.log_ai_call", new=AsyncMock(side_effect=Exception("db down"))):
        # should NOT raise — logging is best-effort
        result = await gw.chat(
            [{"role": "user", "content": "x"}],
            provider="glm-4",
            project_id="00000000-0000-0000-0000-000000000001",
            stage="identify_point",
        )
        assert result["content"] == "hi"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_ai_gateway_logging.py -v`
Expected: FAIL（chat 不接受 project_id 参数 / log_ai_call 不存在）

- [ ] **Step 3: 改 ai_gateway.chat 加可选参数 + _log_ai_call**

Modify `backend/app/services/ai_gateway.py`。

先在文件顶部 import 区加（在现有 import 之后）：

```python
from app.models.execution import AICallLog
from app.core.database import AsyncSessionLocal
```

然后在 `AIGateway` 类内，**修改 `chat` 方法签名**（在现有 `**kwargs` 前加可选参数）：

把现有：
```python
    async def chat(
        self,
        messages: List[Dict],
        provider: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """..."""
        provider_name = provider or settings.AI_DEFAULT_PROVIDER

        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not available. Check API key configuration in settings.")

        return await self._providers[provider_name].chat_completion(messages, **kwargs)
```

改为：
```python
    async def chat(
        self,
        messages: List[Dict],
        provider: Optional[str] = None,
        *,
        project_id: Optional[str] = None,
        stage: Optional[str] = None,
        operator: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """聊天接口。project_id 非空时记录 ai_call_log（W10 埋点）。

        Args:
            messages: 消息列表
            provider: 指定 provider，默认使用配置的默认 provider
            project_id: 项目ID，传入则记录 token 用量到 ai_call_log
            stage: 调用阶段（identify_point/generate_case/detect_hallucination/refine 等）
            operator: 操作人（可选）
            **kwargs: 额外参数
        """
        provider_name = provider or settings.AI_DEFAULT_PROVIDER

        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not available. Check API key configuration in settings.")

        result = await self._providers[provider_name].chat_completion(messages, **kwargs)

        # W10: best-effort token logging
        if project_id:
            try:
                await log_ai_call(
                    project_id=project_id,
                    provider_name=provider_name,
                    tokens=result.get("tokens", 0),
                    stage=stage or "unknown",
                    status="success",
                )
            except Exception as e:
                logger.warning(f"AI call logging failed (non-blocking): {e}")

        return result
```

在文件**末尾**（模块级，`ai_gateway = AIGateway()` 单例之前或之后均可）加 `log_ai_call` 函数：

```python
async def log_ai_call(project_id: str, provider_name: str, tokens: int,
                      stage: str, status: str = "success"):
    """Write an ai_call_log row. Best-effort: opens its own session, never raises."""
    try:
        async with AsyncSessionLocal() as db:
            entry = AICallLog(
                project_id=UUID(project_id),
                model=provider_name,
                tokens_used=tokens,
                tokens_cost=0,
                stage=stage,
                status=status,
            )
            db.add(entry)
            await db.commit()
    except Exception as e:
        logger.warning(f"log_ai_call failed: {e}")
```

确保文件顶部已有 `from uuid import UUID`（检查；若无则加）。

- [ ] **Step 4: 给现有 generator 传 project_id/stage**

Modify `backend/app/services/test_point_generator.py`，把 `generate` 方法内调用处（约 99-100 行）：

```python
            logger.info("Calling AI gateway with provider=glm-4")
            response = await ai_gateway.chat(messages, provider="glm-4")
```

改为：
```python
            logger.info("Calling AI gateway with provider=glm-4")
            response = await ai_gateway.chat(
                messages, provider="glm-4",
                project_id=str(project_id) if project_id else None,
                stage="identify_point",
            )
```

需要 `generate` 接收 `project_id`。改 `generate` 签名加 `project_id` 参数：

```python
    async def generate(
        self,
        doc_content: str,
        rules: List[str],
        knowledge_context: str,
        project_id: Optional[str] = None,
    ) -> List[Dict]:
```

文件顶部 import 加 `from typing import Optional`（若无）。调用方 `ai_case_tasks.py` 传 `project_id`——**但本会话不碰 tasks/**，故 ai_case_tasks 的传参留到联调或 #4 完成后；此处 generator 默认 None 向后兼容（不传则不埋点，符合保守策略）。

> 注：若 test_point_generator 当前已被 ai_case_tasks 以 `generator.generate(doc_content=..., rules=..., knowledge_context=...)` 关键字调用，加可选参数不破坏现有调用。

Modify `backend/app/services/test_case_generator.py`，把 `generate_from_point` 内调用处（约 75-76 行）：

```python
            logger.info("Calling AI gateway with provider=glm-4")
            response = await ai_gateway.chat(messages, provider="glm-4")
```

改为：
```python
            logger.info("Calling AI gateway with provider=glm-4")
            response = await ai_gateway.chat(
                messages, provider="glm-4",
                project_id=str(point.project_id) if hasattr(point, "project_id") and point.project_id else None,
                stage="generate_case",
            )
```

（`point` 是 TestPoint，有 `project_id` 字段，直接用。hallucination_detector 不调 ai_gateway.chat，无需改。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_ai_gateway_logging.py -v`
Expected: PASS（3 tests）

- [ ] **Step 6: 跑全量确认无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/services/ai_gateway.py app/services/test_point_generator.py app/services/test_case_generator.py tests/test_ai_gateway_logging.py
git commit -m "feat(system): ai_gateway token logging + generators pass project_id (W10)"
```

---

## Task 9: system API router

**Files:**
- Create: `backend/app/api/v1/system.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_api_system.py`

- [ ] **Step 1: 写失败测试 — 端点契约（dependency override + mock service）**

Create `backend/tests/test_api_system.py`:

```python
"""System API endpoint tests (FastAPI TestClient + dependency override)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1 import system as system_api


@pytest.fixture
def client():
    return TestClient(app)


def _override_service(mock_svc):
    """Override get_*_service deps to return mock_svc."""
    from app.api.v1.system import (
        get_setting_service, get_env_service,
        get_token_service, get_oplog_service,
    )
    app.dependency_overrides[get_setting_service] = lambda: mock_svc
    app.dependency_overrides[get_env_service] = lambda: mock_svc
    app.dependency_overrides[get_token_service] = lambda: mock_svc
    app.dependency_overrides[get_oplog_service] = lambda: mock_svc


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


class TestSettingsEndpoints:
    def test_list_settings(self, client):
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[{"id": "1", "key": "heal.strategy", "value": "SMART"}])
        _override_service(svc)
        r = client.get("/api/v1/system/settings?category=runtime")
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"][0]["key"] == "heal.strategy"

    def test_update_setting(self, client):
        svc = MagicMock()
        svc.set = AsyncMock(return_value=None)
        svc.log_and_invalidate = AsyncMock(return_value=None)
        _override_service(svc)
        r = client.put("/api/v1/system/settings/heal.strategy",
                       json={"value": "SMART", "value_type": "string", "is_secret": False})
        assert r.status_code == 200
        svc.set.assert_awaited_once()

    def test_list_settings_bad_category(self, client):
        svc = MagicMock()
        _override_service(svc)
        r = client.get("/api/v1/system/settings?category=invalid")
        assert r.status_code == 422  # pattern validation


class TestEnvEndpoints:
    def test_list_envs(self, client):
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[{"id": "1", "name": "dev"}])
        _override_service(svc)
        r = client.get("/api/v1/system/envs")
        assert r.status_code == 200
        assert r.json()["data"][0]["name"] == "dev"

    def test_create_env(self, client):
        svc = MagicMock()
        svc.create = AsyncMock(return_value={"id": "1", "name": "dev", "url": "http://x",
                                              "env_type": "dev", "status": "active",
                                              "credentials": {}})
        _override_service(svc)
        r = client.post("/api/v1/system/envs",
                        json={"name": "dev", "url": "http://x", "env_type": "dev"})
        assert r.status_code == 201
        assert r.json()["data"]["name"] == "dev"


class TestTokenEndpoints:
    def test_token_status(self, client):
        svc = MagicMock()
        svc.get_status = AsyncMock(return_value=MagicMock(
            model_dump=MagicMock(return_value={
                "total_quota": 100000, "used": 5000, "remaining": 95000,
                "percentage": 5.0, "is_warning": False, "warning_threshold": 10,
                "recent_daily_avg": 1000.0, "estimated_days_remaining": 95,
            })
        ))
        _override_service(svc)
        r = client.get("/api/v1/system/tokens/status?project_id=00000000-0000-0000-0000-000000000001")
        assert r.status_code == 200
        assert r.json()["data"]["used"] == 5000
        assert r.json()["data"]["is_warning"] is False

    def test_token_quota_update(self, client):
        svc = MagicMock()
        svc.update_quota = AsyncMock(return_value={"project_id": "x", "total_quota": 200000,
                                                    "alert_threshold": 10})
        _override_service(svc)
        r = client.put("/api/v1/system/tokens/quota?project_id=00000000-0000-0000-0000-000000000001",
                       json={"total_quota": 200000})
        assert r.status_code == 200


class TestOperationLogEndpoint:
    def test_list_oplogs(self, client):
        svc = MagicMock()
        svc.list = AsyncMock(return_value=([{"id": "1", "module": "system", "action": "x"}], 1))
        _override_service(svc)
        r = client.get("/api/v1/system/operation-logs")
        assert r.status_code == 200
        assert r.json()["data"]["items"][0]["module"] == "system"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_system.py -v`
Expected: FAIL（system router 未注册）

- [ ] **Step 3: 实现 system.py router**

Create `backend/app/api/v1/system.py`:

```python
"""System settings API endpoints (prefix /system)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.system_setting_service import SystemSettingService
from app.services.test_env_service import TestEnvService
from app.services.token_service import TokenService
from app.services.operation_log_service import OperationLogService, log_operation
from app.schemas.system import (
    SettingUpdate, SettingResponse, TestConnectionRequest, TestConnectionResponse,
    RuntimeConfigResponse, TestEnvCreate, TestEnvUpdate, TestEnvResponse,
    TokenQuotaUpdate, OperationLogResponse,
)

router = APIRouter()


# ---- service factories ----
def get_setting_service(db: AsyncSession = Depends(get_db)) -> SystemSettingService:
    return SystemSettingService(db)

def get_env_service(db: AsyncSession = Depends(get_db)) -> TestEnvService:
    return TestEnvService(db)

def get_token_service(db: AsyncSession = Depends(get_db)) -> TokenService:
    return TokenService(db)

def get_oplog_service(db: AsyncSession = Depends(get_db)) -> OperationLogService:
    return OperationLogService(db)


# ---- settings ----
@router.get("/settings")
async def list_settings(
    category: str = Query(..., pattern="^(ai|runtime)$"),
    svc: SystemSettingService = Depends(get_setting_service),
):
    rows = await svc.list(category)
    return {"code": 0, "data": [SettingResponse(**r) for r in rows]}


@router.get("/settings/{key}")
async def get_setting(
    key: str,
    category: str = Query(..., pattern="^(ai|runtime)$"),
    reveal: bool = Query(False),
    svc: SystemSettingService = Depends(get_setting_service),
):
    val = await svc.get(key, category=category)
    return {"code": 0, "data": {"key": key, "value": val}}


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    body: SettingUpdate,
    category: str = Query(..., pattern="^(ai|runtime)$"),
    svc: SystemSettingService = Depends(get_setting_service),
    oplog: OperationLogService = Depends(get_oplog_service),
):
    await svc.set(category, key, body.value, value_type=body.value_type,
                  is_secret=body.is_secret, description=body.description,
                  updated_by=body.updated_by)
    await log_operation(oplog.db, "system", "update_setting", "setting", key,
                        detail={"category": category, "value_type": body.value_type},
                        operator=body.updated_by or "system")
    return {"code": 0, "message": "Setting updated"}


@router.post("/settings/test-connection", response_model=TestConnectionResponse)
async def test_connection(body: TestConnectionRequest):
    """Ping a provider with current config to verify the key."""
    from app.services.ai_gateway import ai_gateway
    provider = body.provider
    if provider not in ai_gateway._providers:
        return TestConnectionResponse(success=False, message=f"Provider '{provider}' not configured", model=None)
    try:
        result = await ai_gateway.chat(
            [{"role": "user", "content": "ping"}], provider=provider,
        )
        return TestConnectionResponse(success=True, message="Connection OK", model=provider)
    except Exception as e:
        return TestConnectionResponse(success=False, message=str(e), model=provider)


# ---- runtime config ----
@router.get("/runtime-config", response_model=RuntimeConfigResponse)
async def get_runtime_config(svc: SystemSettingService = Depends(get_setting_service)):
    """Aggregate runtime config from system_setting (falls back to settings defaults)."""
    from app.core.config import settings
    async def _g(k, default, cast=None):
        v = await svc.get(k, category="runtime", default=default)
        try:
            return cast(v) if cast else v
        except (TypeError, ValueError):
            return default
    return RuntimeConfigResponse(
        heal_strategy=await _g("heal.strategy", "SMART"),
        heal_confidence_threshold=await _g("heal.confidence_threshold", settings.HEAL_CONFIDENCE_THRESHOLD, int),
        heal_cache_ttl_success=await _g("heal.cache_ttl_success", settings.HEAL_CACHE_TTL_SUCCESS, int),
        heal_cache_ttl_fail=await _g("heal.cache_ttl_fail", settings.HEAL_CACHE_TTL_FAIL, int),
        execution_timeout=await _g("execution.timeout", settings.EXECUTION_TIMEOUT, int),
        max_retry_count=await _g("execution.max_retry", settings.MAX_RETRY_COUNT, int),
        sse_timeout=await _g("sse.timeout", settings.SSE_TIMEOUT, int),
    )


# ---- test env ----
@router.get("/envs")
async def list_envs(svc: TestEnvService = Depends(get_env_service)):
    rows = await svc.list()
    return {"code": 0, "data": [TestEnvResponse(**r) for r in rows]}


@router.post("/envs", status_code=201)
async def create_env(body: TestEnvCreate, svc: TestEnvService = Depends(get_env_service),
                     oplog: OperationLogService = Depends(get_oplog_service)):
    env = await svc.create(body.model_dump())
    await log_operation(oplog.db, "system", "create_env", "test_env", env["id"],
                        detail={"name": env["name"]}, operator=body.created_by or "system")
    return {"code": 0, "data": TestEnvResponse(**env)}


@router.put("/envs/{env_id}")
async def update_env(env_id: str, body: TestEnvUpdate,
                     svc: TestEnvService = Depends(get_env_service)):
    env = await svc.update(env_id, body.model_dump(exclude_unset=True))
    if not env:
        raise HTTPException(status_code=404, detail="Env not found")
    return {"code": 0, "data": TestEnvResponse(**env)}


@router.delete("/envs/{env_id}")
async def delete_env(env_id: str, svc: TestEnvService = Depends(get_env_service)):
    ok = await svc.delete(env_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Env not found")
    return {"code": 0, "message": "Env deleted"}


# ---- operation logs ----
@router.get("/operation-logs")
async def list_oplogs(
    module: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    svc: OperationLogService = Depends(get_oplog_service),
):
    from app.models.system import OperationLog
    from sqlalchemy import select, func
    q = select(OperationLog)
    if module:
        q = q.where(OperationLog.module == module)
    total_q = select(func.count()).select_from(OperationLog)
    if module:
        total_q = total_q.where(OperationLog.module == module)
    rows = (await svc.db.execute(
        q.order_by(OperationLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    total = (await svc.db.execute(total_q)).scalar() or 0
    return {"code": 0, "data": {"items": [OperationLogResponse(**r.to_dict()) for r in rows],
                                "total": total, "page": page, "page_size": page_size}}


# ---- tokens ----
@router.get("/tokens/status")
async def token_status(project_id: str = Query(...),
                       svc: TokenService = Depends(get_token_service)):
    st = await svc.get_status(project_id)
    return {"code": 0, "data": st.model_dump()}


@router.get("/tokens/quota")
async def token_quota_get(project_id: str = Query(...),
                          svc: TokenService = Depends(get_token_service)):
    return {"code": 0, "data": await svc.get_quota(project_id)}


@router.put("/tokens/quota")
async def token_quota_update(project_id: str = Query(...), body: TokenQuotaUpdate = None,
                             svc: TokenService = Depends(get_token_service),
                             oplog: OperationLogService = Depends(get_oplog_service)):
    result = await svc.update_quota(project_id,
                                    total_quota=body.total_quota if body else None,
                                    alert_threshold=body.alert_threshold if body else None)
    await log_operation(oplog.db, "system", "update_token_quota", "token_quota", project_id,
                        detail=result, operator="system")
    return {"code": 0, "data": result}


@router.get("/tokens/usage")
async def token_usage(project_id: str = Query(...),
                      days: int = Query(7, ge=1, le=90),
                      svc: TokenService = Depends(get_token_service)):
    usage = await svc.get_usage(project_id, days)
    return {"code": 0, "data": usage.model_dump()}
```

- [ ] **Step 4: 注册到 api/__init__.py**

Modify `backend/app/api/__init__.py`：

import 行加 `system`：
```python
from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, system
```

include 行加：
```python
api_router.include_router(system.router, prefix="/system", tags=["system"])
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_system.py -v`
Expected: PASS（7 tests）

- [ ] **Step 6: 跑全量 + 验证 app 导入**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; sys_routes=[r.path for r in app.routes if '/system' in getattr(r,'path','')]; [print(r) for r in sorted(set(sys_routes))]" 2>&1 | tail -20`
Expected: 列出 /api/v1/system/settings、/envs、/runtime-config、/operation-logs、/tokens/* 等路由

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/api/v1/system.py app/api/__init__.py tests/test_api_system.py
git commit -m "feat(system): system API router (settings/envs/tokens/oplog/runtime) (W10)"
```

---

## Task 10: 前端 API 封装

**Files:**
- Create: `frontend/src/api/system.js`

- [ ] **Step 1: 写 api/system.js**

Create `frontend/src/api/system.js`:

```javascript
import axios from './axios'

export const systemAPI = {
  // ---- settings ----
  listSettings(category) {
    return axios.get('/system/settings', { params: { category } }).then(r => r.data)
  },
  getSetting(key, category, reveal = false) {
    return axios.get(`/system/settings/${key}`, { params: { category, reveal } }).then(r => r.data)
  },
  updateSetting(key, category, body) {
    return axios.put(`/system/settings/${key}`, body, { params: { category } }).then(r => r.data)
  },
  testConnection(provider) {
    return axios.post('/system/settings/test-connection', { provider }).then(r => r.data)
  },

  // ---- runtime config ----
  getRuntimeConfig() {
    return axios.get('/system/runtime-config').then(r => r.data)
  },

  // ---- envs ----
  listEnvs() {
    return axios.get('/system/envs').then(r => r.data)
  },
  createEnv(body) {
    return axios.post('/system/envs', body).then(r => r.data)
  },
  updateEnv(id, body) {
    return axios.put(`/system/envs/${id}`, body).then(r => r.data)
  },
  deleteEnv(id) {
    return axios.delete(`/system/envs/${id}`).then(r => r.data)
  },

  // ---- operation logs ----
  listOpLogs(params = {}) {
    return axios.get('/system/operation-logs', { params }).then(r => r.data)
  },

  // ---- tokens ----
  tokenStatus(projectId) {
    return axios.get('/system/tokens/status', { params: { project_id: projectId } }).then(r => r.data)
  },
  getQuota(projectId) {
    return axios.get('/system/tokens/quota', { params: { project_id: projectId } }).then(r => r.data)
  },
  updateQuota(projectId, body) {
    return axios.put('/system/tokens/quota', body, { params: { project_id: projectId } }).then(r => r.data)
  },
  tokenUsage(projectId, days = 7) {
    return axios.get('/system/tokens/usage', { params: { project_id: projectId, days } }).then(r => r.data)
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/api/system.js
git commit -m "feat(system): frontend API wrapper (W10)"
```

---

## Task 11: 前端 AISettings + RuntimeConfig + EnvManagement 页

**Files:**
- Create: `frontend/src/views/system/AISettings.vue`
- Create: `frontend/src/views/system/RuntimeConfig.vue`
- Create: `frontend/src/views/system/EnvManagement.vue`
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: 写 AISettings.vue**

Create `frontend/src/views/system/AISettings.vue`:

```vue
<template>
  <div class="ai-settings">
    <el-card>
      <template #header><span>AI 设置</span></template>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:16px">
        provider 的 API Key / URL 存数据库，修改后即时生效（无需重启）。联调时在此填入真实 key。
      </el-alert>

      <el-table :data="providerRows" border>
        <el-table-column prop="provider" label="Provider" width="120" />
        <el-table-column label="API Key">
          <template #default="{ row }">
            <el-input v-model="row.apiKey" :type="row.showKey ? 'text' : 'password'" size="small">
              <template #append>
                <el-button @click="row.showKey = !row.showKey">{{ row.showKey ? '隐藏' : '显示' }}</el-button>
              </template>
            </el-input>
          </template>
        </el-table-column>
        <el-table-column label="API URL" width="320">
          <template #default="{ row }">
            <el-input v-model="row.apiUrl" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="save(row)">保存</el-button>
            <el-button size="small" :loading="row.testing" @click="testConn(row)">测试连接</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-divider />
      <el-form label-width="140px">
        <el-form-item label="默认 Provider">
          <el-select v-model="defaultProvider" style="width: 240px">
            <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
          </el-select>
          <el-button type="primary" style="margin-left: 12px" @click="saveDefault">保存</el-button>
        </el-form-item>
        <el-form-item label="Fallback 链">
          <el-select v-model="fallbackProviders" multiple style="width: 400px">
            <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
          </el-select>
          <el-button type="primary" style="margin-left: 12px" @click="saveFallback">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { systemAPI } from '@/api/system.js'

const providers = ['glm-4', 'qwen', 'deepseek', 'claude']
const providerRows = ref(providers.map(p => ({ provider: p, apiKey: '', apiUrl: '', showKey: false, testing: false })))
const defaultProvider = ref('glm-4')
const fallbackProviders = ref(['glm-4', 'qwen', 'deepseek'])

const loadSettings = async () => {
  try {
    const res = await systemAPI.listSettings('ai')
    const rows = res.data || []
    for (const row of rows) {
      if (row.key.endsWith('.api_key')) {
        const p = row.key.split('.')[0]
        const target = providerRows.value.find(r => r.provider === p)
        if (target && row.value && row.value !== '***') target.apiKey = row.value
      } else if (row.key.endsWith('.api_url')) {
        const p = row.key.split('.')[0]
        const target = providerRows.value.find(r => r.provider === p)
        if (target && row.value) target.apiUrl = row.value
      } else if (row.key === 'ai.default_provider' && row.value) {
        defaultProvider.value = row.value
      } else if (row.key === 'ai.fallback_providers' && row.value) {
        try { fallbackProviders.value = JSON.parse(row.value) } catch {}
      }
    }
  } catch (e) { ElMessage.error('加载配置失败') }
}

const save = async (row) => {
  try {
    await systemAPI.updateSetting(`${row.provider}.api_key`, 'ai', {
      value: row.apiKey, value_type: 'string', is_secret: true
    })
    if (row.apiUrl) {
      await systemAPI.updateSetting(`${row.provider}.api_url`, 'ai', {
        value: row.apiUrl, value_type: 'string', is_secret: false
      })
    }
    ElMessage.success(`${row.provider} 已保存`)
  } catch (e) { ElMessage.error('保存失败') }
}

const testConn = async (row) => {
  row.testing = true
  try {
    const res = await systemAPI.testConnection(row.provider)
    const d = res.data || res
    if (d.success) ElMessage.success(`${row.provider} 连接正常`)
    else ElMessage.error(`${row.provider} 连接失败: ${d.message}`)
  } catch (e) { ElMessage.error('测试失败') }
  finally { row.testing = false }
}

const saveDefault = async () => {
  try {
    await systemAPI.updateSetting('ai.default_provider', 'ai', {
      value: defaultProvider.value, value_type: 'string', is_secret: false
    })
    ElMessage.success('默认 provider 已保存')
  } catch (e) { ElMessage.error('保存失败') }
}

const saveFallback = async () => {
  try {
    await systemAPI.updateSetting('ai.fallback_providers', 'ai', {
      value: JSON.stringify(fallbackProviders.value), value_type: 'json', is_secret: false
    })
    ElMessage.success('Fallback 链已保存')
  } catch (e) { ElMessage.error('保存失败') }
}

onMounted(loadSettings)
</script>

<style scoped>
.ai-settings { padding: 20px; }
</style>
```

- [ ] **Step 2: 写 RuntimeConfig.vue**

Create `frontend/src/views/system/RuntimeConfig.vue`:

```vue
<template>
  <div class="runtime-config">
    <el-card>
      <template #header><span>运行配置</span></template>
      <el-form :model="form" label-width="200px" v-loading="loading">
        <el-card shadow="never" style="margin-bottom:16px">
          <template #header><span>自愈引擎</span></template>
          <el-form-item label="自愈策略">
            <el-select v-model="form.heal_strategy" style="width: 280px">
              <el-option label="SMART（默认，CI）" value="SMART" />
              <el-option label="HEURISTIC_ONLY（仅启发式）" value="HEURISTIC_ONLY" />
              <el-option label="DOM_ONLY（DOM模糊）" value="DOM_ONLY" />
              <el-option label="VISUAL_ONLY（视觉模型）" value="VISUAL_ONLY" />
              <el-option label="FULL（全链含视觉）" value="FULL" />
              <el-option label="PARALLEL（并行）" value="PARALLEL" />
            </el-select>
          </el-form-item>
          <el-form-item label="置信度阈值">
            <el-input-number v-model="form.heal_confidence_threshold" :min="1" :max="10" />
          </el-form-item>
          <el-form-item label="缓存TTL-成功(天)">
            <el-input-number v-model="form.heal_cache_ttl_success" :min="1" :max="90" />
          </el-form-item>
          <el-form-item label="缓存TTL-失败(小时)">
            <el-input-number v-model="form.heal_cache_ttl_fail" :min="1" :max="72" />
          </el-form-item>
        </el-card>

        <el-card shadow="never" style="margin-bottom:16px">
          <template #header><span>执行</span></template>
          <el-form-item label="执行超时(秒)">
            <el-input-number v-model="form.execution_timeout" :min="10" :max="3600" />
          </el-form-item>
          <el-form-item label="最大重试次数">
            <el-input-number v-model="form.max_retry_count" :min="0" :max="10" />
          </el-form-item>
          <el-form-item label="SSE 超时(秒)">
            <el-input-number v-model="form.sse_timeout" :min="60" :max="7200" />
          </el-form-item>
        </el-card>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveAll">保存全部</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { systemAPI } from '@/api/system.js'

const loading = ref(false)
const saving = ref(false)
const form = ref({
  heal_strategy: 'SMART', heal_confidence_threshold: 3,
  heal_cache_ttl_success: 30, heal_cache_ttl_fail: 1,
  execution_timeout: 600, max_retry_count: 3, sse_timeout: 1800
})

const FIELD_MAP = {
  heal_strategy: { key: 'heal.strategy', type: 'string' },
  heal_confidence_threshold: { key: 'heal.confidence_threshold', type: 'int' },
  heal_cache_ttl_success: { key: 'heal.cache_ttl_success', type: 'int' },
  heal_cache_ttl_fail: { key: 'heal.cache_ttl_fail', type: 'int' },
  execution_timeout: { key: 'execution.timeout', type: 'int' },
  max_retry_count: { key: 'execution.max_retry', type: 'int' },
  sse_timeout: { key: 'sse.timeout', type: 'int' }
}

const load = async () => {
  loading.value = true
  try {
    const res = await systemAPI.getRuntimeConfig()
    const d = res.data || res
    Object.assign(form.value, d)
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const saveAll = async () => {
  saving.value = true
  try {
    for (const [field, meta] of Object.entries(FIELD_MAP)) {
      await systemAPI.updateSetting(meta.key, 'runtime', {
        value: String(form.value[field]), value_type: meta.type, is_secret: false
      })
    }
    ElMessage.success('运行配置已保存')
  } catch (e) { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

onMounted(load)
</script>

<style scoped>
.runtime-config { padding: 20px; }
</style>
```

- [ ] **Step 3: 写 EnvManagement.vue**

Create `frontend/src/views/system/EnvManagement.vue`:

```vue
<template>
  <div class="env-management">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>环境管理</span>
          <el-button type="primary" @click="openCreate">新增环境</el-button>
        </div>
      </template>
      <el-table :data="envs" v-loading="loading" border>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="url" label="URL" min-width="250" show-overflow-tooltip />
        <el-table-column prop="env_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag :type="envTagType(row.env_type)">{{ envLabel(row.env_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="remove(row)">停用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑环境' : '新增环境'" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="URL"><el-input v-model="form.url" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.env_type" style="width: 200px">
            <el-option label="开发" value="dev" />
            <el-option label="测试" value="staging" />
            <el-option label="生产" value="prod" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { systemAPI } from '@/api/system.js'

const loading = ref(false)
const envs = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const form = ref({ name: '', url: '', env_type: 'dev', status: 'active' })

const envLabel = (t) => ({ dev: '开发', staging: '测试', prod: '生产' }[t] || t)
const envTagType = (t) => ({ dev: 'info', staging: 'warning', prod: 'danger' }[t] || 'info')

const load = async () => {
  loading.value = true
  try {
    const res = await systemAPI.listEnvs()
    envs.value = res.data || res || []
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const openCreate = () => {
  isEdit.value = false
  form.value = { name: '', url: '', env_type: 'dev', status: 'active' }
  dialogVisible.value = true
}

const openEdit = (row) => {
  isEdit.value = true
  form.value = { ...row }
  dialogVisible.value = true
}

const submit = async () => {
  try {
    if (isEdit.value) {
      await systemAPI.updateEnv(form.value.id, form.value)
    } else {
      await systemAPI.createEnv(form.value)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } catch (e) { ElMessage.error('保存失败') }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确定停用环境「${row.name}」？`, '确认', { type: 'warning' })
    await systemAPI.deleteEnv(row.id)
    ElMessage.success('已停用')
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') }
}

onMounted(load)
</script>

<style scoped>
.env-management { padding: 20px; }
</style>
```

- [ ] **Step 4: 注册路由**

Modify `frontend/src/router/index.js`，在 children 数组末尾（`cases/:id` 之后）加：

```javascript
        {
          path: 'settings/ai',
          name: 'AISettings',
          component: () => import('@/views/system/AISettings.vue'),
          meta: { title: 'AI设置' }
        },
        {
          path: 'settings/runtime',
          name: 'RuntimeConfig',
          component: () => import('@/views/system/RuntimeConfig.vue'),
          meta: { title: '运行配置' }
        },
        {
          path: 'settings/env',
          name: 'EnvManagement',
          component: () => import('@/views/system/EnvManagement.vue'),
          meta: { title: '环境管理' }
        },
        {
          path: 'settings/tokens',
          name: 'TokenDashboard',
          component: () => import('@/views/system/TokenDashboard.vue'),
          meta: { title: 'Token成本管理' }
        },
```

- [ ] **Step 5: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 成功（TokenDashboard.vue 暂未建，下个 task 建；若构建因引用未建文件报错，先注释掉 TokenDashboard 路由，下个 task 再放开）

> 若构建报错 `Cannot find ../TokenDashboard.vue`：临时把 TokenDashboard 路由块注释，Task 12 建完文件后取消注释。记录此情况在 commit。

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/views/system/AISettings.vue src/views/system/RuntimeConfig.vue src/views/system/EnvManagement.vue src/router/index.js
git commit -m "feat(system): AISettings + RuntimeConfig + EnvManagement pages + routes (W10)"
```

---

## Task 12: 前端 TokenDashboard + 预警横幅

**Files:**
- Create: `frontend/src/views/system/TokenDashboard.vue`
- Create: `frontend/src/components/TokenWarningBanner.vue`
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 写 TokenDashboard.vue**

Create `frontend/src/views/system/TokenDashboard.vue`:

```vue
<template>
  <div class="token-dashboard">
    <el-card style="margin-bottom: 16px">
      <template #header><span>Token 成本管理</span></template>
      <el-row :gutter="20" v-loading="loading">
        <el-col :span="12">
          <div class="stat">
            <div class="stat-label">配额使用</div>
            <el-progress :percentage="status.percentage || 0" :color="progressColor" :stroke-width="20" />
            <div class="stat-detail">
              已用 {{ status.used }} / 总额 {{ status.total_quota }}（剩余 {{ status.remaining }}）
            </div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="stat-label">日均消耗</div>
            <div class="stat-value">{{ status.recent_daily_avg }}</div>
            <div class="stat-sub">预估剩余可用 {{ status.estimated_days_remaining ?? '∞' }} 天</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="stat-label">预警阈值</div>
            <div class="stat-value">{{ status.warning_threshold }}%</div>
            <el-tag :type="status.is_warning ? 'danger' : 'success'">
              {{ status.is_warning ? '已触发预警' : '正常' }}
            </el-tag>
          </div>
        </el-col>
      </el-row>

      <el-divider />
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" @change="load" filterable style="width: 240px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="总额度">
          <el-input-number v-model="quotaForm.total_quota" :min="0" />
        </el-form-item>
        <el-form-item label="预警阈值(%)">
          <el-input-number v-model="quotaForm.alert_threshold" :min="0" :max="100" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveQuota">保存配额</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card><template #header><span>按 stage 用量</span></template>
          <div ref="stageChart" style="height: 280px" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card><template #header><span>按 model 用量</span></template>
          <div ref="modelChart" style="height: 280px" />
        </el-card>
      </el-col>
    </el-row>
    <el-card style="margin-top: 16px">
      <template #header><span>按天趋势（近7日）</span></template>
      <div ref="dailyChart" style="height: 300px" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { systemAPI } from '@/api/system.js'
import { projectAPI } from '@/api/project.js'

const loading = ref(false)
const projects = ref([])
const projectId = ref('')
const status = ref({})
const quotaForm = ref({ total_quota: 100000, alert_threshold: 10 })
const usage = ref({ by_stage: [], by_model: [], daily: [] })
const stageChart = ref(null)
const modelChart = ref(null)
const dailyChart = ref(null)
let charts = {}

const progressColor = (percentage) => {
  if (percentage >= 90) return '#f56c6c'
  if (percentage >= 70) return '#e6a23c'
  return '#67c23a'
}

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = res.items || res || []
    if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].id
      load()
    }
  } catch (e) {}
}

const load = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const [statusRes, quotaRes, usageRes] = await Promise.all([
      systemAPI.tokenStatus(projectId.value),
      systemAPI.getQuota(projectId.value),
      systemAPI.tokenUsage(projectId.value, 7)
    ])
    status.value = statusRes.data || statusRes
    const q = quotaRes.data || quotaRes
    quotaForm.value = { total_quota: q.total_quota, alert_threshold: q.alert_threshold }
    usage.value = usageRes.data || usageRes
    await nextTick()
    renderCharts()
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const renderCharts = () => {
  if (stageChart.value) {
    charts.stage = echarts.init(stageChart.value)
    charts.stage.setOption({
      tooltip: {},
      series: [{ type: 'pie', radius: ['40%', '70%'],
        data: usage.value.by_stage.map(s => ({ name: s.label, value: s.tokens })) }]
    })
  }
  if (modelChart.value) {
    charts.model = echarts.init(modelChart.value)
    charts.model.setOption({
      tooltip: {},
      xAxis: { type: 'category', data: usage.value.by_model.map(m => m.label) },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: usage.value.by_model.map(m => m.tokens) }]
    })
  }
  if (dailyChart.value) {
    charts.daily = echarts.init(dailyChart.value)
    charts.daily.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: usage.value.daily.map(d => d.date) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', smooth: true, data: usage.value.daily.map(d => d.tokens) }]
    })
  }
}

const saveQuota = async () => {
  try {
    await systemAPI.updateQuota(projectId.value, quotaForm.value)
    ElMessage.success('配额已保存')
    load()
  } catch (e) { ElMessage.error('保存失败') }
}

onMounted(loadProjects)
</script>

<style scoped>
.token-dashboard { padding: 20px; }
.stat { text-align: center; }
.stat-label { color: #909399; font-size: 13px; margin-bottom: 8px; }
.stat-value { font-size: 24px; font-weight: 600; color: #303133; }
.stat-detail { margin-top: 8px; color: #606266; font-size: 13px; }
.stat-sub { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
```

- [ ] **Step 2: 写 TokenWarningBanner.vue**

Create `frontend/src/components/TokenWarningBanner.vue`:

```vue
<template>
  <el-alert
    v-if="visible"
    title="Token 预警"
    :description="`当前项目 Token 剩余不足 ${threshold}%，请及时补充配额。`"
    type="error"
    :closable="false"
    show-icon
    style="border-radius: 0"
  />
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { systemAPI } from '@/api/system.js'
import { projectAPI } from '@/api/project.js'

const visible = ref(false)
const threshold = ref(10)
let timer = null
let currentProjectId = null

const checkStatus = async () => {
  if (document.hidden) return
  if (!currentProjectId) {
    try {
      const res = await projectAPI.list()
      const projects = res.items || res || []
      if (!projects.length) return
      currentProjectId = projects[0].id
    } catch { return }
  }
  try {
    const res = await systemAPI.tokenStatus(currentProjectId)
    const s = res.data || res
    threshold.value = s.warning_threshold
    if (s.is_warning) {
      visible.value = true
      const key = `token_warned_${currentProjectId}`
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, '1')
        ElMessageBox.alert(
          `Token 剩余不足 ${s.warning_threshold}%（剩余 ${s.remaining}），请及时处理。`,
          'Token 预警', { type: 'warning' }
        )
      }
    } else {
      visible.value = false
    }
  } catch { /* silent */ }
}

onMounted(() => {
  checkStatus()
  timer = setInterval(checkStatus, 5 * 60 * 1000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
```

- [ ] **Step 3: 挂载横幅到 App.vue**

Modify `frontend/src/App.vue`。先 Read 当前 App.vue，在根容器顶部加 `<TokenWarningBanner />`，import 组件。

（具体修改依现有 App.vue 结构：通常在 `<router-view />` 上方插入 `<TokenWarningBanner />`，script 区加 `import TokenWarningBanner from '@/components/TokenWarningBanner.vue'`。）

- [ ] **Step 4: 菜单加 Token成本管理**

Modify `frontend/src/layouts/MainLayout.vue`，系统设置子菜单（约 71-79 行）加一项：

```vue
          <el-menu-item index="/settings/tokens">Token成本管理</el-menu-item>
```

（加在 `/settings/env` 之后）

- [ ] **Step 5: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/views/system/TokenDashboard.vue src/components/TokenWarningBanner.vue src/App.vue src/layouts/MainLayout.vue
git commit -m "feat(system): TokenDashboard + warning banner (W10)"
```

---

## Task 13: 全量验证 + 收尾

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（含新增的 ~40 个测试 + 原有 179+）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 迁移脚本检查**

Run: `cd backend && ls migrations/*.sql`
Expected: 含 `add_system_settings_tables.sql` + 原有迁移脚本

- [ ] **Step 4: app 路由全量核对**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; routes=[r.path for r in app.routes if '/system' in getattr(r,'path','')]; [print(r) for r in sorted(set(routes))]"`
Expected: 列出 /api/v1/system/settings、/settings/{key}、/settings/test-connection、/runtime-config、/envs、/envs/{id}、/operation-logs、/tokens/status、/tokens/quota、/tokens/usage

- [ ] **Step 5: 更新 TODO_LIST**

Modify `.claude/TODO_LIST.md`：标记 #10 系统设置 P0 完成（5 子项），更新模块计数 4/11。

- [ ] **Step 6: 最终 Commit**

```bash
git add .claude/TODO_LIST.md
git commit -m "chore: update TODO_LIST (4/11 modules, #10 system settings done)"
```

---

## Self-Review 记录

**1. Spec 覆盖：** 
- AI设置（provider 配置热改）✓ Task1(security)+Task5(setting svc)+Task9(settings API)+Task11(AISettings页) 
- 运行配置 ✓ Task9(runtime-config API)+Task11(RuntimeConfig页) 
- 环境管理 ✓ Task6(TestEnvService)+Task9(envs API)+Task11(EnvManagement页) 
- Token成本管理 ✓ Task7(TokenService)+Task8(ai_gateway埋点)+Task9(tokens API)+Task12(TokenDashboard) 
- 操作日志 ✓ Task6(OperationLogService)+Task9(operation-logs API) 
- §11.4 采集点（ai_gateway 埋点）✓ Task8 
- §9.2.6 /tokens/status 响应字段 ✓ Task7 TokenStatusResponse 
- 前端预警横幅 ✓ Task12 TokenWarningBanner 
- 修复死链路由 ✓ Task11 Step4 
全部覆盖。

**2. 占位符扫描：** Task11 Step5 有条件性构建提示（TokenDashboard 未建时临时注释路由）——属实现指引非占位符，下个 task 即建。其余步骤均有完整代码。

**3. 类型一致性：** `SystemSettingService.get/set/list`、`TokenService.get_status/get_quota/update_quota/get_usage`、`log_operation` 签名在 service/task/api/前端全链路一致；`SettingResponse.value` 用 `Optional[Any]` 兼容 string/掩码 `***`；`TokenStatusResponse` 字段对齐 §9.2.6。

**4. 并行隔离核对：** 不碰 test_case.py / models/script.py / ai_case_tasks.py / tasks/。仅改 ai_gateway.py（纯加可选参数 + 末尾加 log_ai_call 函数）、test_point_generator.py、test_case_generator.py（加 project_id 传参，签名向后兼容）。

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-24-system-settings.md`.**
