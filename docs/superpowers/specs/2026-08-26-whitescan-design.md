# 白盒代码体检（#9）设计 — semgrep 扫描 + AI修复 + 回归用例生成

**版本**：v1.0
**日期**：2026-08-26
**作者**：Claude Code (Opus 4.8)
**状态**：待审批（依赖 #2/#3/#5a，#9 可在新 worktree 实施）
**流程**：Superpowers（brainstorming → writing-plans → TDD → 编码 → verification）
**范围依据**：需求 §5.1 白盒代码体检

---

## 1. 概述

#9「白盒代码体检」——用 semgrep 扫描代码仓库，规则库检测安全问题，AI 生成修复建议，**一键产出回归用例**（强制自动化形式，复用 #2 StepSchema），产出物下载。打通 #9→#8：白盒产出的回归用例进 test_case 表，#8 选回归集批量执行。

### 1.1 依赖

- **#2**：StepSchema（{step,action,target,data,expected}）+ 禁用词规则 + test_case_generator prompt 框架（回归用例生成器复用）
- **#3**：TestCase model + 版本历史（force 覆盖 version+1）+ CaseRefiner 断言校验
- **#5a**：Celery worker（扫描异步任务）
- **#8**：生成回归用例进 test_case 表，#8 消费

### 1.2 已确认决策

- **扫描引擎**：semgrep（跨语言规则库，覆盖 WHITE-01/02）
- **semgrep 环境**：**方案 A**——开发期全 mock（Windows 装不上，已验证 pip 卡住），Linux 部署时真实生效
- **回归用例**：白盒扫描产出回归用例（WHITE-05「流程测试用例.md」本就含此），存平台 TestCase，强制自动化形式
- **生成方式**：复用 #2 prompt 框架，输入从 PRD 换成 code_issue + 代码变更上下文
- **增量生成**：一键生成只生成新 issue（已有 source_issue_id 跳过），代码变更的 issue 标 case_outdated 待手动重新生成
- **异步**：Celery 扫描 + AI 修复建议异步子任务
- **worktree**：#9 新 worktree `module9-whitescan`，基于含 #5a 的 master

### 1.3 不做（YAGNI）

- 自写 AST 规则引擎（用 semgrep）
- 回归用例自动覆盖（手动 force，避免误删用户改过的用例）
- 视觉回归（UI 用例示例中的像素对比，留 P1）
- 部署在 Windows（Linux 部署）

---

## 2. 数据层

### 2.1 新建 2 表

| 表 | 关键字段 |
|---|---|
| `code_scan` | id/project_id/repo_url/branch/status(scanning/done/failed)/total_issues/high_count/mid_count/low_count/file_count/duration_ms/created_at |
| `code_issue` | id/scan_id(FK CASCADE)/severity(high/mid/low)/file_path/line_no/title/description/ai_suggestion(JSONB:修复建议+示例代码)/example_code(Text)/status(open/fixed/false_positive)/source_commit(关联变更点)/fingerprint(String:rule_id+位置+代码hash)/case_outdated(Boolean,default false)/handled_by/handled_at |

### 2.2 TestCase 关联（复用 #3 表，加 1 字段）

- `test_case.source_issue_id`（UUID, nullable, FK code_issue SET NULL）—— 标记该用例由哪个白盒问题生成
- 最小改动，区分白盒来源；不加 source 字段（用 source_issue_id 是否为空区分）

### 2.3 加密

无敏感字段（repo_url 公开，issue 明文）。不加密。

### 2.4 迁移 `add_whitescan_tables.sql`（idempotent）

2 表 CREATE IF NOT EXISTS + 索引 + test_case 加 source_issue_id 列（ALTER ADD COLUMN IF NOT EXISTS）。

---

## 3. 服务层

### 3.1 新建 4 service + 1 Celery task

| 文件 | 职责 |
|---|---|
| services/code_scan_service.py | 触发扫描（Celery异步）、查询扫描记录/issue列表、issue状态流转、误报忽略指纹跳过（WHITE-04） |
| services/ai_fix_service.py | 对issue调ai_gateway生成修复建议+示例代码，写ai_suggestion JSONB |
| services/regression_case_generator.py | 回归用例生成：复用#2 prompt框架，输入issue+修复建议+代码上下文，输出平台TestCase（强制自动化形式） |
| services/scan_export_service.py | 产出物导出：BUG清单.xlsx/API契约矩阵.md/功能点清单.md/流程测试用例.md/用例汇总统计.md |
| tasks/code_scan_tasks.py | Celery: git clone→semgrep→写issue→统计→（可选）AI修复子任务 |

### 3.2 semgrep 调用（方案 A：mock 开发，Linux 真跑）

```python
# code_scan_service.py
def _run_semgrep(repo_path: str) -> dict:
    """调 semgrep 扫描。开发期 mock，Linux 部署真实 subprocess。"""
    result = subprocess.run(
        ["semgrep", "scan", "--config", "auto", "--json", repo_path],
        capture_output=True, text=True, timeout=300
    )
    return json.loads(result.stdout)
```
- 测试 `@patch('subprocess.run')` 返回固定 JSON
- Linux 部署 pip 装 semgrep，真实生效，无需改代码

### 3.3 回归用例生成器（核心，融入用户规范）

`regression_case_generator.py`：

**提示词模板**（角色+输入+分析步骤+输出）：
```
你是一位资深的测试架构师。请基于以下【代码问题(code_issue)】+【AI修复建议】+【代码变更上下文】，
生成回归测试用例。

分析要求：
1. 基于代码依赖（精准打击）：优先为被修改函数/类的直接调用方和下游依赖生成
2. 兼顾新旧路径：验证老功能未被改坏（防退化），非仅验证新功能
3. 数据隔离与幂等性：使用唯一标识(UUID)或临时账户，并发不冲突
4. 断言精细化：拒绝模糊断言（"页面正常"），必须校验具体业务状态码/数据结构/元素属性
5. 异常与容错覆盖：除主流程，根据 try-catch/降级/超时生成异常注入用例

输出 JSON（平台 TestCase 格式，强制自动化形式）：
{
  "name": "REG-XXX_验证意图",
  "priority": "P0|P1|P2",
  "precondition": "前置条件",
  "steps": [
    {"step":1, "action":"navigate|click|input|select|check|assert|wait",
     "target":"目标元素", "data":"测试数据", "expected":"可断言预期(URL/文本/状态)"}
  ],
  "expected_result": "最终可断言预期",
  "source_issue_id": "关联的code_issue.id"
}

禁用词：action/expected 不得含 观察/查看/验证/检查/确认（软断言词）
```

**用例列规范**（7 字段对齐 TestCase）：
- 用例编号/名称 → test_case.name（REG-前缀）
- 优先级 → test_case.priority
- 关联变更点 → source_issue_id
- 前置条件 → precondition
- 测试步骤 → steps（JSONB，复用 #2 StepSchema）
- 预期断言 → steps[].expected + expected_result
- 数据清理 → precondition 或 steps 末步

**生成规则5条**：基于代码依赖/兼顾新旧路径/数据隔离幂等/断言精细化/异常容错覆盖（写进 prompt + validator）

**强制自动化形式**：复用 #2 StepSchema + 禁用词规则，生成用例直接进 #4 转脚本 + #5 执行 + #8 回归集

### 3.4 增量生成策略

`generate_cases(scan_id)`：
1. 遍历 scan 下所有 issue
2. 查 test_case 是否已有 `source_issue_id == issue.id`
3. 已有 → 跳过（不重复生成）
4. 没有 → 调生成器生成，写 test_case + source_issue_id 关联
5. issue.case_outdated=true 的 → 前端提示"待更新"，用户手动 [重新生成] force 覆盖（version+1，复用 #3 版本历史）

**指纹变更检测**：每次新扫描，对 issue 算 fingerprint（rule_id+file_path+line_no+代码hash）。若 issue 已存在且指纹变了 → case_outdated=true。

### 3.5 WHITE-04 误报忽略

issue 标 false_positive 后，记录规则指纹，同规则同场景下次扫描跳过告警。存 code_issue.fingerprint，扫描时查已忽略指纹列表跳过。

---

## 4. API（router `whitescan.py`，prefix /whitescan）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /whitescan/scan | 触发扫描（body: project_id+repo_url+branch），异步 Celery，返回 scan_id |
| GET | /whitescan/scans?project_id=&page= | 扫描记录列表 |
| GET | /whitescan/scans/{scan_id} | 扫描概览（统计+issue概要） |
| GET | /whitescan/scans/{scan_id}/issues?severity=&status= | issue列表（筛选） |
| PATCH | /whitescan/issues/{issue_id} | issue状态流转（fixed/false_positive） |
| POST | /whitescan/issues/{issue_id}/ai-fix | 单条生成AI修复建议 |
| POST | /whitescan/scans/{scan_id}/generate-cases | 一键生成回归用例（增量） |
| POST | /whitescan/issues/{issue_id}/generate-case?force=false | 单issue生成/重新生成用例 |
| GET | /whitescan/scans/{scan_id}/export?format=xlsx\|md | 产出物下载 |

---

## 5. 前端

### 5.1 新建

| 文件 | 内容 |
|---|---|
| views/whitescan/WhiteScan.vue | 白盒体检页（整合 §5.1.2，4块） |
| api/whitescan.js | 封装 /whitescan/* |

### 5.2 WhiteScan.vue 结构（对齐 §5.1.2）

**① 扫描入口**：项目下拉 + 仓库URL + 分支 + [开始扫描]（异步，轮询状态每3s）
**② 扫描概览卡**：总问题/高危/中危/低危 + 文件数 + 耗时（4数字卡红橙黄灰）
**③ 问题列表**：等级tag/文件路径/行号/问题描述/状态/操作[AI修复][生成用例][标记已修复][标记误报]，筛选等级+状态
**④ AI修复弹窗+产出物**：弹窗显示ai_suggestion（问题+建议+示例代码修改前/后diff+[复制代码]）；底部[下载BUG清单][下载API契约矩阵][下载功能点清单]

### 5.3 路由+菜单

- router 加 /whitescan → WhiteScan
- MainLayout「质量与报告」子菜单「白盒代码体检」改指 /whitescan（修复死链）

### 5.4 交互

- 一键生成回归用例：`POST /whitescan/scans/{id}/generate-cases`，loading后提示生成N条
- case_outdated 标记：问题列表显示"用例待更新"标记，单条[重新生成]覆盖

---

## 6. 测试 + 边界 + 风险

### 6.1 测试（延续 mock）

| 文件 | 覆盖 |
|---|---|
| test_code_scan_service.py | 扫描记录查询、issue列表筛选、状态流转、误报忽略指纹跳过 |
| test_ai_fix_service.py | AI修复建议生成（mock ai_gateway）、写ai_suggestion |
| test_regression_case_generator.py | 生成用例强制自动化形式（steps+禁用词）、增量生成查重、case_outdated标记、force覆盖 |
| test_scan_export_service.py | 产出物导出（xlsx/md非空，mock openpyxl） |
| test_api_whitescan.py | 9端点契约 |

### 6.2 与其他模块边界

- **复用 #2**：StepSchema + 禁用词 + prompt 框架
- **复用 #3**：TestCase + source_issue_id + 版本历史
- **复用 #5**：Celery worker
- **复用 #8**：生成用例进 test_case，#8 消费
- **不改**：case_refiner.py、test_case_service.py 核心、#4 script_*

**共享文件**：
- `models/test_case.py`（加 source_issue_id）—— **与 #4 撞风险**，需协调（#9 在 #4 完成后基于最新 master 开）
- `api/__init__.py`（注册 whitescan router，追加）
- `requirements.txt`（加 semgrep，标注 Linux 装）

### 6.3 worktree 策略

- #9 依赖 #2/#3(master) + #5a(Celery)
- 新 worktree `module9-whitescan`，基于含 #5a 的 master
- 前置：#5a 完成；#4 完成或协调 test_case.py

### 6.4 风险

- **semgrep Windows**：开发期 mock（方案A，已验证 pip 卡住），Linux 部署 pip 装顺
- **AI 修复 token 消耗**：每 issue 一次 AI 调用，复用 #10 token 配额预警
- **git clone 安全**：限制内网/可信仓库，联调验证

### 6.5 诚实边界

- 全 mock，无真实 DB / 无真实 semgrep / 无真实 LLM
- semgrep 真实扫描 + git clone + AI 修复真实链路留 Linux 联调
- 误报忽略指纹机制 mock 测试，真实效果联调验证

---

## Self-Review 记录（2026-08-26）

| 项 | 结果 |
|---|---|
| 占位符扫描 | 无 TBD/TODO |
| 内部一致性 | semgrep方案A、回归用例复用#2框架、增量生成+case_outdated、/whitescan前缀——全文一致 |
| 范围检查 | 扫描+AI修复+回归用例+导出，单spec可承载，约2-2.5天 |
| 歧义检查 | 已澄清：不写AST用semgrep、不自动覆盖用force、Windows不装走mock |
| 依赖前置 | #2/#3在master，#5a Celery待完成，#4 test_case.py需协调 |

确认后转入 writing-plans 生成实施计划（等 #5a 完成 + #4 协调 test_case.py 后实施）。
