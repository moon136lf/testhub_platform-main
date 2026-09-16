# SESSION HANDOFF — 2026-09-15 晚 验证码识别 script_error 根因 + 修复方案（已定稿待实施）

> master 最新：e6004d5。本轮只做排查与方案，**未动代码**。

## 一、问题现象（用户实录 2026-09-15 17:36）

脚本「手工创建用例20260909163053-自动化脚本114759」执行 7 步，第 4 步
`captcha_recognize 图形验证码图片` 失败 **script_error**，其余 6 步通过。
用户反馈两点：
1. 失败截图已上传（fail_step4.png @ minio），但**直播里看不到具体失败原因**（只有 `❌ 失败（script_error）`，没有 error_msg）
2. SSE 直播里**看不到验证码识别结果**（识别出什么、对不对无从判断）

## 二、根因分析

### 根因1：失败详情不透出（日志黑盒）
`script_executor.py` SSE 消息只发 `error_type`（四分类），**error_msg 不进直播**——
`collect_failure()` 采集了 error_msg/stack_trace 存 last_failure，但从未 send 给前端。
`classify_error()` 里 RuntimeError → script_error，无法区分「定位失败 / OCR为空 / ddddocr未装」。

### 根因2：captcha_recognize 实现薄弱（对比用户已跑通的旧脚本）
平台现实现（dispatch_editor_action :144）：
- 直接 `page.locator(target).screenshot()`，**无 boundingBox 校验、无可见性检查、无兜底选择器**
- 失败重试 2 次但**不刷新验证码图**（同一张图重试没有意义）
- 识别结果不透出（连日志都没有，识别成什么都不知道）

用户旧平台（已验证跑通登录）的成熟做法（scripts/run-playwright.ts）：
- `get_captcha_image()`：xpath 优先 → boundingBox 宽高>20 校验（防裂图/隐藏节点）→
  6 个兜底选择器（img[src*=captcha]/kaptcha/code、.captcha img、.login-code img、form img）→ 最后整页
- `get_captcha_code()`：识别结果长度 ≥3 才有效；无效则**点验证码图刷新换一张**再试（最多 3 次）
- ocr 实例只初始化一次（非每次循环 new，避免模型重复加载首帧慢）

### 疑点（实施时先验证）
用户脚本第 4 步 target 是「图形验证码图片」——若元素库该元素的定位符失效/不唯一，
locator.screenshot() 会抛 TimeoutError（classify→script_error 之外的 locate_failed/timeout……
但实际报 script_error，说明是**非超时异常**：大概率 ddddocr 初始化或 screenshot 即时失败，
或 RuntimeError「OCR 识别结果为空」。**修复后日志透出即可见真相**）。

## 三、修复方案（已定稿，按序实施）

### 修1：captcha_recognize / input_captcha 重写（对齐旧平台成熟逻辑）
位置：`backend/app/services/script_executor.py` dispatch_editor_action 两个分支。
要点：
1. 模块级单例 `ocr = ddddocr.DdddOcr(show_ad=False)`（懒加载一次，非每次调用 new）
2. 抽公共函数 `_get_captcha_image(page, target, save_path) -> bool`：
   - target 定位失败 → 走兜底选择器组（img[src*="captcha"] 等同旧平台）
   - 元素 count()>0 + is_visible + boundingBox 宽高>20 才元素截图，否则继续兜底
3. 抽 `_get_captcha_code(page, target, max_retry=3) -> str`：
   - 每轮截图→识别；结果 `len>=3` 才返回
   - 无效 → **点击验证码图刷新换一张**（page.locator(图).click()，异常吞掉）→ wait 800ms → 下轮
   - 3 轮全空 → RuntimeError（带「已尝试刷新 N 次」信息）
4. captcha_recognize 分支：识别成功存 `page._script_vars["captcha_text"]`（保持现有引用机制不变）
5. **每次识别后 SSE 透出识别结果**：`content=f"验证码识别结果：{text}（第 {n} 次）"`——
   直播可见识别对错（用户明确要求）

### 修2：失败详情透出 SSE（不只是验证码步，所有步受益）
位置：execute() 两处 except（编辑器分支 + 元素库分支）。
- `❌ 失败（{error_type}）` 消息追加 error_msg 截断版：
  `content=f"第 {step} 步：❌ 失败（{error_type}）：{str(error)[:150]}"`
- 可选：type="error" 后再发一条 type="system" 的 detail（若前端错误气泡有长度限制，拆两条更稳——实施时看前端渲染方式定）

### 修3：测试
- `backend/tests/test_script_executor*.py` 补/改：
  - captcha 识别成功路径（mock ocr.classification 返回 4 位）
  - 空→刷新→重试路径（mock 前两次空第三次 4 位）
  - boundingBox 校验分支（mock 返回 None/小尺寸）
  - SSE 透出 error_msg 断言
- 回归：pytest backend 全绿

## 四、实施顺序与验证标准
1. 修1（验证码识别重写+SSE透出识别结果）→ 用户跑登录脚本，直播应显示「验证码识别结果：xxxx」
2. 修2（error_msg 透出）→ 任意失败步直播应显示具体原因（不再是裸 script_error）
3. 修3 测试补齐 → pytest 全绿
4. 用户验收点：①直播看得到识别值 ②失败看得到原因 ③登录脚本通过率提升（刷新换图生效）

## 五、环境备忘（沿用上轮）
- 后端 8000 无 --reload：改后端必须重启（Get-NetTCPConnection 查杀净）
- ddddocr==1.5.6 已在 requirements（无需新增依赖）
- 另一会话 anchor-axis worktree 已合并（af5fb2a），backend 2 个预存失败测试属其基线

## 六、待修复 bug 清单（上轮 16/17 + 本轮新增，均未实施）

| # | bug | 状态 |
|---|---|---|
| 8 | 脚本库操作列仍要滚动条才见全（方案：fixed right+260 已定） | 未实施 |
| 13a | 测试集 Tab 无翻页栏（方案已定） | 未实施 |
| 16 | 脚本库/测试集进来为空需手动刷新（onMounted 重构方案已定） | 未实施 |
| 17 | 测试集详情页 UI 不合规范（整页重做方案已定） | 未实施 |
| 新A | 验证码识别 script_error 无详情（本文档修1+修2） | 未实施 |
| 新B | SSE 不透出验证码识别结果（本文档修1） | 未实施 |
