# 阶段1执行进度跟踪

计划：docs/superpowers/plans/2026-09-07-element-assets-phase1.md
worktree：D:\MoonTest\.claude\worktrees\elem-assets-phase1（分支 worktree-elem-assets-phase1，基线 master@547956e，580 测试通过）

| Task | 内容 | 状态 | commit |
|---|---|---|---|
| T0 | 提交工作区 16 项修复 | ✅ bbf4ba4 + b178c23（master 上） | - |
| T1 | 迁移+模型扩展 | ✅ 完成（两阶段审查通过，修复 page_id 序列化 + FK 对齐） | 8596b6a + cae6f95 |
| T2 | 定位器 score 统一 | ✅ 完成（复审 Approved：find 回退次选+正则畸形用例） | bff0473 + 2a92877 |
| T3 | 引用计数 | ✅ 完成（两阶段审查通过，补 list 空名保护） | 8285cfb + 04491a6 |
| T4 | 元素CRUD+调序+回收站 | ✅ 完成（两阶段审查通过：越界防护+时区修复） | 1be816a + 7f98e1e |
| T5 | 页面树 | ✅ 完成（两阶段审查通过：占位URL标记+迁移目标校验） | 8f3215d + 197ad2e |
| T6 | 全局元素 | ✅ 完成（两阶段审查 Approved，5 Minor 记 polish 清单） | c5cf84a |
| T7 | 快速校验 | ✅ 完成（两阶段审查 Approved：直驱链路裁决成立） | 6794995 |
| T8 | 导入导出 | ✅ 完成（两阶段审查通过：跨项目 page_name 映射+可见性） | 7968b62 + 9919ff4 |
| T9 | 前端路由+列表页 | 🔄 修审查问题中（Important: 抽屉调序下标错位） | 235fd16 |
| T10 | 菜单+真浏览器验收 | ⬜ | - |

注意：EnterWorktree 原生工具因 origin/main 指向旧仓库产生孤儿基座，已改用 git worktree add（从 master），已 EnterWorktree path 接管会话。

## 审查发现遗留（阶段2 待办）
- uq_element_repository_page_element 唯一约束对 global 元素失效（page_id=NULL, NULLS DISTINCT）——阶段2 做"元素升级为全局"时应用层去重或部分唯一索引
- 模型 FK ondelete 与迁移不一致 → 已在 T1 修复统一为 SET NULL
- **阶段2 fallback 消费端以 verified 标志做质量判断**（reorder 重排会压平原始 score 差距，T4 审查发现）
- **同名全局元素**：find_by_name scalar_one_or_none 会 MultipleResultsFound——需名称唯一校验（T6 审查）
- **手工建页面级元素不回写 page.element_count**——页面元素数徽标可能不准（T6 审查）
- keyword ilike 未转义 %/_ 通配符（T6 审查，管理页搜索影响极小）
