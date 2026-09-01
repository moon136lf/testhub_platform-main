# 功能回归用例生成（白盒模块增强）设计

> 创建：2026-09-01
> 流程：brainstorm → spec → writing-plans → TDD → 实现
> 背景：用户不需要"按安全问题生成回归用例"（现有 regression_case_generator），需要的是**读取被测系统前后端代码，生成每个菜单的功能回归用例 + 基础功能/增删改查用例**。用户确认：只替换"生成回归用例"逻辑，Semgrep 安全扫描/问题列表/AI修复保留不动。

---

## 1. 目标与边界

### 1.1 做

替换白盒页「生成回归用例」按钮的逻辑：

```
现有: scan 的安全问题 → AI 逐条生成"修复XX"用例 (删除)
新增: clone 的仓库代码 → 静态解析 → 前端菜单树 + 后端 API 清单
      → AI 生成功能回归用例 (菜单级 + API级) → 落 test_case 表
```

### 1.2 不做

- Semgrep 扫描/问题列表/AI修复/误报标记：**全部保留不动**
- 非 Vue Router + FastAPI 技术栈的解析器：未来按需加
- 用例自动执行：落库到用例管理页后人工/既有执行链路使用

## 2. 数据流

```
POST /whitescan/scans/{scan_id}/generate-cases (现有端点, 逻辑替换)
  → Celery task (后台跑, 不打爆网关)
  → 1. clone 仓库 (复用现有 clone 逻辑; 若 scan 已 clone 过目录还在则复用)
  → 2. 静态解析:
       前端: 找 */router/index.js → 正则抽 [{path, name, meta:{title}}]
       后端: 找 */api/v1/*.py (或 */api/*.py) → 正则抽
             @router.(get|post|put|delete|patch)("path") + 函数名 + docstring
  → 3. AI 生成 (glm-5.2, 批量模式):
       菜单级: 每菜单 1 次调用, 生成 2-3 条功能用例 (页面可访问+核心操作)
       API 级: 每 5-10 个 API 1 次批量调用, 生成 CRUD 用例
  → 4. 落库 test_case:
       project_id = scan.project_id
       name = "[回归][菜单名] 用例标题" / "[回归][API] METHOD path"
       case_type = 'regression'
       steps = [{step, action, expected}...] (JSONB)
       source_issue_id = None (功能用例不挂安全问题)
       point_id = None
  → 5. 返回 {generated_count, failed_count, menus_found, apis_found}
```

## 3. 模块设计

### 3.1 新建 `backend/app/services/code_structure_analyzer.py`

纯静态解析，零 AI、零 DB，可独立单测：

```python
class CodeStructureAnalyzer:
    """被测系统前后端代码结构静态解析 (Vue Router + FastAPI)."""

    def analyze_frontend(self, repo_path: str) -> list[dict]:
        """找 router/index.js (glob **/router/index.js, 排除 node_modules),
        正则抽 route 定义: path/name/component/meta.title. 返回菜单树列表."""
        # 匹配: { path: 'xxx', name: 'Xxx', ..., meta: { title: '中文' } }
        # 多行 route 对象用 DOTALL 正则, title 缺省用 name

    def analyze_backend(self, repo_path: str) -> list[dict]:
        """找 api 目录下的 *.py, 抽 @router.(method)("path") + 紧随的函数定义
        + docstring 首行. 返回 [{file, method, path, func, desc}]."""
        # router prefix 从 APIRouter(prefix=...) 或文件聚合推断
```

### 3.2 新建 `backend/app/services/functional_case_generator.py`

```python
class FunctionalCaseGenerator:
    """基于代码结构生成功能回归用例 (AI 批量, 替换原 regression_case_generator)."""

    def __init__(self, db, gateway):
        ...

    async def generate_from_repo(self, project_id, repo_path) -> dict:
        menus = analyzer.analyze_frontend(repo_path)
        apis = analyzer.analyze_backend(repo_path)
        # 批量生成 (串行, 每批 sleep 1s 避免打爆网关):
        # 菜单批: 每批 3 个菜单一次调用
        # API 批: 每批 8 个 API 一次调用
        # AI prompt 要求返回 JSON 数组: [{title, precondition, steps:[{action,expected}], priority}]
        # 解析失败/网关 503 → 该批记 failed, 继续下一批 (不中断)
        # 落库 test_case (去重: 同 title 已存在则跳过)
        return {"generated": n, "failed": m, "menus": len(menus), "apis": len(apis)}
```

### 3.3 替换点

- `whitescan.py` 的 `generate_cases` 端点：调用 `FunctionalCaseGenerator.generate_from_repo`（原来是 RegressionCaseGenerator.batch_generate）
- Celery task `code_scan_tasks.py` 加 `generate_functional_cases_task`（生成较慢，走后台；端点返回 task_id + 立即 202，前端轮询 scan 状态或简化为同步等待——**v1 用同步**，批次少时几分钟内完成，前端按钮 loading）
- 旧 `regression_case_generator.py` **文件保留不删**（不 import 即死代码，后续清理），前端按钮文案改「生成功能回归用例」

### 3.4 test_case 落库字段映射

| 字段 | 值 |
|---|---|
| project_id | scan.project_id |
| name | `[回归] {菜单title} - {用例标题}` / `[回归][API] {METHOD} {path}` |
| priority | 菜单级 P1 / API 级 P2 |
| case_type | regression |
| steps | JSONB `[{step, action, expected}]` |
| precondition | AI 生成或"已登录系统" |
| is_finalized | False（进用例管理页人工确认后定稿） |

## 4. 测试策略

- analyzer 单测（纯函数，fixture 小型 router 文件 + api 文件）
- generator 单测（mock gateway + mock db，验证批量/失败继续/去重）
- e2e：对 MoonTest 自身仓库跑一次，验证产出条数 > 100
- 前端不改按钮逻辑，只改文案

## 5. 验收

1. 白盒页对一个含 Vue Router + FastAPI 的仓库点「生成回归用例」→ test_case 表新增 100+ 条功能用例
2. 用例管理页可见、可编辑
3. Semgrep 扫描/问题列表/AI修复不受影响
4. 网关 503 时单批失败不中断整体
