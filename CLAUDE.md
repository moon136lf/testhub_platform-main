# MoonTest 项目指引

## ⭐ 当前状态（2026-09-15 存档）——下次会话必读

**元素管理模块验收全部通过（5 轮修复收官）✅。「编辑=详情合并」终态模式已确立（操作列=编辑+删除，860px 编辑弹窗含定位器增删调序+校验，双树迁移）。**

### 下次会话开工顺序
1. `git status` + `git log --oneline -5` 确认现场（近期有并行会话提交：时间格式统一 7ce5153、IA改造 a2333c8 等，均已合 master）
2. 继续验收剩余模块（用例转脚本/回归/Dashboard 等，见 `docs/ACCEPTANCE_CHECKLIST_3PHASES.md` 34 验收点）
3. 全过 → **三阶段整体收官存档** + worktree 清理

### 长期教训（已入持久记忆，自动加载）
- SQLAlchemy JSONB 原地变异必须 flag_modified（元素定位器曾静默丢失）
- ORM cascade delete-orphan + db.delete(parent) 会级联删已载入 session 的旧子集合（删页迁移曾丢元素）
- 前端开发先对照已有页面对齐 UI 规范（操作列宽/字号/间距），避免验收返工
- backend 8000 无 --reload，改后端必须重启；重启前查清并杀干净全部占端口进程

### 缺口待办
credentials 明文脱敏（Important）/登录态链路激活（RunConfig+inject_state+前端UI）/AI识别覆盖人工移出确认/会话抓取高亮框偏移（问题2 未最终确认）

## 工作约定
- Superpowers 流程 + subagent-driven；每 Task 收官贴全表；commit 只 stage 指定文件
- worktree 用 `git worktree add <path> -b <branch> master` 手动建
- agent 中断恢复：检查现场 → 新 agent 接续（已验证）
- 测试基线：770 passed（master）；celery `-A app.tasks`；AI provider glm-2.5；PG16 localhost:5433

## 项目结构
- backend: FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + Redis
- frontend: Vue3 + Element Plus；需求文档: docs/REQUIREMENTS_V1.1.md
