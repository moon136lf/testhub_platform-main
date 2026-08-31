# W7 #7 Review Report (7a09172..e31102b)

核实完成。#3 复用声明已验证：在 7a09172..e31102b 范围内，`case_refiner.py`、`test_case_service.py`、`schemas/refinement.py`、`models/test_case.py` 的 diff 为零（"复用不重写" 属实），`batch_refine` 确实构建了 `TestCaseService(self.db)` 并循环调用了 `refine_case`，最终提交的差异仅包含 reviews 路由（无 reports 遗留）。完整报告如下。

---

# #7 评审中心 Code Review 报告（7a09172..e31102b）

已独立复核：后端 357 passed（本机重跑确认）、前端 build 通过且 ReviewCenter chunk 正常 emit、4 条 `/api/v1/reviews/*` 路由注册确认、schema 校验行为用真实 Pydantic 探针验证（非只读代码）。

### 优势

- **"复用不重写" 纪律执行到位**：范围 diff 对 #3 四个受保护文件零改动；`batch_refine` 内部真实调用 `TestCaseService.refine_case`（review_service.py:60），未复制引擎逻辑。
- **自报偏离全部属实且必要**：逐一验证——计划测试 `["1","2","3"]` 中 `UUID('1')` 确实抛 `ValueError`（badly formed hexadecimal），偏离 2 的 try/except 是让测试可运行的最小改动；偏离 1 的 `valid_cases` 过滤与计划测试 `case_b.refinement_report=None → case_count==1` 的期望一致；T3 误带入的 reports 路由已确认还原干净（`api/__init__.py` 最终 diff 仅 1 行 reviews 注册）。
- **容错语义正确**：批量精修单条异常被捕获、记录日志、生成 `error` 条目后继续（有测试覆盖且断言真实输出形态）；`report is None`（case 不存在）返回 `"error": "case not found"`（review_service.py:65-67）。
- **可自动化率 null 安全**：total=0 → rate 0.0（有测试）；`refine_sync` 实测返回 int score（`max(0,min(100,...))`），与 `BatchRefineResultItem.score: Optional[int]` 匹配（float 会被 422 拒绝，但引擎不会产生）。
- **SQL 注入面干净**：全部查询走 SQLAlchemy 表达式 + UUID 强类型解析，`id.in_(id_list)` 参数化；畸形字符串在 UUID() 处被拒。
- **`review_status` 校验可靠**：`BatchReviewRequest` field_validator 引用单一事实源 `REVIEW_STATUSES`，探针实测 bogus 值 → ValidationError → 422。
- **前端前向兼容设计好**：`listCasesWithReview` 的 `review_status === undefined` 探测钩子，后端补齐列表字段后 detail 扇出自动失效——为正确的长期修复预留了零成本切换路径。
- **菜单死链修复正确**：`/ai/review` → `/reviews`，路由 `children` 内 `path: 'reviews'` 与菜单 index 匹配。
- **batch_update_review 项目限定正确**：查询含 `TestCase.project_id == pid` + `is_deleted.is_(False)`（review_service.py:121-125），跨项目 id 不会命中。

### 问题

#### 严重（必须修复）

无。功能可用、无数据损坏路径、无真实安全边界被突破（平台本无鉴权体系）。

#### 重要（建议修复）

1. **`listCasesWithReview` N+1 detail 扇出 —— 100 用例 = 最多 101 个请求/每次加载，且每次批量操作后重放**
   - `frontend/src/api/review.js:31-52`（扇出在 :36 `Promise.allSettled`）
   - 问题：后端 `CaseResponse`（列表项）确实不含评审 4 字段，前端并行拉全部 detail。关键放大器是 `backend/app/core/database.py:21` 用 **NullPool**——每个并发请求占一条真实 DB 连接，100 并发 detail 直顶 PostgreSQL 默认 `max_connections=100`，页面满载时可能连接耗尽（500）。且 `onBatchRefine/onBatchReview/onApply*` 每次成功后都 `loadAll()` → 再来一轮 100 请求。
   - 为什么：`page_size le=100` 封顶了最坏规模、内网单用户使它"能跑"，但这是全 diff 最脆弱的部分，而修复极便宜。
   - 怎么修（推荐单向修复）：在 `backend/app/schemas/test_case.py` `CaseResponse`（:165-183）+ `test_case_service.py:list_cases`（:158-176 组装处）补 `review_status/feasibility_level/refinement_report/refined_at` 四字段——模型字段现成、`_to_detail` 已有取法。前端钩子自动跳过扇出，`listCasesWithReview` 退化为纯 list。次选：前端分批（每批 10-20）执行 allSettled。

2. **项目精修报告的 `refined_at` 恒为 null —— spec §4.2 ④ "精修时间戳" 实际未落地**
   - `backend/app/services/review_service.py:97-98`
   - 问题：代码从 `report.get("refined_at")`（JSON 内）取时间戳，但实测 `CaseRefiner.refine_sync` 返回的 report **不含 `refined_at` 键**（只有 score/refined_case/suggestions/normativity/reuse_level/feasibility_level/cannot_automate_reason）——当前引擎产出的所有报告此处必为 None。真实时间在 `TestCase.refined_at` 列上，代码 `order_by(refined_at.desc())` 排序用的正是列，取值却读了 JSON。
   - 为什么：spec 明确要求报告区展示精修时间戳；计划测试用了带 `"refined_at"` 键的虚构 report 形状，掩盖了这一点（计划级 bug，非实现者偏离）。
   - 怎么修：`refined_at` 回退到 `c.refined_at`（列，isoformat），如 `max(c.refined_at for c in valid_cases if c.refined_at)`；前端报告区头部补时间戳展示。

3. **批量评审绕过了 #3 单条评审的 finalized 保护 —— 两条评审路径行为分叉**
   - `backend/app/services/review_service.py:128-133`
   - 问题：spec §3.1 说 batch_update_review "内部调 update_case"，实现是直接置字段（计划自身如此，属计划级偏离、已获准）。后果：`update_case` 对 `is_finalized` 用例抛 "Cannot update finalized test case"（test_case_service.py:290-292），#3 的 `PATCH /test-cases/{id}/review` 因此拒绝已定稿用例；#7 批量评审却可静默改已定稿用例的评审状态。同一用例单条评审 400、批量评审 200，用户可感知的不一致。
   - 怎么修：二选一并写进 spec/计划备注——(a) batch 查询加 `TestCase.is_finalized.is_(False)`（或计入 failure_count 上报）；(b) 明确决策"评审字段允许改已定稿用例"，回头放开 #3 单条路径。当前直接置字段的写法本身更干净（不会产生"无字段变更"的垃圾 CaseVersion 行），保留亦可，只需补齐语义对齐。

4. **spec §4.2 三处 UI 元素在计划阶段被静默裁剪，未列入实现者偏离申报**
   - `frontend/src/views/reviews/ReviewCenter.vue`（① :8-21、③ :40-60、④ :73-83）
   - 问题：spec ① "模块下拉（按 page_name 分组）" 未实现（只剩项目+评审状态筛选）；③ "关联测试点" 列未显示（`CaseResponse.point_name` 现成可用）；④ "逐条 [拒绝]" 未实现（只有 [确认]，且 `apply_suggestions(ids=None)` 会把 pending 全部置 applied，无 rejected 路径）。计划代码即如此，实现者照计划做——但偏离清单只报了 5 项，这三项遗漏未申报。
   - 怎么修：请 controller 确认这三项是"本期裁剪"还是"计划遗漏"。若是前者补 spec 备注；若要补齐，①模块下拉用 `point_name` 分组、③加一列、④需 #3 `apply_suggestions` 支持 rejected 状态（超出 #7 只读边界，建议移后续）。

5. **batch_update_review 畸形 id 静默 no-op，返回 `{success_count: 0, failure_count: 0}` 误导调用方**
   - `backend/app/services/review_service.py:117-120`
   - 问题：任一 id 非法 → 整批 `id_list=[]` → 查空 → 返回 0/0（连 failure_count 都不反映请求了 3 条）。且已提交的测试 `test_batch_review_updates_and_counts` 用 mock 直接返回 3 个 case、绕过 UUID 解析——**该测试在真实 DB 下会失败（期望 3 实际 0）**，即当前测试无法守住这段偏离后的语义。前端今天只发真实 UUID，实际触发率低，故列 Important 而非 Critical。
   - 怎么修：改为 schema 层校验（`case_ids: List[UUID]` 或 field_validator），畸形输入 422；或至少把未匹配数计入 `failure_count = len(case_ids) - success`。并补一条"含畸形 id"的服务测试锁死所选语义。

#### 次要（建议优化）

1. **project_id 非法 → 500 而非 4xx**：`backend/app/api/v1/reviews.py:21-23`（stats/refinement-report）及 :37（batch-review 的 `UUID(project_id)`）无 ValueError→400 处理，同文件 test_cases.py 全部有 `except ValueError → 400`。顺手对齐。
2. **batch_refine 的 project_id 是装饰性参数**（review_service.py:56）：收下但不用于过滤，`refine_case` 仅按 case_id 查——与 #3 单条 refine 一致（也无项目约束），但端点契约暗示了项目作用域。建议文档注明或加校验。
3. **feasibility NULL 被归入 "manual" 桶**（review_service.py:93）：未精修用例（feasibility_level=NULL）会被计成"需手工"，可行性分布条在未评估项目上显示 100% 需手工，语义混淆。建议单列 `unassessed` 桶或从分布中排除 NULL（可自动化率分子不受影响，仅展示语义）。
4. **用例表无分页**（ReviewCenter.vue:40）：`page_size=100` 封顶，>100 用例的项目静默截断且无提示（总用例统计卡会暴露不一致）。
5. **批量精修阻塞事件循环**：`refine_sync` 是同步 CPU 型调用，批量 N 条期间整个 event loop 停摆。spec §5.4 已声明"本期不优化"，仅提醒联调时留意大批量场景。
6. **前端筛选边缘**：detail 拉取失败的用例 `review_status` 为 undefined，会被"待评审"筛选排除（computed 对 undefined 不匹配 'pending'）——与 Important #1 一并解决。
7. **`SuggestionWithCase` 白名单静默丢弃未知字段**：CaseRefiner 未来给 suggestion 加字段时 API 响应会悄悄丢——可接受，留注释即可。
8. **onApplyAll 首败即中断**（ReviewCenter.vue:214-224）：顺序 apply，某 case 抛错则后续不执行、只有笼统"应用失败"，前面已 apply 的无法回退也无进度反馈。低频场景，可后续加逐条容错。

### 建议

1. 合并前做两件小事（合计 <30 行）：Important #1 的 CaseResponse 补字段 + Important #2 的 refined_at 列回退。两者都有现成数据、低风险、且分别消掉最大的运行时脆弱点和唯一的 spec 功能性缺口。
2. Important #3（finalized 语义）与 #4（三处 UI 裁剪）属"需 controller 拍板"项：前者写决策进 spec，后者确认是裁剪还是遗漏。
3. 测试补强方向（后续 task 即可，不阻塞）：畸形 case_ids 语义锁死（#5）、batch_refine "case not found" 分支、batch_update_review 跨项目过滤（现 mock 无法覆盖查询级约束——全 mock 约定的固有盲区，可留到集成测试阶段）。
4. 计划质量反馈：本计划两处测试 fixture 用了引擎不会产出的数据形状（report 内 `refined_at` 键、非 UUID 的 case_ids），导致实现者被迫偏离——写计划时测试数据应从真实引擎输出（`refine_sync` 实跑样本）反推。

### 评估

**可以合并吗？** 需修复

**理由：** 无 Critical，骨架、容错、复用边界、安全面都合格，偏离申报诚实；但 Important #1（NullPool 下 100 并发扇出）与 #2（spec 要求的精修时间戳恒空）都是小改动却直接影响上线体验与 spec 符合度，建议修完这两项再合，#3/#4 交 controller 确认后可随合并或转后续。