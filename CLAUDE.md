# MoonTest 项目指引

## ⭐ 当前状态（2026-09-07 存档）——下次会话必读

**系统重构进行中。阶段1（元素资产）代码已全部完成并审查通过（16 commits 在 worktree，待真浏览器验收+合并），阶段2/3 未开工。**

→ 最新存档：**`docs/SESSION_HANDOFF_2026-09-07-phase1-execution.md`**（阶段1 交付清单/T10 验收清单/阶段2 待办/执行方法论）
→ 重构总方案：`docs/SESSION_HANDOFF_2026-09-04-refactor-plan.md`（菜单结构/三阶段范围/登录态设计）

### 下次会话开工顺序
1. **T10 真浏览器验收**（8 项清单见 handoff 第一节末；建议在 worktree 验收）
2. **合并阶段1**：worktree-elem-assets-phase1 → master（17 commits 含进度文档），合并后跑全量测试
3. **开工阶段2**（转脚本+测试集）：步骤化脚本编辑器（用户点名核心件，含 assert_db）→ 转脚本页改造 → test_set 模型 + UI自动化测试页 → 删回归页（隐藏代码）
4. 阶段3（回归独立+菜单重组+登录态复用）照原方案

### 方案速览
- 三阶段：①元素资产 ✅②转脚本+测试集（步骤化脚本编辑器+assert_db+失败截图+可自动化评级）③回归独立+菜单重组+登录态复用(storage_state)
- 阶段2 审查待办 11 条在 handoff 第三节（fallback 用 verified 标志/同名全局元素去重等）
- 二期待办：`docs/ROADMAP_PHASE2_TODO.md`
- 用户核心认知：UI自动化=回归/冒烟层；平台测自己=第一验收标准

## 工作约定
- Superpowers 流程 + **subagent-driven 执行**（每 Task 独立 subagent 带代码级 spec → spec 审查 → 质量审查 → 修复循环 → 复审收官）；每 Task 收官展示全部任务表
- commit 前只 stage 指定文件；worktree 用 `git worktree add <path> -b <branch> master` 手动建（EnterWorktree 原生工具会用 origin/main 旧仓库基座产生孤儿 commit）
- 后端测试基线：658 passed（阶段1 worktree）；backend 用 uvicorn --reload
- celery 启动：`python -m celery -A app.tasks worker --pool=solo -l info`
- AI provider：glm-2.5；数据库 PG16 localhost:5433/moontest（worktree 无 .env，用主仓 backend/.env）

## 项目结构
- backend: FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + Redis，测试在 backend/tests/
- frontend: Vue3 + Element Plus，`npm run build` 验证
- 需求文档: docs/REQUIREMENTS_V1.1.md；日志规范: docs/LOGGING.md
