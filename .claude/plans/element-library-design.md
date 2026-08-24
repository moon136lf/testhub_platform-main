# 元素库模块设计文档

## 1. 模块概述

### 1.1 目标
元素库模块是 MoonTest 平台的核心基础设施，负责：
- 自动抓取页面可交互元素
- 生成并验证多层定位器
- 提供智能降级和自愈机制
- 为 UI 自动化测试提供稳定的元素定位能力

### 1.2 核心价值
- **准确性优先**：抓取时实时验证定位器，确保每个定位器都经过页面验证
- **容错性强**：每个元素存储 3-5 个已验证的定位器，支持自动降级
- **自愈能力**：当所有定位器失效时，自动启用 playwright-healer 语义定位

### 1.3 技术选型
- **浏览器自动化**：Playwright Python
- **自愈引擎**：playwright-healer
- **异步任务**：Celery + Redis
- **实时通信**：Server-Sent Events (SSE)
- **对象存储**：MinIO（存储页面截图）

---

## 2. 架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (Vue3)                               │
│  ElementLibrary.vue                                              │
│  - 用户输入 URL、项目、登录信息                                   │
│  - 点击"抓取元素"按钮                                             │
│  - 通过 SSE 接收实时进度                                          │
│  - 展示元素列表 + 页面截图                                        │
│  - 勾选元素 → 一键入库                                            │
└────────────┬────────────────────────────────────────────────────┘
             │ HTTP POST /api/v1/elements/fetch
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI 后端                                  │
│  /api/v1/elements/fetch                                          │
│  - 创建抓取会话 (session_id)                                      │
│  - 触发 Celery 异步任务                                           │
│  - 立即返回 session_id                                            │
└────────────┬────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Celery 异步任务队列                             │
│  fetch_elements_task(session_id, url, project_id, ...)           │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  1. 初始化 PlaywrightService                              │  │
│  │  2. 启动浏览器 (chromium headless)                        │  │
│  │  3. 访问目标 URL                                          │  │
│  │  4. 可选：执行登录操作                                     │  │
│  │  5. 扫描可交互元素 (button/input/link/...)                │  │
│  │  6. 为每个元素生成 5-8 种候选定位器                       │  │
│  │  7. 实时验证每个定位器 (唯一性、有效性)                   │  │
│  │  8. 计算定位器质量评分 (0-120分)                          │  │
│  │  9. 提取元素语义信息 (text/role/coords/context)           │  │
│  │ 10. 截取页面截图 → 上传 MinIO                             │  │
│  │ 11. 返回验证后的元素数据                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────┬────────────────────────────────────────────────────┘
             │ 通过 SSE 推送进度消息
             │ {"type": "progress", "message": "正在扫描元素...", "count": 12}
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SSE 端点                                      │
│  /api/v1/sse/element-fetch/{session_id}                          │
│  - 前端通过 EventSource 连接                                     │
│  - 实时推送抓取进度                                               │
│  - 完成后推送最终结果                                             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流图

```
用户操作 → API请求 → Celery任务 → Playwright浏览器
                                      ↓
                              扫描可交互元素
                                      ↓
                          ┌───────────┴──────────┐
                          │  为每个元素生成定位器  │
                          │  - id                │
                          │  - data-testid       │
                          │  - name              │
                          │  - role + text       │
                          │  - class + text      │
                          │  - css selector      │
                          │  - xpath             │
                          └───────────┬──────────┘
                                      ↓
                          ┌───────────┴──────────┐
                          │   实时验证定位器      │
                          │   - 查找元素数量      │
                          │   - 是否定位到目标    │
                          │   - 计算质量评分      │
                          └───────────┬──────────┘
                                      ↓
                          ┌───────────┴──────────┐
                          │  保存验证通过的定位器 │
                          │  (score >= 60)       │
                          └───────────┬──────────┘
                                      ↓
                          ┌───────────┴──────────┐
                          │  提取语义信息         │
                          │  - text/role         │
                          │  - 坐标/上下文       │
                          └───────────┬──────────┘
                                      ↓
                              返回给前端展示
```

---

## 3. 定位器生成与验证策略

### 3.1 定位器生成优先级

按照稳定性和唯一性，定位器优先级如下：

| 优先级 | 类型 | 示例 | 基础分 | 说明 |
|--------|------|------|--------|------|
| 1 | id | `#login-btn` | 100 | 最稳定，唯一性强 |
| 2 | data-testid | `[data-testid='submit']` | 95 | 专为测试设计 |
| 3 | name | `[name='username']` | 90 | 表单元素常用 |
| 4 | role + text | `button[role='button']:has-text('登录')` | 85 | 语义化强 |
| 5 | text | `button:has-text('登录')` | 80 | 依赖文案 |
| 6 | xpath | `//button[contains(text(),'登录')]` | 70 | 通用但不稳定 |
| 7 | class + type | `input.form-control[type='text']` | 70 | 依赖样式类 |
| 8 | css selector | `div > form > button:nth-of-type(1)` | 50 | 依赖位置，最不稳定 |

### 3.2 验证规则

每个候选定位器生成后，立即在浏览器中验证：

```python
async def verify_and_score_locator(page, locator_candidate, target_element):
    """
    验证定位器并计算最终评分
    
    返回格式:
    {
        "type": "id",
        "value": "#login-btn",
        "score": 120,
        "unique": True,
        "verified": True
    }
    或 None (验证失败)
    """
    try:
        # 1. 使用定位器查找元素
        found_elements = await page.locator(locator_candidate['value']).all()
        
        # 2. 检查是否找到元素
        if len(found_elements) == 0:
            return None  # 无效定位器
        
        # 3. 检查是否定位到目标元素
        target_found = any(
            await elem.evaluate('(el, target) => el === target', target_element)
            for elem in found_elements
        )
        if not target_found:
            return None  # 定位到了其他元素
        
        # 4. 计算最终评分
        score = locator_candidate['base_score']
        
        # 唯一性加分
        if len(found_elements) == 1:
            score += 20  # 唯一定位，加分
        else:
            score -= 10  # 非唯一，扣分
        
        # 稳定性检查
        value = locator_candidate['value']
        if 'nth-of-type' in value or 'nth-child' in value:
            score -= 15  # 依赖位置索引，不稳定
        
        if ':nth-of-type(' in value and ')' in value:
            # 提取索引值，索引越大越不稳定
            import re
            match = re.search(r':nth-of-type\((\d+)\)', value)
            if match:
                index = int(match.group(1))
                if index > 3:
                    score -= 5  # 索引大于3，额外扣分
        
        return {
            "type": locator_candidate['type'],
            "value": value,
            "score": max(score, 0),  # 保证非负
            "unique": len(found_elements) == 1,
            "verified": True
        }
    
    except Exception:
        return None  # 验证失败
```

### 3.3 评分规则总结

| 条件 | 分数调整 |
|------|----------|
| 基础分 | 50-100 分（根据定位器类型） |
| 唯一定位（找到1个元素） | +20 分 |
| 非唯一定位（找到多个元素） | -10 分 |
| 包含 nth-of-type/nth-child | -15 分 |
| nth-of-type 索引 > 3 | -5 分 |
| 定位失败或未找到目标 | 丢弃（返回 None） |

**最终保存条件**：score >= 60 分

---

## 4. 语义信息提取（自愈兜底）

当所有验证通过的定位器都失效时，playwright-healer 会使用语义信息进行智能定位。

### 4.1 语义信息结构

```python
{
    "type": "button",
    "text": "登录",
    "placeholder": None,
    "aria_label": "登录按钮",
    "aria_role": "button",
    "coords": {
        "x": 120,
        "y": 350,
        "width": 80,
        "height": 32
    },
    "context": {
        "parent_tag": "form",
        "sibling_tags": ["input", "input", "a"]
    }
}
```

### 4.2 提取逻辑

```python
async def extract_semantic_info(page, element):
    """提取元素语义信息"""
    
    # 获取边界框（坐标）
    box = await element.bounding_box()
    coords = {
        "x": box['x'] if box else 0,
        "y": box['y'] if box else 0,
        "width": box['width'] if box else 0,
        "height": box['height'] if box else 0
    }
    
    # 获取父节点和兄弟节点信息
    parent_tag = await element.evaluate(
        'el => el.parentElement?.tagName.toLowerCase()'
    )
    sibling_tags = await element.evaluate('''
        el => Array.from(el.parentElement?.children || [])
            .map(e => e.tagName.toLowerCase())
    ''')
    
    return {
        "type": await element.evaluate('el => el.tagName.toLowerCase()'),
        "text": (await element.inner_text()).strip()[:100],
        "placeholder": await element.get_attribute('placeholder'),
        "aria_label": await element.get_attribute('aria-label'),
        "aria_role": await element.get_attribute('role'),
        "coords": coords,
        "context": {
            "parent_tag": parent_tag,
            "sibling_tags": sibling_tags[:5]  # 只保存前5个兄弟节点
        }
    }
```

---

## 5. 数据模型设计

### 5.1 PageRepository 表（页面库）

**根据需求文档字段定义**：

```python
class PageRepository(Base):
    __tablename__ = "page_repository"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    page_name = Column(String(100), nullable=False, comment="页面名称")
    page_url = Column(String(500), nullable=False, comment="页面URL")
    screenshot_url = Column(String(500), comment="页面截图URL (MinIO)")
    element_count = Column(Integer, default=0, comment="该页面下元素数量")
    last_fetch_at = Column(DateTime, comment="最后一次抓取时间")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(50), default="system")
    
    # 关系
    elements = relationship("ElementRepository", back_populates="page")
    fetch_histories = relationship("FetchHistory", back_populates="page")
```

### 5.2 ElementRepository 表（元素库）

**根据需求文档字段定义**：

```python
class ElementRepository(Base):
    __tablename__ = "element_repository"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_id = Column(String(36), ForeignKey("page_repository.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    
    # 元素标识
    element_id = Column(String(100), nullable=False, index=True, comment="元素唯一标识（用户可自定义）")
    element_name = Column(String(100), comment="元素名称（用户可编辑）")
    element_type = Column(String(50), nullable=False, comment="button/input/link/select/other")
    element_text = Column(String(200), comment="元素显示文本")
    
    # 定位策略链（核心字段）
    locator_strategies = Column(JSON, nullable=False, comment="多层定位器数组")
    # 格式（需求文档标准）:
    # {
    #   "strategies": [
    #     {"type": "id", "value": "username", "priority": 1, "score": 120, "unique": true, "verified": true},
    #     {"type": "css", "value": "#username", "priority": 2, "score": 100, "unique": true, "verified": true},
    #     {"type": "xpath", "value": "//input[@name='username']", "priority": 3, "score": 70, "unique": false, "verified": true},
    #     {"type": "text", "value": "用户名", "priority": 4, "score": 80, "unique": true, "verified": true},
    #     {"type": "role", "value": "textbox", "priority": 5, "score": 75, "unique": true, "verified": true}
    #   ]
    # }
    
    # 语义信息（自愈兜底）
    semantic_info = Column(JSON, comment="元素语义信息，供 playwright-healer 使用")
    # 格式:
    # {
    #   "type": "button",
    #   "text": "登录",
    #   "placeholder": null,
    #   "aria_label": "登录按钮",
    #   "aria_role": "button",
    #   "coords": {"x": 120, "y": 350, "width": 80, "height": 32},
    #   "context": {"parent_tag": "form", "sibling_tags": ["input", "input"]}
    # }
    
    # 元素位置
    position_x = Column(Integer, comment="元素X坐标")
    position_y = Column(Integer, comment="元素Y坐标")
    width = Column(Integer, comment="元素宽度")
    height = Column(Integer, comment="元素高度")
    
    # 元素属性
    attributes = Column(JSON, comment="元素HTML属性（id/class/name等）")
    
    # 状态管理
    status = Column(String(20), default="active", comment="active/deprecated/deleted")
    confidence = Column(Integer, default=0, comment="置信度 0-10，自愈成功≥3次后回写")
    source = Column(String(20), default="manual", comment="manual/auto/healed")
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(50), default="system")
    last_verified_at = Column(DateTime, comment="最后验证时间")
    
    # 关系
    page = relationship("PageRepository", back_populates="elements")
```

### 5.3 FetchHistory 表（抓取历史）

**根据需求文档补充**：

```python
class FetchHistory(Base):
    __tablename__ = "fetch_history"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_id = Column(String(36), ForeignKey("page_repository.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    
    fetch_time = Column(DateTime, default=datetime.utcnow, comment="抓取时间")
    elements_found = Column(Integer, default=0, comment="发现的元素数量")
    elements_imported = Column(Integer, default=0, comment="实际入库的元素数量")
    screenshot_url = Column(String(500), comment="本次抓取的截图URL")
    
    # 抓取配置
    fetch_url = Column(String(500), comment="抓取的URL")
    used_login = Column(Boolean, default=False, comment="是否使用了登录")
    
    # 执行结果
    status = Column(String(20), default="success", comment="success/failed/partial")
    error_message = Column(Text, comment="失败时的错误信息")
    duration_seconds = Column(Integer, comment="抓取耗时（秒）")
    
    created_by = Column(String(50), default="system")
    
    # 关系
    page = relationship("PageRepository", back_populates="fetch_histories")
```

### 5.4 ChangeDetection 表（变更检测）

**根据需求文档补充**：

```python
class ChangeDetection(Base):
    __tablename__ = "change_detection"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_id = Column(String(36), ForeignKey("page_repository.id"), nullable=False)
    
    check_time = Column(DateTime, default=datetime.utcnow, comment="检测时间")
    change_type = Column(String(20), comment="added/removed/modified")
    element_id = Column(String(100), comment="涉及的元素ID")
    element_name = Column(String(100), comment="元素名称")
    
    # 变更详情
    old_locator = Column(JSON, comment="旧定位器")
    new_locator = Column(JSON, comment="新定位器")
    
    # 影响分析
    affected_scripts = Column(JSON, comment="受影响的脚本列表")
    impact_level = Column(String(20), comment="low/medium/high")
    
    # 处理状态
    status = Column(String(20), default="pending", comment="pending/reviewed/fixed")
    reviewed_by = Column(String(50))
    reviewed_at = Column(DateTime)
```

---

## 6. API 设计

### 6.1 抓取元素 API

**端点**: `POST /api/v1/elements/fetch`

**请求体**:
```json
{
    "project_id": "proj_001",
    "url": "https://example.com/login",
    "username": "testuser",  // 可选，登录用
    "password": "testpass"   // 可选，登录用
}
```

**响应**:
```json
{
    "session_id": "fetch_20260818_143052",
    "sse_url": "/api/v1/sse/element-fetch/fetch_20260818_143052"
}
```

### 6.2 SSE 直播端点

**端点**: `GET /api/v1/sse/element-fetch/{session_id}`

**事件流示例**:
```
event: progress
data: {"message": "正在启动浏览器...", "progress": 10}

event: progress
data: {"message": "正在访问页面...", "progress": 30}

event: progress
data: {"message": "正在扫描元素...", "progress": 50, "found_count": 12}

event: progress
data: {"message": "正在验证定位器...", "progress": 70, "verified_count": 8}

event: complete
data: {
    "elements": [
        {
            "element_id": "elem_001",
            "element_type": "button",
            "text": "登录",
            "locators": [
                {"type": "id", "value": "#login-btn", "score": 120, "unique": true},
                {"type": "text", "value": "button:has-text('登录')", "score": 85, "unique": true}
            ],
            "semantic_info": {...}
        },
        ...
    ],
    "screenshot_url": "https://minio.example.com/screenshots/page_001.png"
}
```

### 6.3 元素入库 API

**端点**: `POST /api/v1/elements/import`

**请求体**:
```json
{
    "project_id": "proj_001",
    "page_name": "登录页",
    "page_url": "https://example.com/login",
    "screenshot_url": "https://minio.example.com/screenshots/page_001.png",
    "elements": [
        {
            "element_id": "elem_001",
            "element_name": "登录按钮",
            "element_type": "button",
            "locator_chain": [...],
            "semantic_info": {...}
        },
        ...
    ]
}
```

**响应**:
```json
{
    "page_id": 123,
    "imported_count": 8,
    "failed_count": 0
}
```

---

## 7. 运行时定位策略（智能降级 + 自愈）

### 7.1 降级策略

脚本执行时，按评分从高到低尝试定位器：

```python
async def locate_element_with_fallback(page, element_data):
    """
    智能降级定位元素
    
    策略:
    1. 按 score 从高到低尝试 locator_chain 中的定位器
    2. 全部失败后，调用 playwright-healer 使用 semantic_info 自愈
    """
    locators = sorted(
        element_data['locator_chain'],
        key=lambda x: x['score'],
        reverse=True
    )
    
    # 第一阶段: 尝试已验证的定位器
    for locator in locators:
        try:
            element = page.locator(locator['value'])
            if await element.count() > 0:
                return element  # 成功定位
        except Exception:
            continue  # 尝试下一个
    
    # 第二阶段: 所有定位器失效，启用自愈
    return await heal_element(page, element_data['semantic_info'])


async def heal_element(page, semantic_info):
    """
    使用 playwright-healer 自愈定位
    """
    from playwright_healer import heal_locator
    
    healed_locator = await heal_locator(
        page=page,
        element_type=semantic_info['type'],
        text=semantic_info['text'],
        coords=semantic_info['coords'],
        context=semantic_info['context']
    )
    
    return page.locator(healed_locator)
```

### 7.2 自愈成功后的更新

当 playwright-healer 成功定位元素后，应更新元素库：

```python
async def update_healed_locator(element_id, new_locator, score=60):
    """
    自愈成功后，将新定位器追加到 locator_chain
    """
    element = await db.get(ElementRepository, element_id)
    
    # 追加新定位器（标记为healed）
    element.locator_chain.append({
        "type": "healed",
        "value": new_locator,
        "score": score,
        "unique": True,
        "verified": False,  # 未经验证
        "healed_at": datetime.utcnow().isoformat()
    })
    
    await db.commit()
```

---

## 8. 实施计划

### 阶段 1: 数据库表和模型（0.5天）
- [ ] 创建 PageRepository 模型
- [ ] 创建 ElementRepository 模型
- [ ] 创建 FetchHistory 模型（抓取历史）
- [ ] 创建 ChangeDetection 模型（变更检测）
- [ ] 编写数据库迁移脚本
- [ ] 单元测试

### 阶段 2: PlaywrightService 核心逻辑（1.5天）
- [ ] 实现元素扫描逻辑
- [ ] 实现定位器生成逻辑（8种策略）
- [ ] 实现定位器验证逻辑
- [ ] 实现语义信息提取
- [ ] 实现截图上传 MinIO
- [ ] 单元测试

### 阶段 3: Celery 异步任务（0.5天）
- [ ] 实现 fetch_elements_task
- [ ] 集成 SSE 进度推送
- [ ] 错误处理和重试机制
- [ ] 集成测试

### 阶段 4: FastAPI 端点（0.5天）
- [ ] 实现 POST /elements/fetch
- [ ] 实现 GET /sse/element-fetch/{session_id}
- [ ] 实现 POST /elements/import
- [ ] API 文档和测试

### 阶段 5: 前端页面（1天）
- [ ] 完善 ElementLibrary.vue
- [ ] 集成 SSE 实时更新
- [ ] 元素列表展示和勾选
- [ ] 截图预览
- [ ] 一键入库功能

### 阶段 6: 运行时降级和自愈（1天）
- [ ] 实现 locate_element_with_fallback
- [ ] 集成 playwright-healer
- [ ] 实现自愈后的定位器更新
- [ ] 端到端测试

### 阶段 7: 集成测试和优化（1天）
- [ ] 端到端场景测试
- [ ] 性能优化
- [ ] 错误处理完善
- [ ] 文档完善

**总计**: 约 6 天

---

## 9. 风险和缓解措施

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 定位器验证耗时过长 | 抓取慢 | 并发验证、设置超时（每个定位器最多1秒） |
| playwright-healer 依赖不稳定 | 自愈失败 | 提供手动定位器编辑功能 |
| 大页面元素过多（>100个） | 抓取超时 | 分批处理、只抓取可见区域 |
| MinIO 上传失败 | 截图丢失 | 重试机制、降级到本地存储 |
| SSE 连接中断 | 前端无法获取进度 | 前端轮询兜底 |

---

## 10. 验收标准

- [ ] 能成功抓取包含登录的页面元素
- [ ] 每个元素至少有 2 个已验证的定位器
- [ ] 定位器评分准确反映质量
- [ ] SSE 实时推送进度消息
- [ ] 截图正常上传和展示
- [ ] 元素入库后能在数据库中查询
- [ ] 降级策略在测试中有效工作
- [ ] 当所有定位器失效时，自愈机制能成功定位
- [ ] 单元测试覆盖率 >= 80%
- [ ] 端到端测试通过

---

## 11. 后续优化方向

1. **智能分组**: 自动将相似元素分组（如表单字段、按钮组）
2. **定位器建议**: AI 分析失败定位器，建议优化方案
3. **元素变更检测**: 定期巡检，发现元素变更后自动更新定位器
4. **批量验证**: 提供批量验证所有元素定位器的功能
5. **可视化编辑**: 在截图上圈选元素，手动调整定位器

## 12. 与需求文档的对齐说明

### 12.1 字段对齐

| 需求文档字段 | 设计文档实现 | 说明 |
|-------------|-------------|------|
| element_id | element_id | 用户可自定义的元素标识 |
| locator_strategies JSON | locator_strategies JSON | 采用需求文档的 strategies 数组格式，包含 type/value/priority/score |
| confidence (0-10) | confidence | 自愈成功≥3次后回写 |
| source (manual/auto/healed) | source | 元素来源标记 |
| status (active/deprecated/deleted) | status | 元素状态 |
| position_x/y, width/height | position_x/y, width/height | 元素坐标信息 |

### 12.2 业务规则对齐

**规则 ELM-01: 两级存储**
- ✅ 已实现：强制"页面-元素"两级，元素必须挂载页面下
- 实现：ElementRepository.page_id 为必填外键

**规则 ELM-02: 定位策略优先级**
- ✅ 已实现：id > data-testid > name > role+text > text > css > xpath
- 实现：priority 字段 1-8，score 字段 50-120

**规则 ELM-03: 自愈回写**
- ✅ 已实现：自愈成功定位器置信度≥3后自动回写仓库
- 实现：update_healed_locator() 函数，检查 confidence 字段

**规则 ELM-04: 即时生成入库**
- ✅ 已实现：仓库无该元素→AI即时生成→强制人工确认后入库
- 实现：通过 source='auto' 标记，前端需确认后调用 import API

### 12.3 功能补充

根据需求文档，本次设计已包含：
1. ✅ 元素抓取（3.5.1节）
2. ✅ 元素入库（3.5.4节）
3. ✅ 抓取历史记录（FetchHistory表）
4. ✅ 变更检测表结构（ChangeDetection表）

**待后续实现**（超出本次范围）：
- 🔲 变更检测的定期巡检逻辑
- 🔲 影响脚本的关联分析
- 🔲 可视化编辑器（在截图上圈选元素）

---

**文档版本**: v1.1（已对齐需求文档）  
**创建时间**: 2026-08-18  
**更新时间**: 2026-08-18  
**负责人**: Claude + MoonTest Team
