# 系统设置（#10）设计 — AI设置 / 运行配置 / 环境管理 / Token成本管理 / 操作日志

**版本**：v1.0
**日期**：2026-08-24
**作者**：Claude Code (Opus 4.8)
**状态**：待审批
**流程**：Superpowers（brainstorming → writing-plans → TDD → 编码 → verification）
**范围依据**：需求 §10 系统设置 + §11.4 Token成本管理 + §9.2.6 Token预警

---

## 1. 概述

补全 #10 系统设置模块，含 5 个子项：AI设置、运行配置、环境管理、Token成本管理、操作日志。不做用户体系与鉴权（§10 用户管理标记为可选，本期跳过）。延续"先骨架后大模型"集成策略：AI 调用走可插拔 gateway，provider key 存 DB 可热改，联调时填入真实 key。

### 1.1 已确认决策

- **范围**：5 子项全做
- **AI provider 配置存储**：DB 表 + 热改（不重启即生效）
- **运行配置存储**：纳入同一 system_setting 表（按 category 区分 ai/runtime）
- **环境管理**：被测环境列表（dev/staging/prod），不含执行环境
- **用户/鉴权**：不做，created_by/changed_by 沿用 system 占位值
- **Token 路由**：并入 `/system` 前缀（`/system/tokens/*`），不单列
- **埋点范围**：ai_gateway 加可选参数；现有 generator 顺手传 project_id/stage
- **并行隔离**：本会话用 git worktree，不碰 test_case.py / ai_case_tasks.py / tasks/

### 1.2 不做（YAGNI）

- 用户体系 / JWT 登录 / 路由鉴权中间件
- 执行环境（浏览器版本/headless/执行机）—— 归 #5
- 操作日志自动拦截（仅 helper 显式调用，不侵入所有 API）
- token_usage 独立表（与 ai_call_log 重复，并入聚合）

---

## 2. 数据层

### 2.1 新表（全部 idempotent 迁移）

| 表 | 用途 |
|---|---|
| system_setting | 通用 KV 配置（AI设置 + 运行配置共用） |
| test_env | 被测环境 |
| token_quota | 项目 Token 配额 |
| operation_log | 操作日志 |
| ai_call_log | AI 调用流水（execution.py:54 已有 model，历史上未建表，本次补建） |

### 2.2 system_setting

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| category | String(20) | `ai` / `runtime` |
| key | String(100) | 如 `glm-4.api_key` / `heal.strategy` |
| value | Text | 非敏感值明文 |
| value_encrypted | Text | 敏感值 Fernet 密文（is_secret=true 时用此列） |
| value_type | String(20) | string/int/float/bool/json |
| is_secret | Boolean | 是否加密存储 |
| description | String(500) | |
| updated_by | String(50) | |
| updated_at | DateTime | onupdate |
| 约束 | UNIQUE(category, key) | |
| 索引 | idx_system_setting_category | |

### 2.3 test_env

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| name | String(50) | |
| url | String(500) | |
| env_type | String(20) | dev/staging/prod |
| status | String(20) | active/inactive |
| credentials | JSONB | 账号密码等（敏感字段加密） |
| created_by | String(50) | |
| created_at / updated_at | DateTime | |

### 2.4 token_quota

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK→project | |
| total_quota | Integer | 默认 100000 |
| alert_threshold | Integer | 默认 10（百分比） |
| updated_at | DateTime | |

> `used` 不存表：运行时从 ai_call_log 聚合 SUM 得出，避免并发累加脏写。

### 2.5 operation_log

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| module | String(50) | system/element/case/execution |
| action | String(50) | update_setting/create_env/... |
| target_type | String(50) | |
| target_id | String(100) | |
| detail | JSONB | 变更前后值（secret 脱敏） |
| operator | String(50) | |
| ip | String(50) | |
| created_at | DateTime | |
| 索引 | idx_op_log_created / idx_op_log_module | |

### 2.6 ai_call_log（已有 model execution.py:54，补建表）

字段沿用现有 model：id/project_id/model/tokens_used/tokens_cost/stage/status/created_at。

### 2.7 加密

- `backend/app/core/security.py`：Fernet 对称加密 helper（`encrypt(plain)->str` / `decrypt(cipher)->str`）
- 密钥从 `settings.JWT_SECRET_KEY` 派生（PBKDF2 → 32 字节），不新增配置项
- 敏感字段（API key、env credentials）存 `value_encrypted`，非敏感存 `value`

### 2.8 迁移 `add_system_settings_tables.sql`

5 表 CREATE IF NOT EXISTS + 索引 + 约束 + 给每个现有 project 插默认 token_quota 行（total=100000, threshold=10）。

---

## 3. 服务层 + AI 埋点

### 3.1 新建服务

| 文件 | 职责 |
|---|---|
| services/system_setting_service.py | KV 读写 + 加解密 + 进程缓存（30s TTL） |
| services/token_service.py | 配额读写 + 状态聚合 + 预警判定 |
| services/test_env_service.py | 被测环境 CRUD |
| services/operation_log_service.py | 操作日志记录 helper |
| core/security.py | Fernet 加解密 |

### 3.2 ai_gateway 埋点改造（保守，纯加可选参数）

`AIGateway.chat_completion` 增加 3 个可选参数：
```python
async def chat_completion(self, messages, *, project_id=None, stage=None, operator=None, **kwargs):
    result = await provider.chat_completion(...)
    if project_id:
        await self._log_ai_call(project_id, provider_name, result.get("tokens", 0), stage, "success")
    return result
```

- `_log_ai_call`：异步写 ai_call_log，失败容错（不影响 AI 结果返回）
- 现有调用方向后兼容：不传 project_id 则不记 log
- **本次顺手给** test_point_generator / test_case_generator / hallucination_detector 传上 `project_id` + `stage`，使 token 统计真实生效

### 3.3 provider key 热读取

gateway 新增 `_resolve_provider_config(provider)`：优先读 system_setting（带 30s 进程缓存），无则回退 settings.py/.env 默认。AI设置页改 DB 值后，缓存失效，下次调用即用新值。

### 3.4 token_service.get_token_status(project_id)（对齐 §9.2.6）

```
total_quota       ← token_quota.total_quota（无记录取 settings.TOKEN_QUOTA=100000）
used              ← SUM(ai_call_log.tokens_used WHERE project_id)
remaining         ← total - used
percentage        ← used / total * 100
is_warning        ← remaining/total*100 ≤ alert_threshold(10%)
recent_daily_avg  ← 近7日 SUM / 7
estimated_days_remaining ← remaining / recent_daily_avg（日均0返回null）
```

### 3.5 operation_log helper

`log_operation(module, action, target_type, target_id, detail, operator, ip)`：显式调用，在系统设置/环境/配额的写操作里调用。非自动拦截。

---

## 4. API 层（单 router 文件 system.py，prefix /system）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /system/settings?category=ai\|runtime | 列配置（secret 返回 `***`） |
| GET | /system/settings/{key} | 取单个（secret 脱敏，`?reveal=true` 取明文） |
| PUT | /system/settings/{key} | 改单个（热改 + 刷缓存） |
| POST | /system/settings/test-connection | 用当前 AI 配置发 ping 验证 key |
| GET | /system/runtime-config | 运行配置聚合展示 |
| GET/POST/PUT/DELETE | /system/envs[/{id}] | 被测环境 CRUD |
| GET | /system/operation-logs?module=&page= | 操作日志分页 |
| GET | /system/tokens/status?project_id= | §9.2.6 Token 预警状态 |
| GET | /system/tokens/quota?project_id= | 取配额 |
| PUT | /system/tokens/quota?project_id= | 改配额/阈值 |
| GET | /system/tokens/usage?project_id=&days=7 | 按 stage/model 聚合用量 |

注册到 `api/__init__.py`：`api_router.include_router(system.router, prefix="/system", tags=["system"])`。

---

## 5. 前端

### 5.1 新建文件

| 文件 | 内容 |
|---|---|
| api/system.js | 全部系统设置 API 封装 |
| views/system/AISettings.vue | provider 列表（glm-4/qwen/deepseek/claude）：key 密文+编辑、url、默认 provider 单选、fallback 链多选、测试连接按钮 |
| views/system/RuntimeConfig.vue | 自愈策略下拉、置信度阈值、缓存 TTL、执行 timeout、重试次数、回写阈值；分组卡片 |
| views/system/EnvManagement.vue | 被测环境 CRUD 表格 + 编辑弹窗 |
| views/system/TokenDashboard.vue | 配额进度条 + 预警阈值 + 按 stage 饼图/model 柱图/按天趋势（ECharts）+ 日均/剩余天数卡片 |
| components/TokenWarningBanner.vue | 全局预警横幅 |

### 5.2 路由（router/index.js 补缺失 + 新增）

- `/settings/ai` → AISettings（修复现有死链）
- `/settings/runtime` → RuntimeConfig（修复死链）
- `/settings/env` → EnvManagement（修复死链）
- `/settings/tokens` → TokenDashboard（新增，菜单加「Token成本管理」）

### 5.3 预警横幅

- App.vue 挂载 TokenWarningBanner
- 切项目时触发 + 每 5 分钟轮询 `/system/tokens/status`
- `is_warning=true` 时红色横幅 + 一次 ElMessageBox 弹窗
- 已弹过的项目存 sessionStorage 不重复弹（刷新后重置）
- `document.hidden` 时暂停轮询

---

## 6. 测试策略（延续 mock，符合"先骨架后大模型"）

| 文件 | 覆盖 |
|---|---|
| test_system_setting_service.py | KV 读写 + 加解密（mock db） |
| test_token_service.py | 状态聚合算术（SUM/percentage/is_warning/estimated_days）纯逻辑（mock db.execute） |
| test_test_env_service.py | CRUD（mock db） |
| test_operation_log_service.py | 记日志（mock db.add） |
| test_api_system.py | 端点契约（dependency override，不起真实 DB） |
| test_ai_gateway_logging.py | 埋点：mock provider 返回 tokens 断言 ai_call_log 被写；project_id=None 不写；写失败不影响返回 |

无真实 DB / 无真实 LLM 调用，留联调阶段验证。

---

## 7. 风险与边界

- **共享文件 ai_gateway.py**：#4 会话可能也改，纯加可选参数 + 新方法保守改法，冲突时手动合并
- **ScriptAsset / test_case.py / tasks/**：不碰，#4 在改
- **token_quota 默认行**：迁移给每个现有 project 插默认行；新建 project 时由 projects 模块后续补 hook（本期不强制）
- **加密密钥来源**：复用 JWT_SECRET_KEY 派生，生产环境须确保该值已变更（非默认）

---

## Self-Review 记录（2026-08-24）

| 项 | 结果 |
|---|---|
| 占位符扫描 | 无 TBD/TODO |
| 内部一致性 | token_usage 并入 ai_call_log、used 不存表、tokens 并入 /system 前缀——全文一致 |
| 范围检查 | 5 子项边界清晰，单 spec 可承载，约 2-3 天 |
| 歧义检查 | 已澄清：不存 used（聚合算）、不自动拦截日志、不做用户体系、tokens 路由并入 system |

确认后转入 writing-plans 生成实施计划。
