# 会话存档 2026-09-11（晚）— 元素绑定V1合并后用户验收：转换链路四大根因

> 状态：元素绑定方案 V1 已合并 master（8c32ed4，19 commits，871 passed）。用户真浏览器验收发现转换产物与用例严重不对应。**根因已全部查明，未修复**。本存档供下次会话直接按方案实施。

## 用户验收发现（截图对比：登录用例 7 步 vs 转换产物）

1. 步骤1"输入+浏览器地址栏+URL"→ 产物元素是"用户名"（应为 navigate 或浏览器地址栏）
2. 步骤2"账号输入框+test02"→ 产物元素"密码"、值空（整体错位）
3. 测试数据（test02/Admin@17866/123456）大部分没带过来
4. 预期结果大部分没转成期望值
5. 编辑脚本元素列全是"待选择"+泛化定位（button/textbox）
6. 点"待选择"弹元素选择器 → 弹窗空白
7. SSE 直播仍只有 4 条粗粒度消息（"匹配元素库: 0/7 命中"），没有逐步骤明细
8. 生成的**脚本代码**反而基本按用例（用户贴的代码有 test02/欢迎登陆断言）——因为代码=step_mapping(坏)+断言计划(好)的混合产物

## 四大根因（已逐条实证复现）

### RC1（最严重）：step1 prompt 只给 LLM 看了动作词，目标/数据/预期全丢
`backend/app/services/script_pipeline.py:55-56`：
```python
def _fmt_steps(steps):
    return "\n".join(f"{s.get('step')}. {s.get('action','')}" for s in steps)
```
LLM 只看到"1. 输入\n2. 输入..."，用例步骤的 target（浏览器地址栏/账号输入框）、data（test02）、expected（显示test02）**全部没进 prompt**。LLM 全靠编，所以产物目标错位、数据空、预期空。
- 自 2026-08-24 原始 #4 模块（c84846d）就存在，**非本次重构引入**；本次 V1 改的是 step2/3（断言/匹配），step1 的输入侧没动——盲区。
- 修复：_fmt_steps 输出完整行 `N. {action} 目标[{target}] 数据[{data}] 预期[{expected}]`；STEP1_PROMPT 补映射规则（输入X到Y→fill target=Y value=X；目标含"地址栏/URL"→navigate value=URL）。

### RC2：评分规则语义鸿沟 + tag 字段取错列，全落 low
实测复现（真实 DB，DM 项目）：
```
账号输入框 vs 请输入账号: bigram=0.333, contain=False → score=0.133 low
密码输入框 vs 请输入密码: 同上 0.133 low
登录按钮 vs 登录: 0.433 low（tag 缺失丢 0.2 类型分）
获取验证码按钮 vs 获取验证码: 0.567 low
```
两个叠加缺陷（`element_service.py` find_candidates:262 / score_element）：
- **tag 恒空**：`getattr(e, "tag_name", "")` —— ElementRepository 根本没有 tag_name 列，实际叫 **element_type**（'input'/'button'）。类型加分 0.2 全丢。
- **stem 规则缺失**：用例目标"账号输入框"（控件角色词）vs 元素名"请输入账号"（placeholder 文本），bigram 只有 0.333、互相不包含。需加"去控件类型词后比对"：账号输入框→账号 ⊂ 请输入账号 ✅。已验证 5 对（账号/密码/验证码/登录/获取验证码）加 stem 规则后全部可达 0.66-0.77，配合类型分（element_type 修复）均 ≥0.86 → L2 命中。
- 修复：①`elem_dict["tag"] = getattr(e, "element_type", "") or ""`；②score_element 加 stem 规则（CONTROL_WORDS=['输入框','按钮','下拉框','链接','文本域']，剥离后互相包含 → contain=1.0 且 alias_sim 至少给 0.5 基础分）；③stem 精确相等（登录按钮 vs 登录剥离后相等）给高分。

### RC3：浏览器地址栏无固定选项
用例步骤1 target="浏览器地址栏"。前端 StepEditor 有"打开页面(navigate)"操作但转换链路没有"浏览器地址栏→navigate"确定性映射（step1 全靠 LLM，而 LLM 看不到 target——RC1）。修复随 RC1：prompt 映射规则 + 后处理（action=fill 且 target 含地址栏/URL 且 value 是 http → 强制改 navigate）。

### RC4：元素选择器弹窗空白（待明天复测）
后端已验证正常：8000 端口 backend 17:14 重启（新代码已加载），curl 实测 picker 返回 2 页面 12 元素：
```
GET /api/v1/elements/picker?project_id=3ff3ea1e... → {code:0, data:{pages:[登录页7元素, 欢迎页5元素]}}
```
前端 ElementPickerDialog 取数路径 `resp.data?.data?.pages` 正确，ScriptConvert/AutoUITest 均传了 :project-id。
**疑点**：vite dev server 10:02 启动（早于 16:45 merge）——HMR 对新增组件文件可能不完整，用户浏览器或需强刷；或用户点弹窗的入口页不是这两个页面。明天：重启 vite → 强刷浏览器 → 复测；若仍空白，检查 axios 实例（ElementPickerDialog 用的 `@/api/axios` 是否带 token/代理）。

## 用户新增需求（本轮明确，次日一并实施）

1. **编辑脚本列名对齐用例**：元素列头改"元素（用例目标）"、值列改"值（用例测试数据）"、期望列改"期望值（用例预期结果）"，让用户一眼看清对应关系。
2. **识别验证码拆两步**（推翻"合一步"设计，用户决策）：
   - 步骤A：识别验证码，元素=验证码图片
   - 步骤B：输入，元素=验证码输入框，值=识别结果（运行时传递）
   - 涉及：STEP1_PROMPT 映射规则（不再合并 input_captcha）、ActionIntent 拆分、step_codegen 的 input_captcha 分支改两步语义、executor 对应调整。**注意**：保留 input_captcha 动作兼容旧数据，新转换产出两步。
3. **元素选择器弹窗重设计**：左侧页面树（所属页面层级），右侧该页元素表格：元素名/定位策略列表/详细定位值/置信度。替代现在的 collapse+单表格。

## 明日开工顺序

1. RC1 修复（_fmt_steps+prompt+后处理）——最高优先，一条改三条（目标/数据/预期全链路）
2. RC2 修复（element_type 列名 + stem 规则）——转换命中率 0/7 → 预期 6/7
3. RC4 复测（重启 vite+强刷；仍空白再查 axios）
4. 用户新需求 1-3（列名标注/验证码拆两步/选择器重设计）
5. SSE 直播逐步明细复测（后端 step_binding 已实现，前端可能未刷新）
6. 重新走登录用例 7 步转换验收（对照 spec 第七节）

## 环境备忘
- 后端 8000（uvicorn --reload，17:14 已重启含新代码）；前端 3000（vite，10:02 启动——**偏旧，需重启**）
- master 8c32ed4；测试基线 871 passed
- DM 项目 project_id=3ff3ea1e-7c4c-4ee5-afcd-c52ae34e074b（登录页 7 元素可直接复现）
