# 用例管理模块 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现用例管理模块，支持用例的 CRUD、筛选、批量操作，完成从 AI 生成到人工定稿的完整流程。

**Architecture:** 单体式设计，后端使用 FastAPI + TestCaseService 封装业务逻辑，前端使用 Vue3 + Element Plus 实现列表页和详情页，复用现有 test_case 表无需数据库迁移。

**Tech Stack:** FastAPI + SQLAlchemy + PostgreSQL + Vue3 + Element Plus

---

## 文件结构规划

### 后端新增/修改文件

**服务层**:
- `backend/app/services/test_case_service.py` - 用例服务（CRUD + 筛选 + 批量操作）

**API层**:
- `backend/app/api/v1/test_cases.py` - 用例管理 API 端点

**Schema层**:
- `backend/app/schemas/test_case.py` - Pydantic 验证 Schema

**测试文件**:
- `backend/tests/test_test_case_service.py` - 服务层单元测试
- `backend/tests/test_test_case_api.py` - API 端点测试

**修改文件**:
- `backend/app/api/__init__.py` - 注册新路由

### 前端新增文件

**页面**:
- `frontend/src/views/cases/CaseList.vue` - 用例列表页
- `frontend/src/views/cases/CaseDetail.vue` - 用例详情/编辑页

**组件**:
- `frontend/src/components/cases/CaseFilters.vue` - 筛选器组件
- `frontend/src/components/cases/CaseStatsCard.vue` - 统计卡片
- `frontend/src/components/cases/StepEditor.vue` - 步骤编辑器
- `frontend/src/components/cases/BatchOperationBar.vue` - 批量操作工具栏

**API 封装**:
- `frontend/src/api/test-cases.js` - API 调用封装

**修改文件**:
- `frontend/src/router/index.js` - 添加路由
- `frontend/src/layouts/MainLayout.vue` - 添加导航菜单

---

## Task 1: 后端 Schema 定义

**Files:**
- Create: `backend/app/schemas/test_case.py`

- [ ] **Step 1: 创建 Schema 文件**

```python
# backend/app/schemas/test_case.py
"""
Test case schemas for request/response validation
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from uuid import UUID
from datetime import datetime


class StepSchema(BaseModel):
    """测试步骤 Schema"""
    seq: int = Field(..., ge=1, description="步骤序号")
    action: str = Field(..., min_length=1, max_length=50, description="操作类型")
    target: str = Field(..., max_length=200, description="目标元素")
    data: Optional[str] = Field(None, max_length=500, description="测试数据")
    expected: Optional[str] = Field(None, max_length=200, description="预期结果")


class CaseFilterParams(BaseModel):
    """用例筛选参数"""
    project_id: UUID
    is_finalized: Optional[bool] = None
    priority: Optional[str] = None  # 逗号分隔: "P0,P1"
    hallucination_status: Optional[str] = None
    point_id: Optional[UUID] = None
    automation_status: Optional[str] = None
    created_start: Optional[datetime] = None
    created_end: Optional[datetime] = None
    keyword: Optional[str] = None


class CaseCreateRequest(BaseModel):
    """创建用例请求"""
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=100)
    priority: str = Field(..., pattern="^P[0-3]$")
    case_type: str = Field(default="functional")
    precondition: Optional[str] = Field(None, max_length=1000)
    steps: List[StepSchema] = Field(..., min_items=1)
    expected_result: str = Field(..., min_length=1, max_length=200)
    point_id: Optional[UUID] = None
    
    @field_validator('steps')
    @classmethod
    def validate_steps(cls, v):
        if not v or len(v) == 0:
            raise ValueError("至少需要一个测试步骤")
        # 验证序号连续性
        seqs = [step.seq for step in v]
        if sorted(seqs) != list(range(1, len(v) + 1)):
            raise ValueError("步骤序号必须从1开始连续")
        return v


class CaseUpdateRequest(BaseModel):
    """更新用例请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    priority: Optional[str] = Field(None, pattern="^P[0-3]$")
    case_type: Optional[str] = None
    precondition: Optional[str] = Field(None, max_length=1000)
    steps: Optional[List[StepSchema]] = None
    expected_result: Optional[str] = Field(None, min_length=1, max_length=200)
    point_id: Optional[UUID] = None
    is_finalized: Optional[bool] = None
    hallucination_status: Optional[str] = None
    automation_status: Optional[str] = None


class BatchOperationRequest(BaseModel):
    """批量操作请求"""
    action: str = Field(..., pattern="^(finalize|unfinalize|delete|set_priority|set_hallucination)$")
    case_ids: List[UUID] = Field(..., min_items=1)
    params: Optional[dict] = None
    
    @field_validator('params')
    @classmethod
    def validate_params(cls, v, info):
        action = info.data.get('action')
        if action == 'set_priority' and (not v or 'priority' not in v):
            raise ValueError("set_priority 操作需要 params.priority")
        if action == 'set_hallucination' and (not v or 'hallucination_status' not in v):
            raise ValueError("set_hallucination 操作需要 params.hallucination_status")
        return v


class CaseResponse(BaseModel):
    """用例响应"""
    id: UUID
    project_id: UUID
    point_id: Optional[UUID]
    point_name: Optional[str]  # 关联查询字段
    name: str
    priority: str
    case_type: str
    automation_status: str
    is_finalized: bool
    hallucination_status: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime


class CaseDetailResponse(CaseResponse):
    """用例详情响应（包含完整信息）"""
    precondition: Optional[str]
    steps: List[dict]
    expected_result: str
    version: int


class CaseListResponse(BaseModel):
    """用例列表响应"""
    total: int
    page: int
    page_size: int
    items: List[CaseResponse]


class CaseStatsResponse(BaseModel):
    """用例统计响应"""
    total: int
    finalized: int
    draft: int
    by_priority: dict
    by_hallucination: dict
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/schemas/test_case.py
git commit -m "feat: add test case schemas for validation"
```

---

## Task 2: 后端服务层实现

**Files:**
- Create: `backend/app/services/test_case_service.py`

- [ ] **Step 1: 创建服务层文件（第1部分 - 基础结构）**

```python
# backend/app/services/test_case_service.py
"""
Test case service - 用例管理业务逻辑
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_
from sqlalchemy.orm import selectinload
from typing import Dict, List, Optional
from uuid import UUID
import logging

from app.models.test_case import TestCase, TestPoint
from app.schemas.test_case import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseFilterParams,
    BatchOperationRequest
)

logger = logging.getLogger(__name__)


class TestCaseService:
    """用例管理服务"""
    
    def _build_query_filters(self, filters: CaseFilterParams):
        """
        动态构建查询条件
        
        Args:
            filters: 筛选参数
            
        Returns:
            查询条件列表
        """
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

- [ ] **Step 2: 创建服务层文件（第2部分 - 列表和详情）**

```python
# 继续在 backend/app/services/test_case_service.py 中添加

    async def list_cases(
        self,
        db: AsyncSession,
        filters: CaseFilterParams,
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """
        用例列表查询
        
        Args:
            db: 数据库会话
            filters: 筛选参数
            page: 页码
            page_size: 每页数量
            
        Returns:
            {"total": int, "page": int, "page_size": int, "items": List[Dict]}
        """
        try:
            # 构建查询条件
            conditions = self._build_query_filters(filters)
            
            # 查询总数
            count_query = select(func.count(TestCase.id)).where(conditions)
            total_result = await db.execute(count_query)
            total = total_result.scalar()
            
            # 查询列表（LEFT JOIN test_point 获取测试点名称）
            query = select(TestCase, TestPoint.name.label('point_name')).join(
                TestPoint,
                TestCase.point_id == TestPoint.id,
                isouter=True  # LEFT JOIN
            ).where(conditions).order_by(TestCase.created_at.desc())
            
            # 分页
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)
            
            result = await db.execute(query)
            rows = result.all()
            
            # 组装数据
            items = []
            for case, point_name in rows:
                item = case.to_dict()
                item['point_name'] = point_name
                items.append(item)
            
            logger.info(f"Found {total} cases, returning page {page} with {len(items)} items")
            
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": items
            }
            
        except Exception as e:
            logger.error(f"List cases failed: {e}")
            raise
    
    async def get_case_detail(
        self,
        db: AsyncSession,
        case_id: UUID
    ) -> Optional[Dict]:
        """
        获取用例详情
        
        Args:
            db: 数据库会话
            case_id: 用例ID
            
        Returns:
            用例详情字典，不存在返回 None
        """
        try:
            # 查询用例（带测试点信息）
            query = select(TestCase, TestPoint.name.label('point_name')).join(
                TestPoint,
                TestCase.point_id == TestPoint.id,
                isouter=True
            ).where(
                TestCase.id == case_id,
                TestCase.is_deleted == False
            )
            
            result = await db.execute(query)
            row = result.first()
            
            if not row:
                return None
            
            case, point_name = row
            detail = case.to_dict()
            detail['point_name'] = point_name
            
            logger.info(f"Retrieved case detail: {case_id}")
            
            return detail
            
        except Exception as e:
            logger.error(f"Get case detail failed: {e}")
            raise
```

- [ ] **Step 3: 创建服务层文件（第3部分 - 创建和更新）**

```python
# 继续在 backend/app/services/test_case_service.py 中添加

    async def create_case(
        self,
        db: AsyncSession,
        case_data: CaseCreateRequest,
        created_by: str = "system"
    ) -> TestCase:
        """
        创建用例
        
        Args:
            db: 数据库会话
            case_data: 用例数据
            created_by: 创建人
            
        Returns:
            创建的用例对象
        """
        try:
            # 转换 steps 为 dict 列表
            steps_dict = [step.model_dump() for step in case_data.steps]
            
            # 创建用例对象
            case = TestCase(
                project_id=case_data.project_id,
                point_id=case_data.point_id,
                name=case_data.name,
                priority=case_data.priority,
                case_type=case_data.case_type,
                precondition=case_data.precondition,
                steps=steps_dict,
                expected_result=case_data.expected_result,
                is_finalized=False,
                version=1,
                created_by=created_by
            )
            
            db.add(case)
            await db.commit()
            await db.refresh(case)
            
            logger.info(f"Created case: {case.id} - {case.name}")
            
            return case
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Create case failed: {e}")
            raise
    
    async def update_case(
        self,
        db: AsyncSession,
        case_id: UUID,
        case_data: CaseUpdateRequest
    ) -> Optional[TestCase]:
        """
        更新用例
        
        Args:
            db: 数据库会话
            case_id: 用例ID
            case_data: 更新数据
            
        Returns:
            更新后的用例对象，不存在返回 None
        """
        try:
            # 查询用例
            query = select(TestCase).where(
                TestCase.id == case_id,
                TestCase.is_deleted == False
            )
            result = await db.execute(query)
            case = result.scalar_one_or_none()
            
            if not case:
                return None
            
            # 更新字段
            update_data = case_data.model_dump(exclude_unset=True)
            
            # 特殊处理 steps
            if 'steps' in update_data and update_data['steps']:
                update_data['steps'] = [step.model_dump() if hasattr(step, 'model_dump') else step 
                                       for step in update_data['steps']]
            
            for key, value in update_data.items():
                setattr(case, key, value)
            
            # 版本号自增
            case.version += 1
            
            await db.commit()
            await db.refresh(case)
            
            logger.info(f"Updated case: {case.id}, version: {case.version}")
            
            return case
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Update case failed: {e}")
            raise
```

- [ ] **Step 4: 创建服务层文件（第4部分 - 删除和批量操作）**

```python
# 继续在 backend/app/services/test_case_service.py 中添加

    async def delete_case(
        self,
        db: AsyncSession,
        case_id: UUID
    ) -> bool:
        """
        删除用例（软删除）
        
        Args:
            db: 数据库会话
            case_id: 用例ID
            
        Returns:
            是否成功
        """
        try:
            # 查询用例
            query = select(TestCase).where(
                TestCase.id == case_id,
                TestCase.is_deleted == False
            )
            result = await db.execute(query)
            case = result.scalar_one_or_none()
            
            if not case:
                return False
            
            # 软删除
            case.is_deleted = True
            
            await db.commit()
            
            logger.info(f"Deleted case: {case_id}")
            
            return True
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Delete case failed: {e}")
            raise
    
    async def batch_operation(
        self,
        db: AsyncSession,
        request: BatchOperationRequest
    ) -> Dict:
        """
        批量操作
        
        Args:
            db: 数据库会话
            request: 批量操作请求
            
        Returns:
            {"success_count": int, "failed_count": int, "failed_cases": List}
        """
        success_count = 0
        failed_count = 0
        failed_cases = []
        
        try:
            # 查询所有用例
            query = select(TestCase).where(
                TestCase.id.in_(request.case_ids),
                TestCase.is_deleted == False
            )
            result = await db.execute(query)
            cases = result.scalars().all()
            
            # 执行操作
            for case in cases:
                try:
                    if request.action == "finalize":
                        case.is_finalized = True
                    elif request.action == "unfinalize":
                        case.is_finalized = False
                    elif request.action == "delete":
                        case.is_deleted = True
                    elif request.action == "set_priority":
                        case.priority = request.params.get("priority")
                    elif request.action == "set_hallucination":
                        case.hallucination_status = request.params.get("hallucination_status")
                    
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
            
            logger.info(f"Batch operation {request.action}: success={success_count}, failed={failed_count}")
            
            return {
                "success_count": success_count,
                "failed_count": failed_count,
                "failed_cases": failed_cases
            }
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Batch operation failed: {e}")
            raise
```

- [ ] **Step 5: 创建服务层文件（第5部分 - 统计）**

```python
# 继续在 backend/app/services/test_case_service.py 中添加

    async def get_stats(
        self,
        db: AsyncSession,
        project_id: UUID
    ) -> Dict:
        """
        获取用例统计数据
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            
        Returns:
            统计数据字典
        """
        try:
            # 基础条件
            base_condition = and_(
                TestCase.project_id == project_id,
                TestCase.is_deleted == False
            )
            
            # 总数
            total_query = select(func.count(TestCase.id)).where(base_condition)
            total_result = await db.execute(total_query)
            total = total_result.scalar()
            
            # 已定稿数量
            finalized_query = select(func.count(TestCase.id)).where(
                base_condition,
                TestCase.is_finalized == True
            )
            finalized_result = await db.execute(finalized_query)
            finalized = finalized_result.scalar()
            
            # 草稿数量
            draft = total - finalized
            
            # 按优先级统计
            priority_query = select(
                TestCase.priority,
                func.count(TestCase.id).label('count')
            ).where(base_condition).group_by(TestCase.priority)
            
            priority_result = await db.execute(priority_query)
            by_priority = {row.priority: row.count for row in priority_result}
            
            # 按幻觉状态统计
            hallucination_query = select(
                TestCase.hallucination_status,
                func.count(TestCase.id).label('count')
            ).where(base_condition).group_by(TestCase.hallucination_status)
            
            hallucination_result = await db.execute(hallucination_query)
            by_hallucination = {row.hallucination_status: row.count for row in hallucination_result}
            
            logger.info(f"Retrieved stats for project {project_id}: total={total}")
            
            return {
                "total": total,
                "finalized": finalized,
                "draft": draft,
                "by_priority": by_priority,
                "by_hallucination": by_hallucination
            }
            
        except Exception as e:
            logger.error(f"Get stats failed: {e}")
            raise
```

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/test_case_service.py
git commit -m "feat: implement test case service with CRUD and batch operations"
```

---

## Task 3: 后端 API 端点实现

**Files:**
- Create: `backend/app/api/v1/test_cases.py`
- Modify: `backend/app/api/__init__.py`

- [ ] **Step 1: 创建 API 端点文件（第1部分 - 基础结构）**

```python
# backend/app/api/v1/test_cases.py
"""
Test case management API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID
import logging

from app.core.database import get_db
from app.services.test_case_service import TestCaseService
from app.schemas.test_case import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseFilterParams,
    BatchOperationRequest,
    CaseListResponse,
    CaseDetailResponse,
    CaseStatsResponse
)

router = APIRouter()
logger = logging.getLogger(__name__)

# 常量
DEFAULT_USER = "system"  # TODO: 从认证上下文获取当前用户


def get_test_case_service() -> TestCaseService:
    """依赖注入：获取服务实例"""
    return TestCaseService()
```

- [ ] **Step 2: 创建 API 端点文件（第2部分 - 列表和详情）**

```python
# 继续在 backend/app/api/v1/test_cases.py 中添加

@router.get("/", summary="获取用例列表")
async def list_cases(
    project_id: UUID = Query(..., description="项目ID"),
    is_finalized: Optional[bool] = Query(None, description="是否已定稿"),
    priority: Optional[str] = Query(None, description="优先级（多选逗号分隔）"),
    hallucination_status: Optional[str] = Query(None, description="幻觉状态"),
    point_id: Optional[UUID] = Query(None, description="关联测试点ID"),
    automation_status: Optional[str] = Query(None, description="自动化状态"),
    created_start: Optional[str] = Query(None, description="创建时间起（ISO格式）"),
    created_end: Optional[str] = Query(None, description="创建时间止（ISO格式）"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    获取用例列表（分页 + 筛选）
    """
    try:
        # 构建筛选参数
        from datetime import datetime
        filters = CaseFilterParams(
            project_id=project_id,
            is_finalized=is_finalized,
            priority=priority,
            hallucination_status=hallucination_status,
            point_id=point_id,
            automation_status=automation_status,
            created_start=datetime.fromisoformat(created_start) if created_start else None,
            created_end=datetime.fromisoformat(created_end) if created_end else None,
            keyword=keyword
        )
        
        # 查询列表
        result = await service.list_cases(db, filters, page, page_size)
        
        return {
            "code": 0,
            "message": "success",
            "data": result
        }
        
    except Exception as e:
        logger.error(f"List cases failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{case_id}", summary="获取用例详情")
async def get_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    获取用例详情
    """
    try:
        case = await service.get_case_detail(db, case_id)
        
        if not case:
            raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
        
        return {
            "code": 0,
            "message": "success",
            "data": case
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get case failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: 创建 API 端点文件（第3部分 - 创建、更新、删除）**

```python
# 继续在 backend/app/api/v1/test_cases.py 中添加

@router.post("/", summary="创建用例")
async def create_case(
    request: CaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    创建用例
    """
    try:
        case = await service.create_case(db, request, created_by=DEFAULT_USER)
        
        return {
            "code": 0,
            "message": "用例创建成功",
            "data": {
                "id": str(case.id),
                "name": case.name
            }
        }
        
    except Exception as e:
        logger.error(f"Create case failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{case_id}", summary="更新用例")
async def update_case(
    case_id: UUID,
    request: CaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    更新用例
    """
    try:
        case = await service.update_case(db, case_id, request)
        
        if not case:
            raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
        
        return {
            "code": 0,
            "message": "用例更新成功",
            "data": {
                "id": str(case.id),
                "version": case.version
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update case failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{case_id}", summary="删除用例")
async def delete_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    删除用例（软删除）
    """
    try:
        success = await service.delete_case(db, case_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
        
        return {
            "code": 0,
            "message": "用例删除成功"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete case failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: 创建 API 端点文件（第4部分 - 批量操作和统计）**

```python
# 继续在 backend/app/api/v1/test_cases.py 中添加

@router.post("/batch", summary="批量操作")
async def batch_operation(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    批量操作用例
    
    支持的操作：
    - finalize: 批量定稿
    - unfinalize: 批量取消定稿
    - delete: 批量删除
    - set_priority: 批量设置优先级
    - set_hallucination: 批量设置幻觉状态
    """
    try:
        result = await service.batch_operation(db, request)
        
        return {
            "code": 0,
            "message": "批量操作完成",
            "data": result
        }
        
    except Exception as e:
        logger.error(f"Batch operation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/summary", summary="获取统计数据")
async def get_stats(
    project_id: UUID = Query(..., description="项目ID"),
    db: AsyncSession = Depends(get_db),
    service: TestCaseService = Depends(get_test_case_service)
):
    """
    获取用例统计数据
    """
    try:
        stats = await service.get_stats(db, project_id)
        
        return {
            "code": 0,
            "message": "success",
            "data": stats
        }
        
    except Exception as e:
        logger.error(f"Get stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 5: 注册路由**

```python
# backend/app/api/__init__.py
# 在文件中添加导入和路由注册

from app.api.v1 import test_cases

# 在 api_router 中添加
api_router.include_router(
    test_cases.router,
    prefix="/test-cases",
    tags=["test-cases"]
)
```

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/v1/test_cases.py backend/app/api/__init__.py
git commit -m "feat: add test case management API endpoints"
```

---

## Task 4: 后端测试实现

**Files:**
- Create: `backend/tests/test_test_case_service.py`
- Create: `backend/tests/test_test_case_api.py`

- [ ] **Step 1: 创建服务层测试文件**

```python
# backend/tests/test_test_case_service.py
"""
Test case service unit tests
"""

import pytest
from uuid import uuid4
from app.services.test_case_service import TestCaseService
from app.models.test_case import TestCase, TestPoint
from app.schemas.test_case import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseFilterParams,
    BatchOperationRequest,
    StepSchema
)


@pytest.mark.asyncio
async def test_create_case(db_session, test_project):
    """测试创建用例"""
    service = TestCaseService()
    
    case_data = CaseCreateRequest(
        project_id=test_project.id,
        name="测试用例",
        priority="P0",
        steps=[StepSchema(seq=1, action="打开", target="登录页", expected="加载成功")],
        expected_result="登录成功"
    )
    
    case = await service.create_case(db_session, case_data)
    
    assert case.name == "测试用例"
    assert case.priority == "P0"
    assert case.is_finalized == False
    assert case.version == 1


@pytest.mark.asyncio
async def test_list_cases_with_filters(db_session, test_project):
    """测试用例列表筛选"""
    service = TestCaseService()
    
    # 准备测试数据
    case1 = TestCase(
        project_id=test_project.id,
        name="用例1",
        priority="P0",
        is_finalized=True,
        steps=[{"seq": 1, "action": "test"}],
        expected_result="结果1"
    )
    case2 = TestCase(
        project_id=test_project.id,
        name="用例2",
        priority="P1",
        is_finalized=False,
        steps=[{"seq": 1, "action": "test"}],
        expected_result="结果2"
    )
    db_session.add_all([case1, case2])
    await db_session.commit()
    
    # 测试筛选已定稿
    filters = CaseFilterParams(project_id=test_project.id, is_finalized=True)
    result = await service.list_cases(db_session, filters)
    
    assert result['total'] == 1
    assert result['items'][0]['name'] == "用例1"
    
    # 测试筛选优先级
    filters = CaseFilterParams(project_id=test_project.id, priority="P0,P1")
    result = await service.list_cases(db_session, filters)
    
    assert result['total'] == 2


@pytest.mark.asyncio
async def test_update_case(db_session, test_case):
    """测试更新用例"""
    service = TestCaseService()
    
    update_data = CaseUpdateRequest(name="新名称", priority="P1")
    updated_case = await service.update_case(db_session, test_case.id, update_data)
    
    assert updated_case.name == "新名称"
    assert updated_case.priority == "P1"
    assert updated_case.version == 2


@pytest.mark.asyncio
async def test_batch_finalize(db_session, test_project):
    """测试批量定稿"""
    service = TestCaseService()
    
    # 创建测试用例
    cases = []
    for i in range(3):
        case = TestCase(
            project_id=test_project.id,
            name=f"用例{i}",
            priority="P1",
            is_finalized=False,
            steps=[{"seq": 1, "action": "test"}],
            expected_result="结果"
        )
        cases.append(case)
    
    db_session.add_all(cases)
    await db_session.commit()
    
    case_ids = [c.id for c in cases]
    
    # 执行批量定稿
    request = BatchOperationRequest(action="finalize", case_ids=case_ids)
    result = await service.batch_operation(db_session, request)
    
    assert result['success_count'] == 3
    assert result['failed_count'] == 0
    
    # 验证结果
    for case in cases:
        await db_session.refresh(case)
        assert case.is_finalized == True


@pytest.mark.asyncio
async def test_get_stats(db_session, test_project):
    """测试统计数据"""
    service = TestCaseService()
    
    # 准备测试数据
    for i in range(5):
        case = TestCase(
            project_id=test_project.id,
            name=f"用例{i}",
            priority="P0" if i < 2 else "P1",
            is_finalized=i < 3,
            steps=[{"seq": 1, "action": "test"}],
            expected_result="结果"
        )
        db_session.add(case)
    
    await db_session.commit()
    
    # 获取统计
    stats = await service.get_stats(db_session, test_project.id)
    
    assert stats['total'] == 5
    assert stats['finalized'] == 3
    assert stats['draft'] == 2
    assert stats['by_priority']['P0'] == 2
    assert stats['by_priority']['P1'] == 3
```

- [ ] **Step 2: 运行服务层测试**

Run: `cd backend && pytest tests/test_test_case_service.py -v`

Expected: 所有测试通过

- [ ] **Step 3: 创建 API 测试文件**

```python
# backend/tests/test_test_case_api.py
"""
Test case API endpoint tests
"""

import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_create_case_api(client, test_project):
    """测试创建用例 API"""
    payload = {
        "project_id": str(test_project.id),
        "name": "测试用例",
        "priority": "P0",
        "steps": [
            {"seq": 1, "action": "打开", "target": "登录页", "expected": "加载成功"}
        ],
        "expected_result": "登录成功"
    }
    
    response = await client.post("/api/v1/test-cases/", json=payload)
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert response.json()['data']['name'] == "测试用例"


@pytest.mark.asyncio
async def test_get_case_api(client, test_case):
    """测试获取用例详情 API"""
    response = await client.get(f"/api/v1/test-cases/{test_case.id}")
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert response.json()['data']['name'] == test_case.name


@pytest.mark.asyncio
async def test_get_case_not_found(client):
    """测试获取不存在的用例"""
    fake_id = str(uuid4())
    response = await client.get(f"/api/v1/test-cases/{fake_id}")
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_case_api(client, test_case):
    """测试更新用例 API"""
    payload = {"name": "新名称", "priority": "P1"}
    
    response = await client.put(f"/api/v1/test-cases/{test_case.id}", json=payload)
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert response.json()['data']['version'] == 2


@pytest.mark.asyncio
async def test_delete_case_api(client, test_case):
    """测试删除用例 API"""
    response = await client.delete(f"/api/v1/test-cases/{test_case.id}")
    
    assert response.status_code == 200
    assert response.json()['code'] == 0


@pytest.mark.asyncio
async def test_list_cases_api(client, test_project, test_cases):
    """测试用例列表 API"""
    response = await client.get(f"/api/v1/test-cases/?project_id={test_project.id}")
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert response.json()['data']['total'] > 0


@pytest.mark.asyncio
async def test_batch_operation_api(client, test_cases):
    """测试批量操作 API"""
    case_ids = [str(c.id) for c in test_cases[:2]]
    
    payload = {
        "action": "finalize",
        "case_ids": case_ids
    }
    
    response = await client.post("/api/v1/test-cases/batch", json=payload)
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert response.json()['data']['success_count'] == 2


@pytest.mark.asyncio
async def test_get_stats_api(client, test_project):
    """测试统计数据 API"""
    response = await client.get(f"/api/v1/test-cases/stats/summary?project_id={test_project.id}")
    
    assert response.status_code == 200
    assert response.json()['code'] == 0
    assert 'total' in response.json()['data']
```

- [ ] **Step 4: 运行 API 测试**

Run: `cd backend && pytest tests/test_test_case_api.py -v`

Expected: 所有测试通过

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_test_case_service.py backend/tests/test_test_case_api.py
git commit -m "test: add unit and API tests for test case management"
```

---

## Task 5: 前端 API 封装

**Files:**
- Create: `frontend/src/api/test-cases.js`

- [ ] **Step 1: 创建 API 封装文件**

```javascript
// frontend/src/api/test-cases.js
/**
 * Test case management API
 */

import request from './request'

/**
 * 获取用例列表
 */
export function listCases(params) {
  return request({
    url: '/test-cases/',
    method: 'get',
    params
  })
}

/**
 * 获取用例详情
 */
export function getCase(caseId) {
  return request({
    url: `/test-cases/${caseId}`,
    method: 'get'
  })
}

/**
 * 创建用例
 */
export function createCase(data) {
  return request({
    url: '/test-cases/',
    method: 'post',
    data
  })
}

/**
 * 更新用例
 */
export function updateCase(caseId, data) {
  return request({
    url: `/test-cases/${caseId}`,
    method: 'put',
    data
  })
}

/**
 * 删除用例
 */
export function deleteCase(caseId) {
  return request({
    url: `/test-cases/${caseId}`,
    method: 'delete'
  })
}

/**
 * 批量操作
 */
export function batchOperation(data) {
  return request({
    url: '/test-cases/batch',
    method: 'post',
    data
  })
}

/**
 * 获取统计数据
 */
export function getStats(projectId) {
  return request({
    url: '/test-cases/stats/summary',
    method: 'get',
    params: { project_id: projectId }
  })
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/api/test-cases.js
git commit -m "feat: add test case API wrapper"
```

---

## Task 6: 前端核心组件实现

**Files:**
- Create: `frontend/src/components/cases/StepEditor.vue`
- Create: `frontend/src/components/cases/CaseFilters.vue`
- Create: `frontend/src/components/cases/CaseStatsCard.vue`
- Create: `frontend/src/components/cases/BatchOperationBar.vue`

- [ ] **Step 1: 创建步骤编辑器组件**

```vue
<!-- frontend/src/components/cases/StepEditor.vue -->
<template>
  <div class="step-editor">
    <el-table :data="localSteps" style="width: 100%" border>
      <el-table-column type="index" label="序号" width="60" />
      
      <el-table-column prop="action" label="操作" width="120">
        <template #default="{ row }">
          <el-input v-model="row.action" size="small" placeholder="打开/点击/输入" />
        </template>
      </el-table-column>
      
      <el-table-column prop="target" label="目标元素" width="150">
        <template #default="{ row }">
          <el-input v-model="row.target" size="small" placeholder="元素描述" />
        </template>
      </el-table-column>
      
      <el-table-column prop="data" label="测试数据">
        <template #default="{ row }">
          <el-input v-model="row.data" size="small" placeholder="可选" />
        </template>
      </el-table-column>
      
      <el-table-column prop="expected" label="预期结果">
        <template #default="{ row }">
          <el-input v-model="row.expected" size="small" placeholder="可选" />
        </template>
      </el-table-column>
      
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ $index }">
          <el-button
            type="danger"
            icon="Delete"
            size="small"
            link
            @click="handleDelete($index)"
          />
        </template>
      </el-table-column>
    </el-table>
    
    <el-button
      type="primary"
      icon="Plus"
      plain
      class="mt-2"
      @click="handleAdd"
    >
      添加步骤
    </el-button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue'])

const localSteps = ref([...props.modelValue])

// 监听外部变化
watch(() => props.modelValue, (newVal) => {
  localSteps.value = [...newVal]
}, { deep: true })

// 监听内部变化，同步到父组件
watch(localSteps, (newVal) => {
  // 更新序号
  const stepsWithSeq = newVal.map((step, index) => ({
    ...step,
    seq: index + 1
  }))
  emit('update:modelValue', stepsWithSeq)
}, { deep: true })

const handleAdd = () => {
  localSteps.value.push({
    seq: localSteps.value.length + 1,
    action: '',
    target: '',
    data: '',
    expected: ''
  })
}

const handleDelete = (index) => {
  localSteps.value.splice(index, 1)
}
</script>

<style scoped>
.step-editor {
  width: 100%;
}
.mt-2 {
  margin-top: 8px;
}
</style>
```

- [ ] **Step 2: 创建筛选器组件**

```vue
<!-- frontend/src/components/cases/CaseFilters.vue -->
<template>
  <el-form :model="filters" inline class="case-filters">
    <el-form-item label="定稿状态">
      <el-select v-model="filters.is_finalized" placeholder="全部" clearable style="width: 120px">
        <el-option label="草稿" :value="false" />
        <el-option label="已定稿" :value="true" />
      </el-select>
    </el-form-item>
    
    <el-form-item label="优先级">
      <el-select v-model="filters.priority" placeholder="全部" clearable multiple style="width: 150px">
        <el-option label="P0-阻塞级" value="P0" />
        <el-option label="P1-严重级" value="P1" />
        <el-option label="P2-重要级" value="P2" />
        <el-option label="P3-一般级" value="P3" />
      </el-select>
    </el-form-item>
    
    <el-form-item label="幻觉状态">
      <el-select v-model="filters.hallucination_status" placeholder="全部" clearable style="width: 120px">
        <el-option label="正常" value="normal" />
        <el-option label="疑似" value="suspected" />
        <el-option label="确认" value="confirmed" />
      </el-select>
    </el-form-item>
    
    <el-form-item label="自动化状态">
      <el-select v-model="filters.automation_status" placeholder="全部" clearable style="width: 120px">
        <el-option label="未自动化" value="pending" />
        <el-option label="已转脚本" value="scripted" />
        <el-option label="已自动化" value="automated" />
      </el-select>
    </el-form-item>
    
    <el-form-item label="创建时间">
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        style="width: 240px"
      />
    </el-form-item>
    
    <el-form-item label="关键词">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索用例名称"
        clearable
        style="width: 200px"
      />
    </el-form-item>
    
    <el-form-item>
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { ref, computed } from 'vue'

const emit = defineEmits(['search'])

const filters = ref({
  is_finalized: null,
  priority: [],
  hallucination_status: null,
  automation_status: null,
  keyword: null
})

const dateRange = ref(null)

const handleSearch = () => {
  const params = { ...filters.value }
  
  // 处理优先级多选
  if (params.priority && params.priority.length > 0) {
    params.priority = params.priority.join(',')
  } else {
    params.priority = null
  }
  
  // 处理时间范围
  if (dateRange.value && dateRange.value.length === 2) {
    params.created_start = dateRange.value[0].toISOString()
    params.created_end = dateRange.value[1].toISOString()
  }
  
  emit('search', params)
}

const handleReset = () => {
  filters.value = {
    is_finalized: null,
    priority: [],
    hallucination_status: null,
    automation_status: null,
    keyword: null
  }
  dateRange.value = null
  handleSearch()
}
</script>

<style scoped>
.case-filters {
  padding: 16px;
  background: #f5f7fa;
  border-radius: 4px;
}
</style>
```

- [ ] **Step 3: 创建统计卡片组件**

```vue
<!-- frontend/src/components/cases/CaseStatsCard.vue -->
<template>
  <div class="stats-card">
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">总用例数</div>
            <div class="stat-value">{{ stats.total || 0 }}</div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">已定稿</div>
            <div class="stat-value success">{{ stats.finalized || 0 }}</div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">草稿</div>
            <div class="stat-value warning">{{ stats.draft || 0 }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
defineProps({
  stats: {
    type: Object,
    default: () => ({
      total: 0,
      finalized: 0,
      draft: 0
    })
  }
})
</script>

<style scoped>
.stats-card {
  margin-bottom: 16px;
}

.stat-item {
  text-align: center;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-value.success {
  color: #67c23a;
}

.stat-value.warning {
  color: #e6a23c;
}
</style>
```

- [ ] **Step 4: 创建批量操作工具栏组件**

```vue
<!-- frontend/src/components/cases/BatchOperationBar.vue -->
<template>
  <div class="batch-operation-bar" v-if="selectedCount > 0">
    <span class="selected-info">已选择 {{ selectedCount }} 项</span>
    
    <el-button-group>
      <el-button size="small" @click="emit('batch-finalize')">
        批量定稿
      </el-button>
      <el-button size="small" @click="emit('batch-unfinalize')">
        取消定稿
      </el-button>
      <el-button size="small" @click="showPriorityDialog = true">
        设置优先级
      </el-button>
      <el-button size="small" @click="showHallucinationDialog = true">
        设置幻觉状态
      </el-button>
      <el-button size="small" type="danger" @click="emit('batch-delete')">
        批量删除
      </el-button>
    </el-button-group>
    
    <!-- 优先级设置对话框 -->
    <el-dialog v-model="showPriorityDialog" title="设置优先级" width="400px">
      <el-select v-model="selectedPriority" placeholder="选择优先级" style="width: 100%">
        <el-option label="P0-阻塞级" value="P0" />
        <el-option label="P1-严重级" value="P1" />
        <el-option label="P2-重要级" value="P2" />
        <el-option label="P3-一般级" value="P3" />
      </el-select>
      
      <template #footer>
        <el-button @click="showPriorityDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSetPriority">确定</el-button>
      </template>
    </el-dialog>
    
    <!-- 幻觉状态设置对话框 -->
    <el-dialog v-model="showHallucinationDialog" title="设置幻觉状态" width="400px">
      <el-select v-model="selectedHallucination" placeholder="选择幻觉状态" style="width: 100%">
        <el-option label="正常" value="normal" />
        <el-option label="疑似" value="suspected" />
        <el-option label="确认" value="confirmed" />
      </el-select>
      
      <template #footer>
        <el-button @click="showHallucinationDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSetHallucination">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  selectedCount: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits([
  'batch-finalize',
  'batch-unfinalize',
  'batch-delete',
  'batch-set-priority',
  'batch-set-hallucination'
])

const showPriorityDialog = ref(false)
const selectedPriority = ref(null)

const showHallucinationDialog = ref(false)
const selectedHallucination = ref(null)

const handleSetPriority = () => {
  if (selectedPriority.value) {
    emit('batch-set-priority', selectedPriority.value)
    showPriorityDialog.value = false
    selectedPriority.value = null
  }
}

const handleSetHallucination = () => {
  if (selectedHallucination.value) {
    emit('batch-set-hallucination', selectedHallucination.value)
    showHallucinationDialog.value = false
    selectedHallucination.value = null
  }
}
</script>

<style scoped>
.batch-operation-bar {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  background: #ecf5ff;
  border: 1px solid #b3d8ff;
  border-radius: 4px;
  margin-bottom: 16px;
}

.selected-info {
  margin-right: 16px;
  color: #409eff;
  font-weight: 500;
}
</style>
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/cases/
git commit -m "feat: implement case management core components"
```

---

## Task 7: 前端用例列表页实现

**Files:**
- Create: `frontend/src/views/cases/CaseList.vue`

- [ ] **Step 1: 创建用例列表页（第1部分 - 模板）**

```vue
<!-- frontend/src/views/cases/CaseList.vue -->
<template>
  <div class="case-list-page">
    <!-- 统计卡片 -->
    <CaseStatsCard :stats="stats" />
    
    <!-- 筛选器 -->
    <CaseFilters @search="handleSearch" />
    
    <!-- 批量操作栏 -->
    <BatchOperationBar
      :selected-count="selectedCases.length"
      @batch-finalize="handleBatchFinalize"
      @batch-unfinalize="handleBatchUnfinalize"
      @batch-delete="handleBatchDelete"
      @batch-set-priority="handleBatchSetPriority"
      @batch-set-hallucination="handleBatchSetHallucination"
    />
    
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button type="primary" icon="Plus" @click="handleCreate">
        新建用例
      </el-button>
    </div>
    
    <!-- 用例表格 -->
    <el-table
      v-loading="loading"
      :data="caseList"
      @selection-change="handleSelectionChange"
      border
      style="width: 100%"
    >
      <el-table-column type="selection" width="55" />
      
      <el-table-column prop="name" label="用例名称" min-width="200" show-overflow-tooltip />
      
      <el-table-column prop="point_name" label="关联测试点" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.point_name">{{ row.point_name }}</span>
          <el-tag v-else type="info" size="small">未关联</el-tag>
        </template>
      </el-table-column>
      
      <el-table-column prop="priority" label="优先级" width="100">
        <template #default="{ row }">
          <el-tag :type="getPriorityType(row.priority)" size="small">
            {{ row.priority }}
          </el-tag>
        </template>
      </el-table-column>
      
      <el-table-column prop="is_finalized" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_finalized ? 'success' : 'warning'" size="small">
            {{ row.is_finalized ? '已定稿' : '草稿' }}
          </el-tag>
        </template>
      </el-table-column>
      
      <el-table-column prop="hallucination_status" label="幻觉标记" width="100">
        <template #default="{ row }">
          <el-tag
            :type="getHallucinationType(row.hallucination_status)"
            size="small"
          >
            {{ getHallucinationLabel(row.hallucination_status) }}
          </el-tag>
        </template>
      </el-table-column>
      
      <el-table-column prop="automation_status" label="自动化" width="100">
        <template #default="{ row }">
          {{ getAutomationLabel(row.automation_status) }}
        </template>
      </el-table-column>
      
      <el-table-column prop="created_by" label="创建人" width="100" />
      
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="handleEdit(row.id)">
            编辑
          </el-button>
          <el-button type="danger" link size="small" @click="handleDelete(row.id)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    
    <!-- 分页 -->
    <el-pagination
      v-model:current-page="pagination.page"
      v-model:page-size="pagination.page_size"
      :page-sizes="[10, 20, 50, 100]"
      :total="pagination.total"
      layout="total, sizes, prev, pager, next, jumper"
      @size-change="loadCases"
      @current-change="loadCases"
      style="margin-top: 16px; justify-content: flex-end"
    />
  </div>
</template>
```

- [ ] **Step 2: 创建用例列表页（第2部分 - 脚本）**

```vue
<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCases, deleteCase, batchOperation, getStats } from '@/api/test-cases'
import CaseStatsCard from '@/components/cases/CaseStatsCard.vue'
import CaseFilters from '@/components/cases/CaseFilters.vue'
import BatchOperationBar from '@/components/cases/BatchOperationBar.vue'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const caseList = ref([])
const selectedCases = ref([])
const stats = ref({})

const filters = ref({
  project_id: route.query.project_id || null
})

const pagination = ref({
  page: 1,
  page_size: 20,
  total: 0
})

// 加载用例列表
const loadCases = async () => {
  if (!filters.value.project_id) {
    ElMessage.warning('请选择项目')
    return
  }
  
  loading.value = true
  try {
    const params = {
      ...filters.value,
      page: pagination.value.page,
      page_size: pagination.value.page_size
    }
    
    const response = await listCases(params)
    
    if (response.data.code === 0) {
      const data = response.data.data
      caseList.value = data.items
      pagination.value.total = data.total
    }
  } catch (error) {
    ElMessage.error('加载用例列表失败')
  } finally {
    loading.value = false
  }
}

// 加载统计数据
const loadStats = async () => {
  if (!filters.value.project_id) return
  
  try {
    const response = await getStats(filters.value.project_id)
    if (response.data.code === 0) {
      stats.value = response.data.data
    }
  } catch (error) {
    console.error('加载统计数据失败', error)
  }
}

// 搜索
const handleSearch = (searchFilters) => {
  filters.value = {
    project_id: filters.value.project_id,
    ...searchFilters
  }
  pagination.value.page = 1
  loadCases()
}

// 选择变化
const handleSelectionChange = (selection) => {
  selectedCases.value = selection
}

// 新建用例
const handleCreate = () => {
  router.push({
    name: 'CaseDetail',
    query: { project_id: filters.value.project_id }
  })
}

// 编辑用例
const handleEdit = (caseId) => {
  router.push({
    name: 'CaseDetail',
    params: { id: caseId }
  })
}

// 删除用例
const handleDelete = async (caseId) => {
  await ElMessageBox.confirm('确认删除此用例？', '提示', {
    type: 'warning'
  })
  
  try {
    const response = await deleteCase(caseId)
    if (response.data.code === 0) {
      ElMessage.success('删除成功')
      loadCases()
      loadStats()
    }
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

// 批量定稿
const handleBatchFinalize = async () => {
  await executeBatchOperation('finalize', '批量定稿')
}

// 批量取消定稿
const handleBatchUnfinalize = async () => {
  await executeBatchOperation('unfinalize', '批量取消定稿')
}

// 批量删除
const handleBatchDelete = async () => {
  await ElMessageBox.confirm('确认删除选中的用例？', '提示', {
    type: 'warning'
  })
  
  await executeBatchOperation('delete', '批量删除')
}

// 批量设置优先级
const handleBatchSetPriority = async (priority) => {
  await executeBatchOperation('set_priority', '设置优先级', { priority })
}

// 批量设置幻觉状态
const handleBatchSetHallucination = async (hallucination_status) => {
  await executeBatchOperation('set_hallucination', '设置幻觉状态', { hallucination_status })
}

// 执行批量操作
const executeBatchOperation = async (action, actionName, params = null) => {
  const case_ids = selectedCases.value.map(c => c.id)
  
  try {
    const response = await batchOperation({
      action,
      case_ids,
      params
    })
    
    if (response.data.code === 0) {
      const result = response.data.data
      ElMessage.success(`${actionName}完成：成功 ${result.success_count} 条，失败 ${result.failed_count} 条`)
      loadCases()
      loadStats()
    }
  } catch (error) {
    ElMessage.error(`${actionName}失败`)
  }
}

// 工具函数
const getPriorityType = (priority) => {
  const typeMap = { P0: 'danger', P1: 'warning', P2: '', P3: 'info' }
  return typeMap[priority] || ''
}

const getHallucinationType = (status) => {
  const typeMap = { normal: 'success', suspected: 'warning', confirmed: 'danger' }
  return typeMap[status] || ''
}

const getHallucinationLabel = (status) => {
  const labelMap = { normal: '正常', suspected: '疑似', confirmed: '确认' }
  return labelMap[status] || status
}

const getAutomationLabel = (status) => {
  const labelMap = { pending: '未自动化', scripted: '已转脚本', automated: '已自动化' }
  return labelMap[status] || status
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(() => {
  loadCases()
  loadStats()
})
</script>
```

- [ ] **Step 3: 创建用例列表页（第3部分 - 样式）**

```vue
<style scoped>
.case-list-page {
  padding: 20px;
}

.toolbar {
  margin-bottom: 16px;
}
</style>
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/cases/CaseList.vue
git commit -m "feat: implement case list page with filters and batch operations"
```

---

## Task 8: 前端用例详情页实现

**Files:**
- Create: `frontend/src/views/cases/CaseDetail.vue`

- [ ] **Step 1: 创建用例详情页（第1部分 - 模板）**

```vue
<!-- frontend/src/views/cases/CaseDetail.vue -->
<template>
  <div class="case-detail-page">
    <el-page-header @back="handleBack" :title="pageTitle">
      <template #content>
        <span class="page-title">{{ isEdit ? '编辑用例' : '新建用例' }}</span>
      </template>
    </el-page-header>
    
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="120px"
      style="margin-top: 20px; max-width: 1200px"
    >
      <!-- 基本信息 -->
      <el-divider content-position="left">基本信息</el-divider>
      
      <el-form-item label="用例名称" prop="name">
        <el-input v-model="form.name" placeholder="请输入用例名称" style="width: 500px" />
      </el-form-item>
      
      <el-form-item label="关联测试点" prop="point_id">
        <el-select
          v-model="form.point_id"
          placeholder="选择测试点（可选）"
          clearable
          filterable
          style="width: 500px"
        >
          <el-option
            v-for="point in testPoints"
            :key="point.id"
            :label="point.name"
            :value="point.id"
          />
        </el-select>
      </el-form-item>
      
      <el-form-item label="优先级" prop="priority">
        <el-radio-group v-model="form.priority">
          <el-radio label="P0">P0-阻塞级</el-radio>
          <el-radio label="P1">P1-严重级</el-radio>
          <el-radio label="P2">P2-重要级</el-radio>
          <el-radio label="P3">P3-一般级</el-radio>
        </el-radio-group>
      </el-form-item>
      
      <el-form-item label="用例类型" prop="case_type">
        <el-select v-model="form.case_type" style="width: 200px">
          <el-option label="功能测试" value="functional" />
          <el-option label="API测试" value="api" />
        </el-select>
      </el-form-item>
      
      <el-form-item label="前置条件" prop="precondition">
        <el-input
          v-model="form.precondition"
          type="textarea"
          :rows="3"
          placeholder="请输入前置条件（可选）"
          style="width: 800px"
        />
      </el-form-item>
      
      <el-form-item label="预期结果" prop="expected_result">
        <el-input
          v-model="form.expected_result"
          placeholder="请输入预期结果"
          style="width: 800px"
        />
      </el-form-item>
      
      <!-- 测试步骤 -->
      <el-divider content-position="left">测试步骤</el-divider>
      
      <el-form-item label="" prop="steps">
        <StepEditor v-model="form.steps" />
      </el-form-item>
      
      <!-- 状态信息（编辑模式） -->
      <template v-if="isEdit">
        <el-divider content-position="left">状态信息</el-divider>
        
        <el-form-item label="定稿状态">
          <el-switch
            v-model="form.is_finalized"
            active-text="已定稿"
            inactive-text="草稿"
          />
        </el-form-item>
        
        <el-form-item label="幻觉状态">
          <el-select v-model="form.hallucination_status" style="width: 200px">
            <el-option label="正常" value="normal" />
            <el-option label="疑似" value="suspected" />
            <el-option label="确认" value="confirmed" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="自动化状态">
          <el-select v-model="form.automation_status" style="width: 200px">
            <el-option label="未自动化" value="pending" />
            <el-option label="已转脚本" value="scripted" />
            <el-option label="已自动化" value="automated" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="版本">
          <span>v{{ caseDetail?.version || 1 }}</span>
        </el-form-item>
        
        <el-form-item label="创建人">
          <span>{{ caseDetail?.created_by || '-' }}</span>
        </el-form-item>
        
        <el-form-item label="创建时间">
          <span>{{ formatDate(caseDetail?.created_at) }}</span>
        </el-form-item>
      </template>
      
      <!-- 操作按钮 -->
      <el-form-item>
        <el-button type="primary" @click="handleSave" :loading="saving">
          保存
        </el-button>
        <el-button @click="handleBack">取消</el-button>
        <el-button v-if="isEdit && !form.is_finalized" type="success" @click="handleFinalize">
          一键定稿
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>
```

- [ ] **Step 2: 创建用例详情页（第2部分 - 脚本）**

```vue
<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getCase, createCase, updateCase } from '@/api/test-cases'
import StepEditor from '@/components/cases/StepEditor.vue'

const router = useRouter()
const route = useRoute()

const formRef = ref(null)
const saving = ref(false)
const caseDetail = ref(null)
const testPoints = ref([]) // TODO: 从API加载测试点列表

const isEdit = computed(() => !!route.params.id)
const pageTitle = computed(() => isEdit.value ? '编辑用例' : '新建用例')

const form = reactive({
  project_id: route.query.project_id || null,
  name: '',
  point_id: null,
  priority: 'P1',
  case_type: 'functional',
  precondition: '',
  expected_result: '',
  steps: [
    { seq: 1, action: '', target: '', data: '', expected: '' }
  ],
  is_finalized: false,
  hallucination_status: 'normal',
  automation_status: 'pending'
})

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
      validator: (rule, value, callback) => {
        if (!value || value.length === 0) {
          callback(new Error('至少添加一个测试步骤'))
        } else {
          const hasEmptyAction = value.some(step => !step.action || !step.target)
          if (hasEmptyAction) {
            callback(new Error('步骤的操作和目标元素不能为空'))
          } else {
            callback()
          }
        }
      },
      trigger: 'change'
    }
  ]
}

// 加载用例详情
const loadCaseDetail = async () => {
  if (!isEdit.value) return
  
  try {
    const response = await getCase(route.params.id)
    if (response.data.code === 0) {
      caseDetail.value = response.data.data
      
      // 填充表单
      Object.assign(form, {
        project_id: caseDetail.value.project_id,
        name: caseDetail.value.name,
        point_id: caseDetail.value.point_id,
        priority: caseDetail.value.priority,
        case_type: caseDetail.value.case_type,
        precondition: caseDetail.value.precondition,
        expected_result: caseDetail.value.expected_result,
        steps: caseDetail.value.steps || [],
        is_finalized: caseDetail.value.is_finalized,
        hallucination_status: caseDetail.value.hallucination_status,
        automation_status: caseDetail.value.automation_status
      })
    }
  } catch (error) {
    ElMessage.error('加载用例详情失败')
  }
}

// 保存
const handleSave = async () => {
  await formRef.value.validate()
  
  saving.value = true
  
  try {
    const data = { ...form }
    
    let response
    if (isEdit.value) {
      response = await updateCase(route.params.id, data)
    } else {
      response = await createCase(data)
    }
    
    if (response.data.code === 0) {
      ElMessage.success(isEdit.value ? '更新成功' : '创建成功')
      handleBack()
    }
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

// 一键定稿
const handleFinalize = async () => {
  form.is_finalized = true
  await handleSave()
}

// 返回
const handleBack = () => {
  router.push({
    name: 'CaseList',
    query: { project_id: form.project_id }
  })
}

// 工具函数
const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(() => {
  loadCaseDetail()
  // TODO: 加载测试点列表
})
</script>
```

- [ ] **Step 3: 创建用例详情页（第3部分 - 样式）**

```vue
<style scoped>
.case-detail-page {
  padding: 20px;
}

.page-title {
  font-size: 18px;
  font-weight: 500;
}
</style>
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/cases/CaseDetail.vue
git commit -m "feat: implement case detail page with step editor"
```

---

## Task 9: 前端路由和导航配置

**Files:**
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1: 添加路由配置**

```javascript
// frontend/src/router/index.js
// 在路由配置中添加

{
  path: '/cases',
  name: 'CaseList',
  component: () => import('@/views/cases/CaseList.vue'),
  meta: { title: '用例管理' }
},
{
  path: '/cases/new',
  name: 'CaseNew',
  component: () => import('@/views/cases/CaseDetail.vue'),
  meta: { title: '新建用例' }
},
{
  path: '/cases/:id',
  name: 'CaseDetail',
  component: () => import('@/views/cases/CaseDetail.vue'),
  meta: { title: '用例详情' }
}
```

- [ ] **Step 2: 添加导航菜单**

```vue
<!-- frontend/src/layouts/MainLayout.vue -->
<!-- 在侧边栏菜单中添加 -->

<el-menu-item index="/cases">
  <el-icon><Document /></el-icon>
  <span>用例管理</span>
</el-menu-item>
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/router/index.js frontend/src/layouts/MainLayout.vue
git commit -m "feat: add routes and navigation for case management"
```

---

## 规格覆盖验证

**✅ 数据模型**: Task 1 - Schema 定义完成，复用现有表  
**✅ 服务层**: Task 2 - 完整的 CRUD + 筛选 + 批量操作  
**✅ API 端点**: Task 3 - 7个 RESTful 端点  
**✅ 后端测试**: Task 4 - 单元测试 + API 测试  
**✅ 前端组件**: Task 6 - 4个核心组件  
**✅ 列表页**: Task 7 - 筛选 + 分页 + 批量操作  
**✅ 详情页**: Task 8 - 表单 + 步骤编辑器  
**✅ 路由配置**: Task 9 - 路由和导航  

所有规格要求已覆盖！

