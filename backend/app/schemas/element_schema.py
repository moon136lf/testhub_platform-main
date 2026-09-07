"""
Element schemas for request/response validation

元素库模块的 Pydantic 数据模型，覆盖元素抓取、入库、查询等接口的请求与响应校验。

类型说明:
- ORM 模型 (app/models/element.py) 中的主键与外键使用 UUID 类型，时间字段使用
  带时区的 datetime。为方便 `from_attributes` 直接从 ORM 对象映射，响应模型中
  对应字段统一声明为 ``StrField``（经 BeforeValidator 将 UUID/datetime 自动转为
  字符串），既兼容 ``to_dict()`` 输出的字符串，也兼容直接传入 ORM 对象。
- ``locator_strategies`` 与模型保持一致，使用 JSONB 存储，结构为
  ``{"strategies": [LocatorStrategy, ...]}``。
"""

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _coerce_to_str(value: Any) -> Any:
    """将 UUID / datetime 等非字符串标量转为字符串，便于响应模型直接接收 ORM 字段。"""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# 可自动转换 UUID/datetime 为字符串的字段类型，用于响应模型中映射自 ORM 的字段。
StrField = Annotated[str, BeforeValidator(_coerce_to_str)]


class SubPageCreateRequest(BaseModel):
    """创建子页面请求（parent_id=None 即根级）"""
    project_id: str
    parent_id: Optional[str] = None
    page_name: str = Field(..., min_length=1, max_length=100)
    page_url: Optional[str] = None


class PageRenameRequest(BaseModel):
    """页面重命名请求"""
    page_name: str = Field(..., min_length=1, max_length=100)


class PageMoveRequest(BaseModel):
    """页面上移/下移请求"""
    direction: str = Field(..., pattern="^(up|down)$")


class LocatorStrategy(BaseModel):
    """单个定位器策略"""

    type: str = Field(
        ...,
        description="定位器类型：id/data-testid/name/role-text/text/css/xpath 等",
    )
    value: str = Field(..., description="定位器值")
    priority: Optional[int] = Field(
        None, ge=1, le=10,
        description="优先级 1-10（可选；抓取产物不含此字段，排序按 score）",
    )
    score: int = Field(..., ge=0, le=150, description="质量评分 0-150")
    unique: bool = Field(..., description="是否唯一定位")
    verified: bool = Field(True, description="是否已验证")

    model_config = ConfigDict(from_attributes=True)


class SemanticInfo(BaseModel):
    """元素语义信息（用于自愈兜底）"""

    type: str = Field(..., description="元素类型")
    text: Optional[str] = Field(None, description="元素文本")
    placeholder: Optional[str] = Field(None, description="placeholder 属性")
    aria_label: Optional[str] = Field(None, description="aria-label 属性")
    aria_role: Optional[str] = Field(None, description="role 属性")
    coords: Dict[str, int] = Field(..., description="坐标 {x, y, width, height}")
    context: Dict[str, Any] = Field(..., description="上下文信息")

    model_config = ConfigDict(from_attributes=True)


class ElementFetchRequest(BaseModel):
    """元素抓取请求"""

    project_id: str = Field(..., description="项目 ID")
    url: str = Field(..., description="目标 URL")
    username: Optional[str] = Field(None, description="登录用户名（可选）")
    password: Optional[str] = Field(None, description="登录密码（可选）")
    text_filter: Optional[str] = Field(None, description="文本过滤，逗号分隔，任一词命中 element_text 保留")
    type_filter: Optional[str] = Field(None, description="类型过滤，逗号分隔白名单，如 button,input")
    debug_mode: bool = Field(False, description="调试模式：不过滤，返回全部元素")
    include_text: bool = Field(False, description="抓取文字/不可点击元素")


class ElementFetchResponse(BaseModel):
    """元素抓取响应"""

    session_id: str = Field(..., description="会话 ID（用于 SSE 连接）")
    sse_url: str = Field(..., description="SSE 连接 URL")


class ElementData(BaseModel):
    """抓取到的元素数据"""

    temp_id: str = Field(..., description="临时 ID")
    element_type: str = Field(..., description="元素类型")
    element_text: Optional[str] = Field(None, description="元素文本")
    locator_strategies: Dict[str, List[LocatorStrategy]] = Field(
        ..., description="定位策略列表，结构为 {'strategies': [LocatorStrategy, ...]}"
    )
    semantic_info: SemanticInfo = Field(..., description="语义信息")
    position_x: Optional[int] = Field(None, description="X 坐标")
    position_y: Optional[int] = Field(None, description="Y 坐标")
    width: Optional[int] = Field(None, description="宽度")
    height: Optional[int] = Field(None, description="高度")
    attributes: Optional[Dict[str, Any]] = Field(None, description="HTML 属性")


class ElementImportRequest(BaseModel):
    """元素入库请求"""

    project_id: str = Field(..., description="项目 ID")
    page_id: Optional[str] = Field(
        None, description="已有页面 ID（与 page_name 二选一）"
    )
    page_name: Optional[str] = Field(None, description="新建页面名称")
    page_url: Optional[str] = Field(None, description="新建页面 URL")
    screenshot_url: Optional[str] = Field(None, description="页面截图 URL")
    selected_element_ids: List[str] = Field(
        ..., description="用户勾选的元素临时 ID 列表"
    )
    elements_data: List[ElementData] = Field(..., description="完整元素数据")


class ElementImportResponse(BaseModel):
    """元素入库响应"""

    page_id: str = Field(..., description="页面 ID")
    page_name: str = Field(..., description="页面名称")
    imported_count: int = Field(..., description="导入成功的元素数量")
    failed_count: int = Field(0, description="导入失败的元素数量")


class PageResponse(BaseModel):
    """页面响应"""

    id: StrField
    project_id: StrField
    page_name: str
    page_url: str
    screenshot_url: Optional[str] = None
    parent_id: Optional[StrField] = None
    children: Optional[List[Dict[str, Any]]] = None
    element_count: int
    last_fetch_at: Optional[StrField] = None
    created_at: StrField
    updated_at: StrField

    model_config = ConfigDict(from_attributes=True)


class ElementResponse(BaseModel):
    """元素响应"""

    id: StrField
    page_id: StrField
    project_id: StrField
    element_id: str
    element_name: Optional[str] = None
    element_type: str
    element_text: Optional[str] = None
    locator_strategies: Dict[str, List[LocatorStrategy]]
    semantic_info: Optional[SemanticInfo] = None
    position_x: Optional[int] = None
    position_y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    status: str
    confidence: int
    source: str
    created_at: StrField
    updated_at: StrField

    model_config = ConfigDict(from_attributes=True)


class FetchHistoryResponse(BaseModel):
    """抓取历史响应"""

    id: StrField
    page_id: StrField
    fetch_time: StrField
    elements_found: int
    elements_imported: int
    screenshot_url: Optional[str] = None
    fetch_url: str
    used_login: bool
    status: str
    duration_seconds: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------- P3 会话式抓取工作台 ----------------


class CaptureSessionCreateRequest(BaseModel):
    """创建抓取会话"""

    project_id: str = Field(..., description="项目 ID")


class CaptureSessionCreateResponse(BaseModel):
    """创建抓取会话响应"""

    session_id: str = Field(..., description="会话 ID（后续抓取/操作/入库都用它）")
    project_id: str = Field(..., description="项目 ID")


class CaptureBatchAddRequest(BaseModel):
    """向会话追加一个抓取批次（一次页面抓取的结果）"""

    url: str = Field(..., description="抓取的页面 URL")
    screenshot_url: Optional[str] = Field(None, description="页面截图 URL")
    elements: List[ElementData] = Field(..., description="本批次抓到的元素")


class CaptureBatchAddResponse(BaseModel):
    """追加批次响应"""

    batch_idx: int = Field(..., description="批次索引（从 0 起）")
    batch_count: int = Field(..., description="会话累计批次数")
    added: int = Field(..., description="本批次新增元素数")
    total_elements: int = Field(..., description="会话累计元素总数")


class CaptureElementOpRequest(BaseModel):
    """单元素操作（勾选/取消勾选）"""

    temp_id: str = Field(..., description="元素临时 ID")
    included: bool = Field(..., description="是否纳入入库")


class CaptureAllOpRequest(BaseModel):
    """全选/全不选"""

    included: bool = Field(..., description="true=全选 false=全不选")


class CaptureElementDeleteRequest(BaseModel):
    """删除单个元素"""

    temp_id: str = Field(..., description="元素临时 ID")


class CaptureBatchDeleteRequest(BaseModel):
    """删除整个批次"""

    batch_idx: int = Field(..., ge=0, description="批次索引")


class CaptureStateResponse(BaseModel):
    """会话状态（抓取工作台全量渲染数据）"""

    session_id: str = Field(..., description="会话 ID")
    project_id: str = Field(..., description="项目 ID")
    created_at: Optional[str] = Field(None, description="创建时间")
    batches: List[Dict[str, Any]] = Field(default_factory=list, description="批次列表")
    elements: List[Dict[str, Any]] = Field(
        default_factory=list, description="元素列表（含 included/batch_idx）"
    )
    total_elements: int = Field(0, description="元素总数")
    included_count: int = Field(0, description="已勾选元素数")


class CaptureImportRequest(BaseModel):
    """会话式入库请求（按会话内勾选状态入库）"""

    project_id: str = Field(..., description="项目 ID")
    session_id: str = Field(..., description="会话 ID")
    page_id: Optional[str] = Field(None, description="已有页面 ID（与 page_name 二选一）")
    page_name: Optional[str] = Field(None, description="新建页面名称")
    page_url: Optional[str] = Field(None, description="新建页面 URL")
    screenshot_url: Optional[str] = Field(
        None, description="页面截图 URL（缺省取最后批次的截图）"
    )


class CaptureImportResponse(BaseModel):
    """会话式入库响应"""

    page_id: str = Field(..., description="页面 ID")
    page_name: str = Field(..., description="页面名称")
    imported_count: int = Field(..., description="导入成功的元素数量")
    failed_count: int = Field(0, description="导入失败的元素数量")
    session_total: int = Field(0, description="会话剩余元素总数")


# ---------------- P3.5 会话浏览器（headed 人工登录 + 点选补抓） ----------------


class BrowserOpenRequest(BaseModel):
    """打开会话浏览器（headed 人工登录或 headless 直接抓取）"""

    project_id: str = Field(..., description="项目 ID")
    url: str = Field(..., description="起始 URL")
    need_login: bool = Field(False, description="是否需要人工登录（headed 模式）")


class BrowserPickRequest(BaseModel):
    """点选补抓坐标"""

    x: float = Field(..., description="页面坐标 x")
    y: float = Field(..., description="页面坐标 y")


# ---------------- 元素资产管理（阶段1） ----------------


class ElementUpdateRequest(BaseModel):
    """元素编辑（白名单字段在 service 校验）"""

    element_name: Optional[str] = Field(None, min_length=1, max_length=100)
    element_type: Optional[str] = Field(None, max_length=50)
    element_text: Optional[str] = Field(None, max_length=200)


class LocatorReorderRequest(BaseModel):
    index: int = Field(..., ge=0, description="被移动的定位器下标")
    direction: str = Field(..., pattern="^(up|down)$")


class LocatorAddRequest(BaseModel):
    type: str = Field(..., max_length=30, description="id/css/data-testid/text/xpath/自定义")
    value: str = Field(..., min_length=1, max_length=500)
    score: int = Field(50, ge=0, le=150)


class ElementCreateRequest(BaseModel):
    """新建元素（手工录入，支持全局作用域）"""

    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    element_type: str = Field("other", max_length=50)
    element_text: Optional[str] = Field(None, max_length=200)
    scope: str = Field("page", pattern="^(page|global)$")
    page_id: Optional[str] = None
    locators: Optional[List[dict]] = None


class LocatorVerifyRequest(BaseModel):
    locator_type: str = Field(..., max_length=30)
    locator_value: str = Field(..., min_length=1, max_length=500)
    score: Optional[int] = Field(None, ge=0, le=150)
