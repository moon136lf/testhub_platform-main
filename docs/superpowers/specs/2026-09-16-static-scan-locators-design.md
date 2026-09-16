# 源码定位器链路（静态扫描产出元素定位器）设计

- 日期：2026-09-16
- 状态：设计定稿（用户已确认），待写实施计划
- 背景：借鉴材料缺口3。当前元素定位器依赖浏览器抓取（会话式工作台/锚点轴定位），本设计让**不上浏览器**也能产出定位器——上传前端源码 zip，静态解析 .vue 模板，AI 生成定位策略链，以 `static_scan` 标记入元素库挂页面树。

## 一、总体链路

```
上传 zip (whitescan API)
  → 解压到临时目录（复用 CodeScan 的 tempfile 模式）
  → Celery 任务 code_scan.run_locator_scan 并行两支路：
      A) semgrep 扫描（现有逻辑，产出 CodeIssue，不变）
      B) .vue 元素提取（新 StaticScanService）：
         1. regex 提取 <template> 内可交互元素（input/button/select/textarea/a/el-*）
         2. 逐组件计算内容 hash（sha1 of 归一化 template 片段）
         3. hash 未变组件 → 跳过 AI，复用上次定位器（增量）
         4. hash 变化/新组件 → 模板片段喂 glm-5.2 生成 locator_strategies
  → 入库：source=static_scan 写 ElementRepository，挂 PageRepository 页面树
```

## 二、模块设计

### 2.1 API（backend/app/api/v1/whitescan.py 扩展）

- `POST /whitescan/locator-scan`：multipart zip 上传 + project_id。校验 zip（大小 ≤50MB、路径穿越防护：条目名不得含 `..` / 绝对路径）。写 CodeScan（repo_url=zip 文件名标记 `zip:<name>`，branch="zip"）+ 触发 Celery 任务，返回 scan_id。
- 复用现有 `GET /whitescan/scans/{id}` 轮询进度/状态（前端已有 pollTimer 模式，不做 SSE）。
- `GET /whitescan/scans/{scan_id}/static-elements`：本次静态扫描产出的元素列表（file_path/组件/定位器/复用与否）。

### 2.2 Celery 任务（backend/app/tasks/code_scan_tasks.py 新增）

`run_locator_scan_task(scan_id, project_id, zip_path)`：
- 阶段进度：10 解压 / 20 提取模板 / 30-70 AI 生成 / 80 入库 / 100 done
- A 支路（semgrep）与 B 支路（元素提取+AI）并行：`concurrent.futures.ThreadPoolExecutor` 两线程，B 失败不阻断 A（反之亦然），scan 状态取两者综合（双失败才 failed）
- finally 清理临时目录（含解压目录与上传暂存文件）

### 2.3 StaticScanService（新文件 backend/app/services/static_scan_service.py）

**提取**（纯 regex，零依赖，对齐 CodeStructureAnalyzer 风格）：
- 遍历 `*.vue`，截取 `<template>...</template>` 最外层块
- 按组件（.vue 文件）分组；每个可交互标签行提取：tag、v-model/name/placeholder/text(插值与静态)、:id、test-id 属性、disabled/v-if 上下文
- 产物：`[{file, component_name, template_snippet, hash, elements:[{tag, attrs...}]}]`

**AI 生成**（调 ai_gateway，provider key "glm-2.5"（历史遗留），实际模型 glm-5.2）：
- 输入：组件 template_snippet（截断 ≤4000 字符）+ 元素清单
- 输出：JSON 数组，每元素一条 locator_strategies（结构对齐现有链：`{"strategies":[{type,value,priority}]}`，可用类型含 css/xpath/id/placeholder/anchor/sibling-label/text/role——与 strategy_to_playwright 映射一致）
- JSON 围栏解析失败重试 1 次，仍失败该组件标记 ai_failed 不入库（不阻塞其他组件）
- 每组件一次调用（不是每元素），批量出整组件元素定位器，省 token

**hash 增量**：
- 新表 `static_scan_component`（见 2.4）。重扫时按 (project_id, file_path) 查旧 hash：相同 → 直接复制旧元素的 locator_strategies（标记 reused=true，不调 AI）；不同或新文件 → 调 AI
- 默认全量扫描；hash 复用只是省 AI，不省提取

**入库**：
- 页面树：每组件一个 PageRepository 节点（page_name=组件名，page_url=路由路径或文件相对路径，parent 按 src/views 目录层级建；路由表 CodeStructureAnalyzer.analyze_frontend 可用则取 title/path，取不到用文件路径）。同 project 下按 (page_name, created_by='static_scan') 幂等：已存在则复用页面节点
- 元素：source="static_scan"，confidence 默认 5；element_id 生成复用 ElementService._generate_element_id 规则的文件路径变体（file_path 短名+属性，无坐标后缀）；同 (page_id, element_id) 已存在则更新 locator_strategies（对齐 import_elements 的刷新语义）
- 同批去重 seen_element_ids 模式照抄 element_service（防 uq 约束整批回滚）

### 2.4 数据模型（backend/app/models/whitescan.py 扩展）

新表 `static_scan_component`：
```sql
id UUID PK, project_id UUID FK project, scan_id UUID FK code_scan,
file_path VARCHAR(500), component_name VARCHAR(200),
content_hash VARCHAR(64), page_id UUID FK page_repository NULL,
element_count INT, ai_generated BOOL, reused BOOL, ai_failed BOOL,
created_at, updated_at
UNIQUE(project_id, file_path)
```
- ElementRepository.source 值域扩展：现 comment "manual/auto/healed/ai_fixed" → 增加 "static_scan"（String(20) 够长，不改列型；仅改 comment，无需迁移）

### 2.5 前端（frontend/src/views/whitescan/WhiteScan.vue 扩展）

- 扫描表单加双模式：Git 仓库 / **源码 zip 上传**（el-upload，accept=.zip，≤50MB 前端校验）
- 扫描详情区加 Tab「元素定位器」：本次静态扫描产出列表（组件/文件/元素名/定位器预览/来源 AI|复用/失败标记），复用现有轮询，scan done 后拉取
- 定位器预览点击展开完整 strategies 数组

## 三、与需求偏差

| 项 | 需求/现状 | 本设计 | 理由 |
|---|---|---|---|
| element_repository DDL | §8.2.3 无 source 列 | 已有实现列（manual/auto/healed/ai_fixed），新增 static_scan 值 | 沿用实现演进，仅扩值域 |
| page_url NOT NULL | §8.2 DDL | 静态扫描页面用路由路径/文件路径填充，不置空 | 避免迁移改约束 |
| 仓库 URL 方式 | 原设计含 zip/仓库URL | 本期仅 zip 上传 | git clone 凭证管理 YAGNI，URL 下期 |
| 自愈侧（定位失败→DOM 喂 glm） | 缺口3 后半 | 不做，记 ROADMAP | 范围控制 |

## 四、不做项（YAGNI）

- 仓库 URL 拉取（下期）
- 静态定位器的浏览器真实验证（无坐标，confidence 不参与 verify 扣分调整——走现有 verify 逻辑观察效果再说）
- .tsx/.jsx/React 支持（一期 Vue）
- SSE 进度（复用轮询）

## 五、验收标准

1. 上传 MoonTest 自己前端 zip（35 个 .vue 试验田）→ 扫描完成，元素定位器 Tab 展示产出
2. 产出元素 source=static_scan 入元素库，挂页面树（组件名/路径层级），元素管理页可见可筛
3. 同一 zip 重传：hash 未变组件不调 AI（日志/标记 reused=true，耗时显著下降），定位器复用
4. 改一个 .vue 后重传：仅该组件重新生成，其余复用
5. zip 路径穿越（恶意条目名）被拒；非 zip 文件被拒；>50MB 被拒
6. semgrep 与元素提取互不阻断：AI 全挂时 semgrep 结果仍正常入库
7. 全量测试不回退（918 基线）+ 前端 build 通过
