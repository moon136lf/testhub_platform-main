# 用例管理模块 - 设计规格

**版本**: v1.0  
**日期**: 2026-08-18  
**作者**: Claude Code (Opus 4.8)  
**状态**: 待审批

---

## 1. 概述

### 1.1 目标

实现 MoonTest 平台的用例管理模块，支持 AI 生成后的用例精修和日常用例库管理。用户可以查看、编辑、筛选、批量操作测试用例，完成从 AI 生成到人工定稿的完整流程。

### 1.2 核心能力

- 📋 用例列表展示（分页、排序、筛选）
- ✏️ 用例 CRUD 操作（创建、查看、编辑、删除）
- 🔄 简单状态流转（草稿 ↔ 已定稿）
- 🔍 多维度筛选（状态、优先级、幻觉标记、测试点、时间范围）
- ⚡ 批量操作（定稿、删除、设置优先级、设置幻觉状态）
- 🔗 测试点弱关联（支持手工创建的独立用例）
- 📊 基础统计展示（总数、各状态数量）

### 1.3 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy (Async)
- **前端**: Vue3 (Composition API) + TypeScript + Element Plus
- **数据库**: PostgreSQL
- **API 风格**: RESTful

---

## 2. 需求澄清结果

基于与用户的需求澄清，确定以下设计决策：

| 需求维度 | 选择方案 | 理由 |
|---------|---------|------|
| 核心场景 | 两者都需要（AI 精修 + 日常管理） | 既支持 AI 生成后精修，也支持传统手工管理 |
| 状态流转 | 简单二态模型（草稿/已定稿） | 快速迭代，避免复杂审批流 |
| 批量操作 | 基础 + 状态管理 | 覆盖幻觉标记、优先级等核心场景 |
| 用例编辑 | 表格式编辑器 | 高效编辑 AI 生成的规整步骤 |
| 测试点关联 | 弱关联模式 | 支持手工创建的独立用例 |
| 搜索筛选 | 基础 + AI 相关 | 支持幻觉状态、测试点、时间范围筛选 |

---

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────┐
│        前端 (Vue3 + Element Plus)    │
│  ┌─────────────────────────────────┐│
│  │  CaseList.vue (用例列表页)      ││
│  │  - 表格展示 + 分页               ││
│  │  - 筛选器组件                   ││
│  │  - 批量操作工具栏               ││
│  └─────────────────────────────────┘│
│  ┌─────────────────────────────────┐│
│  │  CaseDetail.vue (详情/编辑页)   ││
│  │  - 基本信息表单                 ││
│  │  - 步骤编辑器(表格)             ││
│  │  - 状态操作按钮                 ││
│  └─────────────────────────────────┘│
└───────────────┬─────────────────────┘
                │ HTTP/REST API
┌───────────────▼─────────────────────┐
│        后端 (FastAPI)                │
│  ┌─────────────────────────────────┐│
│  │  /api/v1/test-cases/            ││
│  │  - GET    /          (列表)     ││
│  │  - GET    /{id}      (详情)     ││
│  │  - POST   /          (创建)     ││
│  │  - PUT    /{id}      (更新)     ││
│  │  - DELETE /{id}      (删除)     ││
│  │  - POST   /batch     (批量操作) ││
│  │  - GET    /stats     (统计)     ││
│  └─────────────────────────────────┘│
│  ┌─────────────────────────────────┐│
│  │  TestCaseService                 ││
│  │  - 业务逻辑封装                  ││
│  │  - 搜索筛选逻辑                  ││
│  │  - 批量操作事务                  ││
│  └─────────────────────────────────┘│
└───────────────┬─────────────────────┘
                │
┌───────────────▼─────────────────────┐
│     PostgreSQL (test_case 表)       │
└─────────────────────────────────────┘
```

### 3.2 设计方案

**选择方案：单体式设计（推荐）**

**架构思路：**
- 前端：一个主列表页 + 一个详情编辑页
- 后端：复用现有 `test_case` 表 + CRUD API + 批量操作 API
- 状态流转：前端直接调用状态更新 API
- 搜索筛选：后端通过 SQLAlchemy 查询构建器动态拼接条件

**优点：**
- 简单直接，开发快（约2-3天）
- 易于理解和维护
- 符合当前项目的技术栈风格

**放弃的方案：**
- 状态机模式：对于简单二态流转属于过度设计
- 微服务拆分：当前项目规模不需要

---

## 4. 数据模型设计

### 4.1 复用现有 TestCase 表

现有 `test_case` 表字段已满足需求，**无需修改表结构**：

```python
class TestCase(Base):
    __tablename__ = "test_case"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id"), nullable=False)
    point_id = Column(UUID(as_uuid=True), ForeignKey("test_point.id"), nullable=True)
    
    # 基本信息
    name = Column(String(100), nullable=False)
    priority = Column(String(2), nullable=False, default="P1")  # P0/P1/P2/P3
    case_type = Column(String(20), nullable=False, default="functional")
    precondition = Column(Text)
    expected_result = Column(String(200), nullable=False)
    
    # 测试步骤（JSON）
    steps = Column(JSON, nullable=False)
    
    # 状态字段
    is_finalized = Column(Boolean, default=False)  # 草稿/已定稿
    automation_status = Column(String(20), default="pending")
    hallucination_status = Column(String(20), default="normal")
    
    # 版本和审计
    version = Column(Integer, default=1)
    created_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, default=False)
```

### 4.2 Steps 字段 JSON 结构

```json
[
  {
    "seq": 1,
    "action": "打开",
    "target": "登录页",
    "data": "https://example.com/login",
    "expected": "页面正常加载"
  },
  {
    "seq": 2,
    "action": "输入",
    "target": "用户名输入框",
    "data": "admin",
    "expected": "输入成功"
  }
]
```

**字段说明：**
- `seq`: 步骤序号
- `action`: 操作类型（打开/点击/输入/选择等）
- `target`: 目标元素
- `data`: 测试数据（可选）
- `expected`: 预期结果（可选）

### 4.3 优先级枚举

```python
P0 = "阻塞级"  # 核心功能，必须通过
P1 = "严重级"  # 重要功能
P2 = "重要级"  # 常规功能
P3 = "一般级"  # 优化建议
```

### 4.4 状态枚举

**定稿状态：**
- `is_finalized = False`: 草稿
- `is_finalized = True`: 已定稿

**幻觉状态：**
- `normal`: 正常
- `suspected`: 疑似幻觉
- `confirmed`: 确认幻觉

**自动化状态：**
- `pending`: 未自动化
- `scripted`: 已转脚本
- `automated`: 已自动化

---

## 5. API 端点设计

### 5.1 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/test-cases` | 用例列表（分页+筛选） |
| GET | `/api/v1/test-cases/{id}` | 用例详情 |
| POST | `/api/v1/test-cases` | 创建用例 |
| PUT | `/api/v1/test-cases/{id}` | 更新用例 |
| DELETE | `/api/v1/test-cases/{id}` | 删除用例（软删除） |
| POST | `/api/v1/test-cases/batch` | 批量操作 |
| GET | `/api/v1/test-cases/stats` | 统计数据 |

### 5.2 用例列表 API

**请求：**
```http
GET /api/v1/test-cases?
  project_id=uuid              # 必填，按项目筛选
  &is_finalized=true           # 可选，定稿状态
  &priority=P0,P1              # 可选，优先级（多选）
  &hallucination_status=suspected  # 可选，幻觉状态
  &point_id=uuid               # 可选，关联测试点
  &automation_status=pending   # 可选，自动化状态
  &created_start=2024-01-01    # 可选，创建时间起
  &created_end=2024-12-31      # 可选，创建时间止
  &keyword=登录                # 可选，名称模糊搜索
  &page=1                      # 分页页码
  &page_size=20                # 每页条数
```

**响应：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total": 100,
    "page": 1,
    "page_size": 20,
    "items": [
      {
        "id": "uuid",
        "project_id": "uuid",
        "point_id": "uuid",
        "point_name": "登录功能测试点",
        "name": "正常登录流程",
        "priority": "P0",
        "case_type": "functional",
        "automation_status": "pending",
        "is_finalized": false,
        "hallucination_status": "normal",
        "created_by": "admin",
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T11:00:00Z"
      }
    ]
  }
}
```

### 5.3 用例详情 API

**请求：**
```http
GET /api/v1/test-cases/{id}
```

**响应：**
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "project_id": "uuid",
    "point_id": "uuid",
    "point_name": "登录功能测试点",
    "name": "正常登录流程",
    "priority": "P0",
    "case_type": "functional",
    "precondition": "用户未登录",
    "steps": [
      {
        "seq": 1,
        "action": "打开",
        "target": "登录页",
        "data": "https://example.com/login",
        "expected": "页面正常加载"
      }
    ],
    "expected_result": "登录成功，跳转到首页",
    "is_finalized": false,
    "automation_status": "pending",
    "hallucination_status": "normal",
    "version": 1,
    "created_by": "admin",
    "created_at": "2024-01-01T10:00:00Z",
    "updated_at": "2024-01-01T11:00:00Z"
  }
}
```

### 5.4 创建用例 API

**请求：**
```http
POST /api/v1/test-cases
Content-Type: application/json

{
  "project_id": "uuid",
  "name": "正常登录流程",
  "priority": "P0",
  "case_type": "functional",
  "precondition": "用户未登录",
  "steps": [
    {
      "seq": 1,
      "action": "打开",
      "target": "登录页",
      "data": "https://example.com/login",
      "expected": "页面正常加载"
    }
  ],
  "expected_result": "登录成功",
  "point_id": "uuid"  // 可选
}
```

**响应：**
```json
{
  "code": 0,
  "message": "用例创建成功",
  "data": {
    "id": "uuid",
    "name": "正常登录流程"
  }
}
```

### 5.5 更新用例 API

**请求：**
```http
PUT /api/v1/test-cases/{id}
Content-Type: application/json

{
  "name": "正常登录流程（更新）",
  "priority": "P1",
  "steps": [...]
}
```

**响应：**
```json
{
  "code": 0,
  "message": "用例更新成功",
  "data": {
    "id": "uuid",
    "version": 2
  }
}
```

### 5.6 批量操作 API

**请求：**
```http
POST /api/v1/test-cases/batch
Content-Type: application/json

{
  "action": "finalize",  // finalize/unfinalize/delete/set_priority/set_hallucination
  "case_ids": ["uuid1", "uuid2"],
  "params": {            // 可选参数
    "priority": "P0",
    "hallucination_status": "normal"
  }
}
```

**响应：**
```json
{
  "code": 0,
  "message": "批量操作完成",
  "data": {
    "success_count": 2,
    "failed_count": 0,
    "failed_cases": []
  }
}
```

**支持的批量操作：**
- `finalize`: 批量定稿
- `unfinalize`: 批量取消定稿
- `delete`: 批量软删除
- `set_priority`: 批量设置优先级
- `set_hallucination`: 批量设置幻觉状态

### 5.7 统计数据 API

**请求：**
```http
GET /api/v1/test-cases/stats?project_id=uuid
```

**响应：**
```json
{
  "code": 0,
  "data": {
    "total": 120,
    "finalized": 80,
    "draft": 40,
    "by_priority": {
      "P0": 30,
      "P1": 50,
      "P2": 30,
      "P3": 10
    },
    "by_hallucination": {
      "normal": 100,
      "suspected": 15,
      "confirmed": 5
    }
  }
}
```

---

## 6. 前端设计

### 6.1 页面结构

#### 6.1.1 CaseList.vue（用例列表页）

**布局：**
```
┌────────────────────────────────────────────────┐
│  面包屑: 首页 > 用例管理                        │
├────────────────────────────────────────────────┤
│  统计卡片:                                      │
│  [总用例: 120] [已定稿: 80] [草稿: 40]         │
├────────────────────────────────────────────────┤
│  筛选器:                                        │
│  [项目▼] [状态▼] [优先级▼] [幻觉状态▼]        │
│  [测试点▼] [自动化状态▼] [时间范围]           │
│  [关键词搜索框] [搜索] [重置]                  │
├────────────────────────────────────────────────┤
│  工具栏:                                        │
│  [+ 新建用例]  批量操作: [定稿][删除][设优先级]│
├────────────────────────────────────────────────┤
│  用例表格: (支持勾选、排序)                     │
│  ☑ 用例名称    测试点    优先级 状态 幻觉 操作  │
│  ☑ 正常登录    登录功能  P0    草稿  正常  [编辑]│
│  ☐ 异常登录    登录功能  P1    已定稿 疑似 [编辑]│
├────────────────────────────────────────────────┤
│  分页: < 1 2 3 ... 10 >  共120条               │
└────────────────────────────────────────────────┘
```

**核心功能：**
1. 统计卡片展示（总数、已定稿、草稿）
2. 多维度筛选器（项目、状态、优先级、幻觉、测试点、自动化状态、时间范围、关键词）
3. 批量操作（勾选多个用例 → 批量定稿/删除/设优先级/设幻觉状态）
4. 表格展示（支持排序、分页）
5. 单行操作（编辑、删除）

#### 6.1.2 CaseDetail.vue（详情/编辑页）

**布局：**
```
┌────────────────────────────────────────────────┐
│  返回 | 用例详情                    [保存][取消]│
├────────────────────────────────────────────────┤
│  基本信息:                                      │
│  用例名称: [________________]                   │
│  关联测试点: [选择测试点▼]                      │
│  优先级: (•) P0 ( ) P1 ( ) P2 ( ) P3          │
│  用例类型: [functional▼]                        │
│  前置条件: [________________]                   │
│  预期结果: [________________]                   │
├────────────────────────────────────────────────┤
│  测试步骤: (表格编辑器)              [+ 添加步骤]│
│  序号 操作   目标元素     测试数据    预期  [删除]│
│  1    打开   登录页       url        加载  [🗑]  │
│  2    输入   用户名框     admin      成功  [🗑]  │
│  (支持拖拽排序 ☰)                               │
├────────────────────────────────────────────────┤
│  状态信息:                                      │
│  定稿状态: [草稿]  [一键定稿]                   │
│  幻觉状态: [正常]▼                              │
│  自动化状态: [未自动化]                         │
│  版本: v1  创建人: admin  创建时间: 2024-01-01  │
└────────────────────────────────────────────────┘
```

**核心功能：**
1. 基本信息编辑（名称、测试点、优先级、类型、前置条件、预期结果）
2. 步骤表格编辑器（增删改、拖拽排序）
3. 状态管理（一键定稿、设置幻觉状态）
4. 版本和审计信息展示

### 6.2 核心组件划分

```
views/
  └── cases/
      ├── CaseList.vue           // 用例列表页
      └── CaseDetail.vue         // 用例详情/编辑页

components/
  └── cases/
      ├── CaseFilters.vue        // 筛选器组件
      ├── CaseStatsCard.vue      // 统计卡片组件
      ├── StepEditor.vue         // 步骤表格编辑器
      └── BatchOperationBar.vue  // 批量操作工具栏

api/
  └── test-cases.js              // API 调用封装
```

### 6.3 步骤编辑器（StepEditor.vue）

**功能：**
- 表格形式展示步骤
- 支持行内编辑
- 支持拖拽排序
- 支持添加/删除步骤
- 自动更新序号

**实现：**
```vue
<template>
  <el-table 
    :data="steps" 
    row-key="seq"
    @row-drag="handleDrag"
  >
    <el-table-column type="index" label="序号" width="60" />
    <el-table-column prop="action" label="操作" width="120">
      <template #default="{ row }">
        <el-input v-model="row.action" size="small" />
      </template>
    </el-table-column>
    <el-table-column prop="target" label="目标元素" width="150">
      <template #default="{ row }">
        <el-input v-model="row.target" size="small" />
      </template>
    </el-table-column>
    <el-table-column prop="data" label="测试数据">
      <template #default="{ row }">
        <el-input v-model="row.data" size="small" />
      </template>
    </el-table-column>
    <el-table-column prop="expected" label="预期结果">
      <template #default="{ row }">
        <el-input v-model="row.expected" size="small" />
      </template>
    </el-table-column>
    <el-table-column label="操作" width="80">
      <template #default="{ $index }">
        <el-button 
          type="danger" 
          icon="Delete" 
          size="small"
          @click="handleDelete($index)"
        />
      </template>
    </el-table-column>
  </el-table>
  <el-button @click="handleAdd" class="mt-2">+ 添加步骤</el-button>
</template>
```

---

## 7. 后端服务层设计

### 7.1 TestCaseService

**文件**: `backend/app/services/test_case_service.py`

**核心方法：**

```python
class TestCaseService:
    
    async def list_cases(
        self, 
        db: AsyncSession,
        project_id: UUID,
        filters: CaseFilterParams,
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """
        用例列表查询
        - 动态构建 WHERE 条件
        - JOIN test_point 获取测试点名称
        - 分页查询
        """
        
    async def get_case_detail(
        self, 
        db: AsyncSession,
        case_id: UUID
    ) -> Optional[Dict]:
        """
        用例详情（包含关联的测试点完整信息）
        """
        
    async def create_case(
        self, 
        db: AsyncSession,
        case_data: CaseCreateRequest
    ) -> TestCase:
        """
        创建用例
        - 验证必填字段
        - 验证 steps JSON 格式
        - 设置默认值
        """
        
    async def update_case(
        self, 
        db: AsyncSession,
        case_id: UUID,
        case_data: CaseUpdateRequest
    ) -> TestCase:
        """
        更新用例
        - 版本号自增
        - 更新 updated_at
        """
        
    async def delete_case(
        self, 
        db: AsyncSession,
        case_id: UUID
    ) -> bool:
        """
        软删除用例
        """
        
    async def batch_operation(
        self, 
        db: AsyncSession,
        action: str,
        case_ids: List[UUID],
        params: Optional[Dict] = None
    ) -> Dict:
        """
        批量操作（事务）
        - finalize: 批量定稿
        - unfinalize: 批量取消定稿
        - delete: 批量软删除
        - set_priority: 批量设置优先级
        - set_hallucination: 批量设置幻觉状态
        """
        
    async def get_stats(
        self, 
        db: AsyncSession,
        project_id: UUID
    ) -> Dict:
        """
        统计数据
        - 总用例数
        - 各状态用例数
        - 各优先级用例数
        - 幻觉用例数
        """
```

### 7.2 搜索筛选逻辑

```python
def build_query_filters(filters: CaseFilterParams):
    """动态构建查询条件"""
    conditions = [TestCase.is_deleted == False]
    
    if filters.project_id:
        conditions.append(TestCase.project_id == filters.project_id)
    
    if filters.is_finalized is not None:
        conditions.append(TestCase.is_finalized == filters.is_finalized)
    
    if filters.priority:
        # 支持多选: "P0,P1" -> ["P0", "P1"]
        priorities = filters.priority.split(',')
        conditions.append(TestCase.priority.in_(priorities))
    
    if filters.hallucination_status:
        conditions.append(TestCase.hallucination_status == filters.hallucination_status)
    
    if filters.point_id:
        conditions.append(TestCase.point_id == filters.point_id)
    
    if filters.automation_status:
        conditions.append(TestCase.automation_status == filters.automation_status)
    
    if filters.created_start:
        conditions.append(TestCase.created_at >= filters.created_start)
    
    if filters.created_end:
        conditions.append(TestCase.created_at <= filters.created_end)
    
    if filters.keyword:
        # 名称模糊搜索
        conditions.append(TestCase.name.ilike(f'%{filters.keyword}%'))
    
    return and_(*conditions)
```

### 7.3 批量操作实现

```python
async def batch_operation(
    self,
    db: AsyncSession,
    action: str,
    case_ids: List[UUID],
    params: Optional[Dict] = None
) -> Dict:
    """批量操作"""
    success_count = 0
    failed_count = 0
    failed_cases = []
    
    try:
        # 查询所有用例
        query = select(TestCase).where(
            TestCase.id.in_(case_ids),
            TestCase.is_deleted == False
        )
        result = await db.execute(query)
        cases = result.scalars().all()
        
        # 执行操作
        for case in cases:
            try:
                if action == "finalize":
                    case.is_finalized = True
                elif action == "unfinalize":
                    case.is_finalized = False
                elif action == "delete":
                    case.is_deleted = True
                elif action == "set_priority":
                    case.priority = params.get("priority")
                elif action == "set_hallucination":
                    case.hallucination_status = params.get("hallucination_status")
                
                success_count += 1
            except Exception as e:
                failed_count += 1
                failed_cases.append({
                    "id": str(case.id),
                    "name": case.name,
                    "error": str(e)
                })
        
        # 提交事务
        await db.commit()
        
        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "failed_cases": failed_cases
        }
    
    except Exception as e:
        await db.rollback()
        raise
```

---

## 8. 错误处理和数据验证

### 8.1 Pydantic Schema 验证

```python
class CaseCreateRequest(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=100)
    priority: str = Field(..., pattern="^P[0-3]$")
    case_type: str = Field(default="functional")
    precondition: Optional[str] = None
    steps: List[StepSchema] = Field(..., min_items=1)
    expected_result: str = Field(..., min_length=1, max_length=200)
    point_id: Optional[UUID] = None

class StepSchema(BaseModel):
    seq: int = Field(..., ge=1)
    action: str = Field(..., min_length=1)
    target: str
    data: Optional[str] = None
    expected: Optional[str] = None

class CaseUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    priority: Optional[str] = Field(None, pattern="^P[0-3]$")
    steps: Optional[List[StepSchema]] = None
    # 其他字段可选
```

### 8.2 异常处理

```python
class CaseNotFoundException(HTTPException):
    def __init__(self, case_id: str):
        super().__init__(
            status_code=404, 
            detail=f"Test case {case_id} not found"
        )

class InvalidStepsFormatException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=400,
            detail="Steps field must be a valid JSON array"
        )

class CaseAlreadyFinalizedException(HTTPException):
    def __init__(self, case_id: str):
        super().__init__(
            status_code=400,
            detail=f"Test case {case_id} is already finalized"
        )
```

### 8.3 前端表单验证

```javascript
const rules = {
  name: [
    { required: true, message: '请输入用例名称', trigger: 'blur' },
    { min: 1, max: 100, message: '长度在 1 到 100 个字符', trigger: 'blur' }
  ],
  priority: [
    { required: true, message: '请选择优先级', trigger: 'change' }
  ],
  expected_result: [
    { required: true, message: '请输入预期结果', trigger: 'blur' },
    { max: 200, message: '长度不超过 200 个字符', trigger: 'blur' }
  ],
  steps: [
    { 
      type: 'array', 
      required: true, 
      message: '至少添加一个测试步骤', 
      trigger: 'change',
      validator: (rule, value, callback) => {
        if (!value || value.length === 0) {
          callback(new Error('至少添加一个测试步骤'))
        } else {
          callback()
        }
      }
    }
  ]
}
```

### 8.4 边界情况处理

| 场景 | 处理方式 |
|------|---------|
| 列表为空 | 显示"暂无数据"占位图 + "创建第一个用例"按钮 |
| 测试点被删除 | `point_id` 为 NULL，显示"已解除关联" |
| 并发编辑 | 使用乐观锁（version 字段），检测冲突后提示刷新 |
| 批量操作部分失败 | 返回详细结果，前端提示"成功 X 条，失败 Y 条" |
| 步骤为空 | 前端验证，至少需要一个步骤 |
| 步骤序号冲突 | 后端自动重排序号 |

---

## 9. 测试策略

### 9.1 后端单元测试

**测试文件**: `backend/tests/test_test_case_service.py`

```python
@pytest.mark.asyncio
async def test_list_cases_with_filters(db_session):
    """测试用例列表筛选"""
    service = TestCaseService()
    
    # 准备测试数据
    case1 = TestCase(name="用例1", priority="P0", is_finalized=True)
    case2 = TestCase(name="用例2", priority="P1", is_finalized=False)
    db_session.add_all([case1, case2])
    await db_session.commit()
    
    # 测试筛选
    filters = CaseFilterParams(is_finalized=True)
    result = await service.list_cases(db_session, filters)
    
    assert result['total'] == 1
    assert result['items'][0]['name'] == "用例1"

@pytest.mark.asyncio
async def test_batch_finalize(db_session):
    """测试批量定稿"""
    service = TestCaseService()
    
    # 创建测试用例
    cases = [TestCase(name=f"用例{i}", is_finalized=False) for i in range(3)]
    db_session.add_all(cases)
    await db_session.commit()
    
    case_ids = [c.id for c in cases]
    
    # 执行批量定稿
    result = await service.batch_operation(db_session, "finalize", case_ids)
    
    assert result['success_count'] == 3
    
    # 验证结果
    for case in cases:
        await db_session.refresh(case)
        assert case.is_finalized == True

@pytest.mark.asyncio
async def test_create_case_with_invalid_steps(db_session):
    """测试创建用例时步骤格式错误"""
    service = TestCaseService()
    
    case_data = CaseCreateRequest(
        project_id=uuid.uuid4(),
        name="测试用例",
        priority="P0",
        steps=[],  # 空步骤
        expected_result="预期结果"
    )
    
    with pytest.raises(ValueError):
        await service.create_case(db_session, case_data)
```

### 9.2 API 端点测试

**测试文件**: `backend/tests/test_test_case_api.py`

```python
@pytest.mark.asyncio
async def test_create_case(client, test_project):
    """测试创建用例"""
    payload = {
        "project_id": str(test_project.id),
        "name": "测试用例",
        "priority": "P0",
        "steps": [
            {"seq": 1, "action": "打开", "target": "登录页", "expected": "加载成功"}
        ],
        "expected_result": "登录成功"
    }
    
    response = await client.post("/api/v1/test-cases", json=payload)
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert response.json()['data']['name'] == "测试用例"

@pytest.mark.asyncio
async def test_update_case_not_found(client):
    """测试更新不存在的用例"""
    fake_id = str(uuid.uuid4())
    
    response = await client.put(
        f"/api/v1/test-cases/{fake_id}",
        json={"name": "新名称"}
    )
    
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_batch_delete(client, test_cases):
    """测试批量删除"""
    case_ids = [str(c.id) for c in test_cases[:2]]
    
    response = await client.post(
        "/api/v1/test-cases/batch",
        json={"action": "delete", "case_ids": case_ids}
    )
    
    assert response.status_code == 200
    assert response.json()['data']['success_count'] == 2
```

### 9.3 前端组件测试

**测试文件**: `frontend/tests/CaseList.spec.js`

```javascript
import { mount } from '@vue/test-utils'
import CaseList from '@/views/cases/CaseList.vue'

describe('CaseList', () => {
  it('renders case list correctly', () => {
    const wrapper = mount(CaseList, {
      props: {
        cases: [
          { id: '1', name: '用例1', priority: 'P0' }
        ]
      }
    })
    
    expect(wrapper.text()).toContain('用例1')
    expect(wrapper.text()).toContain('P0')
  })
  
  it('emits batch-delete event when batch delete button clicked', async () => {
    const wrapper = mount(CaseList)
    
    await wrapper.find('.batch-delete-btn').trigger('click')
    
    expect(wrapper.emitted()).toHaveProperty('batch-delete')
  })
  
  it('filters cases by priority', async () => {
    const wrapper = mount(CaseList)
    
    await wrapper.find('select[name="priority"]').setValue('P0')
    await wrapper.find('.search-btn').trigger('click')
    
    expect(wrapper.emitted()).toHaveProperty('filter-change')
  })
})
```

### 9.4 测试覆盖目标

- **后端单元测试**: 覆盖率 > 80%
- **API 端点测试**: 100% 覆盖所有端点
- **前端组件测试**: 核心组件覆盖率 > 60%
- **集成测试**: 覆盖完整的 CRUD 流程

---

## 10. 性能优化

### 10.1 数据库优化

**索引设计：**
```sql
-- 已有索引（test_case 表）
CREATE INDEX idx_test_case_project_id ON test_case(project_id);
CREATE INDEX idx_test_case_point_id ON test_case(point_id);
CREATE INDEX idx_test_case_created_at ON test_case(created_at);

-- 新增复合索引（优化筛选查询）
CREATE INDEX idx_test_case_project_finalized ON test_case(project_id, is_finalized) WHERE is_deleted = false;
CREATE INDEX idx_test_case_project_priority ON test_case(project_id, priority) WHERE is_deleted = false;
CREATE INDEX idx_test_case_hallucination ON test_case(hallucination_status) WHERE is_deleted = false;
```

### 10.2 查询优化

**分页优化：**
```python
# 使用 offset + limit
query = query.offset((page - 1) * page_size).limit(page_size)

# 避免 COUNT(*) 性能问题
# 当总数超过 10000 时，返回 "10000+"，不精确计数
```

**关联查询优化：**
```python
# 使用 JOIN 而不是 N+1 查询
query = select(TestCase, TestPoint.name.label('point_name')).join(
    TestPoint, 
    TestCase.point_id == TestPoint.id,
    isouter=True  # LEFT JOIN
)
```

### 10.3 前端优化

**虚拟滚动：**
- 当列表超过 100 条时，使用虚拟滚动（el-table-v2）

**分页加载：**
- 默认每页 20 条
- 支持切换每页条数（10/20/50/100）

**防抖处理：**
```javascript
// 搜索框防抖
const handleSearch = debounce(() => {
  fetchCases()
}, 300)
```

---

## 11. 安全考虑

### 11.1 权限控制

**基础权限：**
- 用户只能查看和操作自己项目的用例
- 通过 `project_id` 进行权限隔离

**后续扩展：**
- 二期可引入角色权限（管理员/测试工程师/只读用户）
- 使用中间件验证用户权限

### 11.2 输入验证

- 所有用户输入经过 Pydantic 验证
- SQL 查询使用参数化查询（防止 SQL 注入）
- XSS 防护：前端使用 `v-text` 而非 `v-html`

### 11.3 数据保护

- 软删除而非物理删除
- 关键操作记录审计日志（版本号、操作人、操作时间）

---

## 12. 部署要求

### 12.1 环境依赖

**Python 后端：**
```txt
fastapi>=0.104.0
sqlalchemy>=2.0.0
asyncpg>=0.29.0
pydantic>=2.0.0
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

**前端：**
```json
{
  "vue": "^3.3.0",
  "element-plus": "^2.4.0",
  "axios": "^1.5.0",
  "vue-router": "^4.2.0"
}
```

### 12.2 数据库迁移

**无需迁移脚本**，复用现有 `test_case` 表。

仅需确认索引：
```sql
-- 检查索引是否存在
SELECT indexname FROM pg_indexes 
WHERE tablename = 'test_case';

-- 如缺失，手动创建复合索引
CREATE INDEX idx_test_case_project_finalized 
ON test_case(project_id, is_finalized) 
WHERE is_deleted = false;
```

---

## 13. 开发计划

### 13.1 工作量估算

| 任务 | 预计时间 | 优先级 |
|------|---------|--------|
| 后端 API 端点 | 4小时 | P0 |
| 后端服务层 | 4小时 | P0 |
| 前端列表页 | 6小时 | P0 |
| 前端详情页 | 6小时 | P0 |
| 步骤编辑器 | 4小时 | P0 |
| 批量操作 | 3小时 | P1 |
| 单元测试 | 4小时 | P1 |
| API 测试 | 2小时 | P1 |
| 集成测试 | 2小时 | P2 |

**总计**: 约 35 小时（2-3 个工作日）

### 13.2 里程碑

**Day 1**: 
- ✅ 后端 API 端点完成
- ✅ 后端服务层完成
- ✅ 基础单元测试

**Day 2**:
- ✅ 前端列表页完成
- ✅ 前端详情页完成
- ✅ 步骤编辑器完成

**Day 3**:
- ✅ 批量操作完成
- ✅ 所有测试通过
- ✅ 集成测试完成
- ✅ 代码审查

---

## 14. 后续扩展（二期规划）

### 14.1 高级功能

1. **用例模板系统**
   - 保存用例为模板
   - 从模板创建用例
   - 模板参数化

2. **高级搜索**
   - 全文搜索（Elasticsearch）
   - 步骤内容搜索
   - 标签系统

3. **版本对比**
   - 用例版本历史查看
   - 版本对比（Diff）
   - 版本回滚

4. **协作功能**
   - 评审流程（多人评审）
   - 评论系统
   - @提醒通知

5. **高级统计**
   - 用例覆盖率分析
   - 测试执行趋势图
   - 自定义报表

### 14.2 集成扩展

- 与用例转脚本模块集成
- 与自动化执行模块集成
- 与缺陷管理模块集成

---

## 15. 验收标准

- [ ] 用户可以查看项目下所有用例列表
- [ ] 支持按状态、优先级、幻觉状态、测试点筛选
- [ ] 支持按时间范围筛选和关键词搜索
- [ ] 用户可以创建、编辑、删除用例
- [ ] 步骤编辑器支持添加、删除、排序步骤
- [ ] 支持一键定稿/取消定稿
- [ ] 支持批量定稿、批量删除、批量设置优先级
- [ ] 统计卡片正确显示总数和各状态数量
- [ ] 分页功能正常工作
- [ ] 所有表单验证生效
- [ ] 错误提示友好清晰
- [ ] 单元测试覆盖率 > 80%
- [ ] API 端点测试 100% 覆盖

---

**文档状态**: ✅ 设计完成，等待用户审批
