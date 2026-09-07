# MoonTest 项目指引

## ⭐ 当前状态（2026-09-04 周五 关机前存档）——下次会话必读

**正在进行的系统重构，方案已定稿、代码未动工。** 完整沟通结果与计划在：

→ **`docs/SESSION_HANDOFF_2026-09-04-refactor-plan.md`** ←（先读这个）

### 下次会话开工顺序
1. **提交工作区**：16 项 bug 修复全在工作区未提交（清单见 handoff 文档第三节），分 2-3 个 commit
2. **写阶段1实施计划**（元素资产拆分+定位器score统一），发用户确认
3. TDD 动工，验收后推进阶段2、3

### 方案速览
- 三阶段：①元素资产（拆两页+定位器置信度统一+全局元素+回收站）②转脚本+测试集（步骤化脚本编辑器+assert_db）③回归独立+菜单重组+登录态复用(storage_state)
- 二期待办：`docs/ROADMAP_PHASE2_TODO.md`
- UI 蓝本：千问原型 v6（提炼在 handoff 第二节）
- 用户核心认知：UI自动化=回归/冒烟层；平台测自己=第一验收标准

## 工作约定
- Superpowers 流程（brainstorm→plan→TDD→编码→审查），不主动写总结报告
- commit 前只 stage 指定文件（多会话混入教训）
- 后端测试基线：541 passed；backend 用 uvicorn --reload（改动热加载）
- celery 启动：`python -m celery -A app.tasks worker --pool=solo -l info`（不是 -A app.tasks.celery_app）
- AI provider：glm-2.5（已全局替换 glm-4）

## 项目结构
- backend: FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + Redis，测试在 backend/tests/
- frontend: Vue3 + Element Plus，`npm run build` 验证
- 需求文档: docs/REQUIREMENTS_V1.1.md；日志规范: docs/LOGGING.md
