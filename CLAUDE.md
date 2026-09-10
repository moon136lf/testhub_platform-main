# MoonTest 项目指引

## ⭐ 当前状态（2026-09-09 存档·关机）——下次会话必读

**重构三阶段代码已全部合并 master（770 测试），用户真浏览器验收进行中——本轮收到 2 个新反馈，排查完成一半待实施。**

→ 最新存档：**`docs/SESSION_HANDOFF_2026-09-09-acceptance-round2.md`**（2 个反馈的根因排查结果+修复方向，先读这个）
→ 验收清单：`docs/ACCEPTANCE_CHECKLIST_3PHASES.md`（34 验收点，含已知问题清单）

### 下次会话开工顺序
1. `git status` 确认 Dashboard 双Y轴（charts.js/Dashboard.vue）是否已提交——可能未提交！
2. **修复反馈1**：编辑脚本断言合并进行内（scriptMapping.js + StepEditor.vue + step_codegen.py 三处联动，方案已写好在存档第三节）
3. **修复反馈2**：元素库模糊匹配（find_by_name 精确匹配→ilike+双向contains+element_text 二轮，方案在存档）——登录元素已抓取但转脚本查不到的根因
4. 两个修复 → 用户继续验收 → 全过则**三阶段整体收官存档** + worktree 清理

### 三阶段状态
- 阶段1 元素资产 ✅ / 阶段2 转脚本+测试集 ✅ / 阶段3 回归+菜单+登录态 ✅（均已合并，e9dcc6b 等）
- 用户验收：大部分通过（菜单/元素管理/转脚本/UI自动化/回归对齐/Dashboard双Y轴）；**2 个反馈修复中**（见上）

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
