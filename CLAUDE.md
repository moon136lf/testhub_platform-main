# MoonTest 项目指引

## ⭐ 当前状态（2026-09-15 存档·二）——下次会话必读

**锚点定位+轴定位（缺口1+2）已完成全流程（subagent-driven：每任务实现+双审查+终审）合并 master（af5fb2a，918 测试，backend 已重启生效）。元素管理模块验收通过 ✅（编辑=详情合并终态）。**

→ 详细存档：记忆 `moontest-anchor-axis-merged`（交付内容/E2E 实证结论/源码链路设计决策）
→ 下一个大项：**源码定位器链路**（缺口3，设计决策已定稿，spec 未写——先写 docs/superpowers/specs/2026-09-15-static-scan-locators-design.md 给用户过目，再出计划）

### 下次会话开工顺序
1. `git status` + `git log --oneline -3` 确认现场（近期有并行会话提交，均已合 master）
2. 用户说「继续源码定位器链路」→ 写 spec（白盒扫描扩展+zip上传+glm-5.2+static_scan 标记+hash 增量复用，决策定稿见记忆）
3. 三阶段剩余验收点（docs/ACCEPTANCE_CHECKLIST_3PHASES.md）继续推进

### 长期教训（已入持久记忆，自动加载）
- SQLAlchemy JSONB 原地变异必须 flag_modified（元素定位器曾静默丢失）
- ORM cascade delete-orphan + db.delete(parent) 会级联删已载入 session 的旧子集合（删页迁移曾丢元素）
- 前端开发先对照已有页面对齐 UI 规范（操作列宽/字号/间距），避免验收返工
- backend 8000 无 --reload，改后端必须重启；重启前查清并杀干净全部占端口进程
- Element Plus 页面（class 容器无 id、label 祖先形态）anchor/sibling-label 产出 0 是结构性——真验收要在 DM（iview）页面做

### 缺口待办
credentials 明文脱敏（Important）/登录态链路激活（RunConfig+inject_state+前端UI）/AI识别覆盖人工移出确认/会话抓取高亮框偏移（问题2 未最终确认）

## 工作约定
- Superpowers 流程 + subagent-driven；每 Task 收官贴全表；commit 只 stage 指定文件
- worktree 用 `git worktree add <path> -b <branch> master` 手动建
- agent 中断恢复：检查现场 → 新 agent 接续（已验证）
- 测试基线：918 passed（master）；celery `-A app.tasks`；AI 实际模型 glm-5.2（gateway provider key 仍叫 "glm-2.5" 是历史遗留）；PG16 localhost:5433

## 项目结构
- backend: FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + Redis
- frontend: Vue3 + Element Plus；需求文档: docs/REQUIREMENTS_V1.1.md
