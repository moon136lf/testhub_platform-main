# 点选补抓增强：DOM 路径面包屑 + 悬停高亮（方案1）设计

> 创建：2026-09-08
> 输入：用户确认方案 A（面包屑 + 同级切换，对标 F12 Elements 面板）
> 前置：会话式抓取工作台（bs_* 浏览器会话 + pick-element 端点 + staging）已全部就绪

---

## 1. 目标

点选补抓命中元素后，不只返回单个定位卡片，而是：
1. 显示该元素的**完整 DOM 路径面包屑**（每一级可点击）
2. 点击面包屑某一级 → 页面里**对应节点高亮闪烁**（注入 JS）+ 卡片切换为该节点
3. 卡片下方显示**当前节点的同级兄弟元素列表**，可点选切换目标（span → 父级 a 的场景）

## 2. 后端（2 个新端点，挂 /capture/browser/{sid} 下）

### 2.1 `POST /capture/browser/{sid}/node-info`
请求：`{x, y}`（与 pick-element 相同的截图坐标）+ 可选 `{offset: 层级偏移}` 或 `{anchor_marker: "data-pick-hit"}`

行为：
- 用 elementFromPoint 打标记（复用 `_PICK_MARKER_JS` 逻辑）
- 在被标记节点上执行 JS，返回**祖先链**（最多 8 层，每层含：tag、id、class 摘要、文本摘要、唯一性提示）
- 返回 `{chain: [{tag, id, class, text, index_in_parent}...], marker_active: true}`

标记保留（不立即清除），供高亮/切换用。会话结束或下次 pick 时清除。

### 2.2 `POST /capture/browser/{sid}/node-highlight`
请求：`{css_path: "html > body > div:nth-child(2) > ...", action: "flash"}`

行为：按 CSS 路径查询节点 → 注入 2 秒橙色闪烁样式（复用 P2 配色）→ 返回 `{found: bool}`。
路径校验：查询不到节点返回 `found: false`（页面已变化）。

### 2.3 复用与改动
- `_pick_element_via_dom` 保持不变（pick-element 端点继续用，产物仍入 staging）
- node-info 打标记逻辑与 `_PICK_MARKER_JS` 统一为一个常量
- **面包屑里每一级都附 css_path**（前端点击时传给 node-highlight）
- 元素定位卡片数据（pick-element 返回）**追加 `css_path` 字段**——前端从卡片即可发起面包屑

## 3. 前端（CaptureWorkbench 点选卡片增强）

### 3.1 面包屑组件（卡片内嵌）
```
[定位卡片]
  元素: span「采集字段配置」 button ▸ div.menu ▸ ul ▸ li:nth-child(3) ▸ a«采集字段配置»
  ────────────────────────────────
  同级元素 (5)：
    a«采集字段配置»  ← 当前
    a«采集规则配置»
    a«业务开关配置»
    ...
  [✅ 加入当前页（当前选中层级）] [忽略]
```
- 面包屑每级可点 → 调 node-highlight（页面里闪烁）+ 卡片切换为该层级的信息（含定位策略重新生成？）
  **决策：切换层级后定位策略需重新生成** —— 新端点 `POST /capture/browser/{sid}/node-locators`
  请求 `{css_path}` → 对该节点跑 generate/verify/extract 流水线 → 返回定位卡片数据
- 同级列表可点 → 同上（切换目标节点）

### 3.2 交互流
```
点截图 → pick-element（现状）→ 卡片显示 + 卡片顶部加载面包屑（node-info）
点面包屑某级 → node-highlight（页面闪烁确认）+ node-locators（重新生成策略）→ 卡片更新
点同级元素 → 同上
[加入当前页] → 当前选中的层级入 staging（沿用现有 add 逻辑）
```

## 4. 数据契约

```
node-info 响应: {chain: [{tag, id?, class?, text?, css_path, index_in_parent}], current_index}
node-highlight 请求: {css_path}; 响应: {found}
node-locators 请求: {css_path}; 响应: pick-element 同构 element dict
```

css_path 生成规则（后端 JS）：`html > body > div:nth-of-type(2) > ...` 每级含 nth-of-type（同 tag 兄弟 ≥2 时），与 generate_locators_for_element 策略7 的路径逻辑一致（可提取共用）。

## 5. 边界与注意

- 标记生命周期：node-info 打的标记在**下一次 pick/node-info/close** 时清除（会话级）
- CSS 路径查询失败（页面跳转/重渲染）→ node-highlight 返回 found:false，前端提示"页面已变化，请重新点选"
- 性能：chain 最多 8 层，一次 evaluate 完成，无性能问题
- iframe 不穿透（v1 明确不支持，spec 已有约定）
- **零 token**：全程 Playwright + JS，无 AI 调用

## 6. 测试

- 后端单测：node-info 链构造（mock page）、node-highlight 路径查询命中/未命中、node-locators 复用流水线
- 前端：vite build + 手动验收（真浏览器点选 → 面包屑 → 切层级 → 高亮 → 加入）

## 7. 验收

1. 点选元素 → 卡片出现完整面包屑
2. 点面包屑父级 → 页面里父节点闪烁 + 卡片切换为父级信息
3. 同级列表切换 → 同上
4. 加入当前页 → staging 中元素为当前选中层级
5. 页面跳转后点旧面包屑 → found:false 提示重新点选
