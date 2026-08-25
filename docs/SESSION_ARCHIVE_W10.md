# MoonTest 会话存档 — #10 系统设置（worktree 独立）

> 本文件随 worktree `module10-system-settings` 维护，记录 #10 模块开发进度。
> 格式参考 master 的 `docs/SESSION_ARCHIVE.md`。最新快照在最上方，旧的在下。
> master 的定时存档（每小时 :07）跑在 master 分支，看不到本 worktree 提交——故此文件独立存在，合回 master 时一并进入。

---

## 快照 #1 — 2026-08-25（T1-T12 全完成）

**当前分支**：worktree-module10-system-settings（工作树干净）

### 未提交改动
无（工作树干净）

### 最近 7 条提交
```
3bcd0fa feat(system): TokenDashboard + warning banner (W10)
f534c20 feat(system): AISettings + RuntimeConfig + EnvManagement pages + routes (W10)
13c4e00 feat(system): frontend API wrapper (W10)
b1c7570 feat(system): system API router (settings/envs/tokens/oplog/runtime) (W10)
91ddfb2 feat(system): ai_gateway token logging + generators pass project_id (W10)
544eb9f fix(system): drop unused import; silence db.add warning; add get_usage test (W10)
08b33e8 fix(system): revert TestEnvService to UUID(env_id); use UUID-shaped test ids (W10)
```

### 13 task 进度
- ✅ T1 AES helper（7bd2e7c）
- ✅ T2 4 system models（df6d13f + a4b34f4）
- ✅ T3 幂等迁移 5 表（fdcdd02）
- ✅ T4 pydantic schema（07b3c61）
- ✅ T5 SystemSettingService（86c73cf + f3a2838）
- ✅ T6 TestEnvService + OperationLogService（a67d404 + 08b33e8 回退）
- ✅ T7 TokenService（988f46f + 544eb9f）
- ✅ T8 ai_gateway 埋点 + generators 传 project_id（91ddfb2）
- ✅ T9 system API router（b1c7570）
- ✅ T10 前端 api/system.js（13c4e00）
- ✅ T11 前端 3 页 + 路由（f534c20）
- ✅ T12 前端 TokenDashboard + 预警横幅（3bcd0fa）
- ⬜ T13 全量验证 + 收尾

### 测试 / 构建
- 后端全量：223 passed（T9 后），mock 无真实 DB/LLM
- 前端：`npm run build` 通过（TokenDashboard chunk 正常 emit，路由已取消注释生效）

### 本会话进展
- **#10 系统设置 5 子项后端+前端骨架全完成**：AI设置/运行配置/环境管理/Token成本管理/操作日志。
- **关键决策**：
  - tokens 路由并入 `/system` 前缀（不单列 /tokens）；token `used` 不存表，从 ai_call_log 聚合 SUM。
  - ai_call_log 模型早存于 execution.py:54 但从未建表，本次迁移补建。
  - `SystemSetting.category`/`value_type` 用 `Enum(native_enum=False)`（VARCHAR-backed），迁移用 `VARCHAR(20)+CHECK`（非原生 PG enum）。
  - 加密用 pycryptodome AES-GCM（环境无 cryptography/fernet），密钥从 JWT_SECRET_KEY 派生；已 pin `pycryptodome==3.23.0`。
  - OperationLogService 加 `list` 方法（option B），router 保持 thin。
  - ai_gateway 埋点：`chat` 加 keyword-only `project_id/stage/operator`，保守纯加法，向后兼容；`log_ai_call` 独立 AsyncSession best-effort。
- **审查踩坑**：
  - T6 `UUID(env_id)`→裸字符串偏差被审查 REVERT（asyncpg 源码证实裸字符串对真实 uuid 列会 ValueError；mock 测不出 DB 适配层问题）→ 恢复 `UUID(env_id)` + 测试改用 UUID 字符串。
  - T8 deferred imports + importlib 测试机制（forced by test_ai_gateway 的 MagicMock config + test_knowledge_service 的 sys.modules 污染），审查用 `__globals__` 内省证实测的是真实生产代码路径，ACCEPTABLE。
- **#4 并行隔离**：整个 #10 仅共享 `ai_gateway.py`（T8 保守加可选参数，低合并冲突风险），其余文件与 #4 无重叠。master 上 #4 已完成（238 测试），#10 worktree 待合回。
- **诚实边界**：ai_gateway.log_ai_call 的 DB 写路径未被测试覆盖（mock 替换了 log_ai_call），联调阶段补真实 DB 验证。`operator` 参数 dead（接受未用）。

### 下一步建议
1. T13：后端全量核对（应 230+ 测试）+ 前端最终构建 + 迁移脚本检查 + 更新 TODO_LIST（标 #10 完成，5/11）+ 最终 commit。
2. T13 后用 `superpowers:finishing-a-development-branch` 评估合回 master（注意 ai_gateway.py 与 #4 的合并，保守改法应可自动合并）。
3. 合回后 master 定时存档（每小时 :07）才会看到 #10 内容。

---
