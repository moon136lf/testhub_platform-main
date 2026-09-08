# MoonTest 项目指引

## ⭐ 当前状态（2026-09-08 存档）——下次会话必读

**重构三阶段：阶段1/2 已合并 master；阶段3 执行到最后一个功能任务。**

→ 最新存档：**`docs/SESSION_HANDOFF_2026-09-08-phase3-progress.md`**（T6 任务定义/T7 验收清单/缺口清单）

### 下次会话开工顺序
1. **T6 评审应用 LLM 增强**（任务定义已写好在存档第二节，派 subagent 即可）
2. **T7 收官**：全量测试+build → 合并 worktree-regression-menu-login-phase3 → master → 重启服务 → 用户真浏览器验收（清单在存档）
3. **总收官**：三阶段完成存档 + worktree 清理 + 假成功清单更新

### 阶段3 已交付（9 commits 待合并）
修假成功（编辑器脚本真实执行）/for_regression 回归归属/回归数据源切换/前端对齐补任务/source_type 透出/登录态复用（单例修复）/菜单三组重组

### 缺口待办（存档第三节）
credentials 明文脱敏（Important）/登录态链路激活（RunConfig 字段+inject_state+前端UI）/AI识别覆盖人工移出确认

### 方案速览
- 三阶段：①元素资产 ✅ ②转脚本+测试集 ✅ ③回归+菜单+登录态 🔄
- 二期待办：`docs/ROADMAP_PHASE2_TODO.md`
- 用户核心认知：UI自动化=回归/冒烟层；平台测自己=第一验收标准

## 工作约定
- Superpowers 流程 + **subagent-driven 执行**（每 Task 带代码级 spec → spec 审查 → 质量审查 → 修复 → 复审收官）；每 Task 收官贴全表
- commit 前只 stage 指定文件；worktree 用 `git worktree add <path> -b <branch> master` 手动建
- agent 中断恢复：检查现场（git log/status + 跑测试）→ 新 agent 接续（已两次验证）
- 后端测试基线：741 passed（阶段3 worktree）；backend uvicorn --reload
- celery：`python -m celery -A app.tasks worker --pool=solo -l info`；AI provider glm-2.5；PG16 localhost:5433/moontest（worktree 无 .env 用主仓 backend/.env）

## 项目结构
- backend: FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + Redis，测试在 backend/tests/
- frontend: Vue3 + Element Plus，`npm run build` 验证
- 需求文档: docs/REQUIREMENTS_V1.1.md；日志规范: docs/LOGGING.md
