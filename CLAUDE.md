# MoonTest 项目指引

## ⭐ 当前状态（2026-09-14 存档）——下次会话必读

**元素管理验收第3轮修复完成（896 测试全过，已 commit），待用户重验问题 2/6/7/8/12/13/14/15。**

→ 存档：记忆 `moontest-session-20260914-element-mgmt-round3`（含两大根因：JSONB flag_modified、迁移级联删除）
→ 验收清单：`docs/ACCEPTANCE_CHECKLIST_3PHASES.md`（34 验收点）

### 下次会话开工顺序
1. `git status` + `git log --oneline -5` 确认现场（本轮修复均在 master 顶部）
2. 等用户重验反馈：问题2（高亮框，先 Ctrl+Shift+R）、6/7（定位器添加/调序）、8（校验+环境URL）、12/13（回收站/迁移双树）、14/15（尺寸/编辑弹窗）
3. ⚠️ 后端 8000 无 --reload：改后端必须重启；重启前先 `Get-NetTCPConnection -LocalPort 8000` 查清并杀干净全部进程（曾因双进程导致验证假失败）
4. 全过则三阶段整体收官存档 + worktree 清理

### 三阶段状态
- 阶段1 元素资产 ✅ / 阶段2 转脚本+测试集 ✅ / 阶段3 回归+菜单+登录态 ✅
- 用户验收：大部分通过；第3轮 9 个问题已修待重验（见上）

### 缺口待办
credentials 明文脱敏（Important）/登录态链路激活（RunConfig+inject_state+前端UI）/AI识别覆盖人工移出确认

## 工作约定
- Superpowers 流程 + subagent-driven；每 Task 收官贴全表；commit 只 stage 指定文件
- worktree 用 `git worktree add <path> -b <branch> master` 手动建
- agent 中断恢复：检查现场 → 新 agent 接续（已验证）
- 测试基线：770 passed（master）；celery `-A app.tasks`；AI provider glm-2.5；PG16 localhost:5433

## 项目结构
- backend: FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + Redis
- frontend: Vue3 + Element Plus；需求文档: docs/REQUIREMENTS_V1.1.md
