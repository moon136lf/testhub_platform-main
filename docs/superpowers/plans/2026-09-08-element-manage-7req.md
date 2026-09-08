# 元素管理页 7 条需求 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 元素管理（ElementList.vue）7 条 UX 需求：右键新建子级/同级页面、来源中文、去掉全局元素树节点、所属页面列、作用域筛选、启用/禁用开关（控制转脚本可用性）、序号+分页+更新时间倒序。

**现状（阶段1已交付，直接复用）:** scope 字段（page/global）+ el-tag 已存在；右键菜单已有重命名/上移/下移/删除；pages-tree CRUD 端点齐全；/elements-asset 列表已支持 scope/page_id/keyword 过滤。

---

### Task 1: 页面树右键「新建子级页面 / 新建同级页面」

**Files:**
- Modify: `frontend/src/views/ElementList.vue`
- Backend check: `POST /elements-asset/pages-tree` 已支持 parent_id（SubPageCreateRequest）——确认即可

- [ ] ctxMenu 增加 `page` 上下文（当前右键的页面 id），菜单项改为动态：
  - 右键空白/根 → 只显示「新建同级页面」（parent_id=null）
  - 右键页面节点 → 「新建子级页面」（parent_id=该页 id）+「新建同级页面」（parent_id=该页 parent_id 或 null）+ 原有重命名/上移/下移/删除
  - 新建弹窗：页面名 + 页面 URL（可选，无 URL 时后端生成占位 `/__placeholder__/{name}`——检查 create_sub_page 行为并遵循）
- [ ] vite build + 手动验收

- [ ] Commit `feat(elements): page tree ctx menu — create sub/sibling pages (#elem-mg T1)`

### Task 2: 来源列中文映射

- [ ] `source` 列 template：manual→手工 / auto→自动抓取 / healed→自愈 / ai_fixed→AI修复（el-tag）
- [ ] Commit `feat(elements): source column chinese labels (#elem-mg T2)`

### Task 3: 去掉左侧「全局元素」树节点（保留作用域筛选代替）

- [ ] 删除「🌐 全局元素」tree-node 与 selectNode('global')；全局元素通过 Task 4 的作用域筛选下拉查看
- [ ] Commit `feat(elements): remove global tree node — scope filter replaces it (#elem-mg T3)`

### Task 4: 右侧列表加「所属页面」列 + 作用域筛选下拉

**Files:** ElementList.vue + 检查后端 list 返回是否带 page_name（to_dict 可能没有——需 join 或 Python 补充）

- [ ] 后端 `list_elements_asset` 返回每项附 `page_name`（从 page_repository 批量查，map 后填入 to_dict）
- [ ] 前端加「所属页面」列（scope=global 显示「—」）
- [ ] 作用域下拉（全部/页面级/全局）→ 传 scope 参数给 /elements-asset（已支持）
- [ ] 测试：后端 page_name 填充单测
- [ ] Commit `feat(elements): page-name column + scope filter (#elem-mg T4)`

### Task 5: 启用/禁用开关（控制转脚本可用性）

**Files:**
- Backend: `element_repository.status` 已有 active/deprecated——语义对齐：启用=active，禁用=deprecated（**不改 schema**，复用 status 字段；或新增 boolean `enabled`——**决策：复用 status**，与转脚本侧 find_by_name 的 `status == "active"` 过滤天然联动）
- Backend: `PUT /elements-asset/{element_id}/status` 端点（active↔deprecated 切换）
- Frontend: 状态列改 el-switch（active→开，deprecated→关）；关闭时转脚本 find_by_name 查不到（已有行为）

- [ ] 失败测试：切换端点 + find_by_name 过滤 deprecated
- [ ] 实现 + 前端 switch（@change 调端点，失败回滚 UI）
- [ ] 验证：禁用后用例转脚本无法引用该元素（script_convert 侧确认过滤链路）
- [ ] Commit `feat(elements): element enable/disable switch — deprecated excluded from script conversion (#elem-mg T5)`

### Task 6: 序号列 + 翻页 + 更新时间倒序

- [ ] 前端：序号列（type=index，按页内序号）；el-pagination（每页默认 10，可选 10/20/50）；后端 /elements-asset 加 page/page_size 参数（Python 切片或 SQL limit/offset）+ order_by updated_at desc nullslast
- [ ] 测试：分页参数单测
- [ ] Commit `feat(elements): pagination + updated_at desc ordering (#elem-mg T6)`

### Task 7: 端到端验证 + 收尾

- [ ] 全量测试 + vite build
- [ ] 7 条需求逐条对照验收
- [ ] Commit（如有 fixup）

---

## 注意
- status 复用决策影响转脚本：确认 script_convert/self_heal 查询处均已过滤 status=='active'（find_by_name 已过滤；grep 其他引用点确认）
- 另一会话工作已全部提交，工作区干净；element_service.py/elements.py 无冲突
