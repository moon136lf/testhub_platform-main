# AI智能用例生成模块 - 设计规格

**版本**: v1.0  
**日期**: 2026-08-18  
**作者**: Claude Code (Opus 4.8)  
**状态**: 待审批

---

## 1. 概述

### 1.1 目标

实现MoonTest平台的核心功能：AI驱动的测试用例智能生成。用户通过上传PRD文档，经过7步向导流程，AI自动识别测试点并生成可执行的测试用例。

### 1.2 核心能力

- 📄 多格式文档解析（.docx / .pdf / .txt / .md）
- 🧠 知识库向量检索（基于pgvector）
- 🤖 AI测试点识别（GLM-4/千问/DeepSeek/Claude）
- ✨ 测试规则自定义（自然语言 → AI生成Prompt）
- 🔍 幻觉检测（元素库验证 + 关键词规则）
- 📊 实时进度推送（SSE直播）

### 1.3 技术栈

- **后端**: Python 3.12 + FastAPI + Celery + PostgreSQL + pgvector
- **前端**: Vue3 + TypeScript + Element Plus
- **AI**: GLM-4（主力）+ 千问/DeepSeek/Claude（兜底）
- **存储**: MinIO（文档）+ Redis（SSE消息队列）

---

## 2. 架构设计

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (Vue3)                          │
│         7步向导 + SSE实时推送 + 测试点编辑              │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP + SSE
┌────────────────────▼────────────────────────────────────┐
│                FastAPI 后端                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │  API层 (/api/v1/ai-case-generation/)            │  │
│  │  - upload-document                               │  │
│  │  - search-knowledge                              │  │
│  │  - identify-points                               │  │
│  │  - generate-cases                                │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │                                   │
│  ┌──────────────────▼───────────────────────────────┐  │
│  │  服务层                                          │  │
│  │  - AIGateway (多provider管理)                   │  │
│  │  - DocumentParser (文档解析)                    │  │
│  │  - KnowledgeService (向量检索)                  │  │
│  │  - TestPointGenerator (测试点生成)              │  │
│  │  - TestCaseGenerator (用例生成)                 │  │
│  │  - HallucinationDetector (幻觉检测)             │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │                                   │
│  ┌──────────────────▼───────────────────────────────┐  │
│  │  Celery异步任务                                  │  │
│  │  - parse_document_task (Step 2)                 │  │
│  │  - retrieve_knowledge_task (Step 4)             │  │
│  │  - identify_test_points_task (Step 5)           │  │
│  │  - generate_test_cases_task (Step 7)            │  │
│  └──────────────────┬───────────────────────────────┘  │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴─────────────┐
        │                          │
┌───────▼────────┐      ┌──────────▼─────────┐
│  PostgreSQL    │      │  Redis + MinIO     │
│  + pgvector    │      │  SSE消息 + 文档    │
└────────────────┘      └────────────────────┘
```

### 2.2 7步向导流程

```
Step 1: 选择项目
    ↓
Step 2: 上传PRD文档（或粘贴文本）→ Celery异步解析
    ↓
Step 3: 勾选生成规则 + 配置幻觉处理策略
    ↓
Step 4: 知识库自动检索（pgvector） → 用户勾选相关文档
    ↓
Step 5: AI识别测试点（Celery + SSE实时推送）
    ↓
Step 6: 勾选/编辑/补充测试点
    ↓
Step 7: 批量生成用例（Celery + 幻觉检测 + SSE）
```

---

## 3. 数据模型

### 3.1 新增数据表

#### 3.1.1 test_rule（测试规则表）

```sql
CREATE TABLE test_rule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL,                    -- 规则名称
    description TEXT NOT NULL,                     -- 用户输入的自然语言描述
    prompt_template TEXT,                          -- AI生成的Prompt模板
    is_builtin BOOLEAN DEFAULT FALSE,              -- 是否内置规则
    status VARCHAR(20) DEFAULT 'active',           -- active/generating/failed
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**说明**：
- 内置规则：边界值分析、等价类划分、场景法、状态迁移等（5-8条）
- 自定义规则：用户输入自然语言描述，AI自动生成Prompt模板
- `status=generating`：规则创建中，AI正在生成Prompt

#### 3.1.2 knowledge_document（知识文档表）

```sql
CREATE TABLE knowledge_document (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES project(id),
    doc_name VARCHAR(200) NOT NULL,
    doc_type VARCHAR(20) NOT NULL,                 -- requirement/bug/case
    file_url TEXT,                                 -- MinIO存储路径
    content TEXT,                                  -- 解析后的文本内容
    chunk_count INTEGER DEFAULT 0,
    vector_status VARCHAR(20) DEFAULT 'pending',   -- pending/processing/completed/failed
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 3.1.3 knowledge_chunk（知识分块表）

```sql
CREATE TABLE knowledge_chunk (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES knowledge_document(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536),                        -- pgvector字段
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建向量索引
CREATE INDEX idx_knowledge_chunk_embedding ON knowledge_chunk 
USING ivfflat (embedding vector_cosine_ops);
```

**说明**：
- 分块策略：500字符/块，重叠50字符
- 向量维度：1536（text-embedding-v3）
- 索引算法：IVFFlat（余弦距离）

#### 3.1.4 generation_session（生成会话表）

```sql
CREATE TABLE generation_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES project(id),
    document_content TEXT,                         -- PRD内容
    selected_rules JSONB,                          -- 勾选的规则ID数组
    selected_knowledge JSONB,                      -- 勾选的知识文档ID数组
    hallucination_strategy VARCHAR(20),            -- filter/mark/separate
    current_step INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 3.1.5 hallucination_config（幻觉检测配置表）

```sql
CREATE TABLE hallucination_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_type VARCHAR(50) NOT NULL,  -- forbidden_keyword / element_threshold
    config_value TEXT NOT NULL,
    description VARCHAR(200),
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认禁用词
INSERT INTO hallucination_config (config_type, config_value, description) VALUES
('forbidden_keyword', '观察', '非自动化词汇'),
('forbidden_keyword', '查看', '非自动化词汇'),
('forbidden_keyword', '验证', '非自动化词汇'),
('forbidden_keyword', '检查', '非自动化词汇'),
('forbidden_keyword', '确认', '非自动化词汇');
```

### 3.2 复用已有表

- `test_point` - 存储AI识别的测试点
- `test_case` - 存储生成的测试用例
- `project` - 项目信息
- `page_repository` - 页面信息
- `element_repository` - 元素库

---

## 4. 核心服务设计

### 4.1 AI网关服务（AIGateway）

**文件**: `app/services/ai_gateway.py`

**职责**：
- 统一AI模型调用接口
- 多Provider管理（GLM-4/千问/DeepSeek/Claude）
- 自动兜底机制
- Token消耗统计

**核心接口**：

```python
class AIGateway:
    async def chat(self, messages: List[Dict], provider: str = None, **kwargs) -> Dict
    async def embed(self, text: str, provider: str = "qwen") -> List[float]
    async def with_fallback(self, messages: List[Dict], providers: List[str]) -> Dict
```

**配置参数**：

```python
AI_DEFAULT_PROVIDER: str = "glm-4"
AI_FALLBACK_PROVIDERS: List[str] = ["glm-4", "qwen", "deepseek"]
AI_EMBEDDING_PROVIDER: str = "qwen"

GLM_API_KEY: str
GLM_API_URL: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

QWEN_API_KEY: str
QWEN_API_URL: str = "https://dashscope.aliyuncs.com/api/v1/..."
```

### 4.2 文档解析服务（DocumentParser）

**文件**: `app/services/document_parser.py`

**支持格式**：
- .docx → python-docx
- .pdf → PyPDF2
- .txt → 直接读取
- .md → markdown库

**特殊处理**：
- 同时上传文档和粘贴文本时，合并两者内容
- 文档过大（>10MB）前端限制
- 解析失败返回详细错误信息

### 4.3 知识库服务（KnowledgeService）

**文件**: `app/services/knowledge_service.py`

**核心方法**：

```python
async def vectorize_document(doc_id: UUID, content: str)
    # 1. 分块（500字符，重叠50）
    # 2. 批量生成向量（调用AI embedding）
    # 3. 存储到knowledge_chunk

async def search_similar(query: str, project_id: UUID, top_k: int = 10) -> List[Dict]
    # 1. 查询文本向量化
    # 2. pgvector余弦相似度检索
    # 3. 返回Top-K结果（包含相似度分数）
```

**向量化时机**：
- 用户上传知识文档后，Celery后台异步处理
- 文档状态：pending → processing → completed/failed

### 4.4 测试点生成服务（TestPointGenerator）

**文件**: `app/services/test_point_generator.py`

**输入**：
- PRD文档内容
- 生成规则（Prompt模板）
- 知识库上下文（检索到的历史文档）

**输出**：
- 按页面分组的测试点列表

```json
{
  "登录页": [
    {
      "name": "正常登录-用户名密码正确",
      "type_label": "正常流程",
      "description": "用户输入正确的用户名和密码，点击登录"
    }
  ]
}
```

### 4.5 用例生成服务（TestCaseGenerator）

**文件**: `app/services/test_case_generator.py`

**输入**：测试点对象

**输出**：测试用例数据

```json
{
  "name": "登录-正常登录",
  "priority": "P0",
  "case_type": "functional",
  "precondition": "用户未登录",
  "steps": [
    {"action": "打开", "target": "登录页", "data": ""},
    {"action": "输入", "target": "用户名输入框", "data": "admin"},
    {"action": "输入", "target": "密码输入框", "data": "123456"},
    {"action": "点击", "target": "登录按钮", "data": ""}
  ],
  "expected_result": "成功跳转到首页，显示用户昵称"
}
```

### 4.6 幻觉检测服务（HallucinationDetector）

**文件**: `app/services/hallucination_detector.py`

**检测维度**：

1. **关键词检测** - 检查是否包含非自动化词汇（观察/查看/验证等）
2. **元素库验证** - 检查步骤中引用的元素是否存在于元素库

**检测结果**：

```python
{
    "status": "normal" | "suspected",
    "reasons": ["步骤1包含非自动化词汇「观察」"],
    "confidence": 0.85
}
```

**处理策略**：
- `filter` - 自动过滤疑似幻觉用例
- `mark` - 保留所有用例，标记疑似幻觉（⚠️橙色标签）
- `separate` - 分离展示（正常用例 / 疑似幻觉用例）

---

## 5. API端点设计

### 5.1 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/ai-case-generation/upload-document` | Step 2: 上传PRD文档 |
| POST | `/api/v1/ai-case-generation/search-knowledge` | Step 4: 触发知识库检索 |
| GET  | `/api/v1/ai-case-generation/knowledge-results/{session_id}` | Step 4: 获取检索结果 |
| POST | `/api/v1/ai-case-generation/identify-points` | Step 5: AI识别测试点 |
| GET  | `/api/v1/ai-case-generation/test-points` | Step 6: 获取测试点列表 |
| PUT  | `/api/v1/ai-case-generation/test-points/{point_id}` | Step 6: 编辑测试点 |
| POST | `/api/v1/ai-case-generation/test-points` | Step 6: 手动添加测试点 |
| POST | `/api/v1/ai-case-generation/generate-cases` | Step 7: 批量生成用例 |
| GET  | `/api/v1/ai-case-generation/test-cases` | Step 7: 获取生成的用例 |
| GET  | `/api/v1/ai-case-generation/rules` | 获取所有规则 |
| POST | `/api/v1/ai-case-generation/rules` | 创建自定义规则 |

### 5.2 请求/响应示例

#### 上传文档

```http
POST /api/v1/ai-case-generation/upload-document
Content-Type: multipart/form-data

project_id: "uuid"
file: PRD.docx
text_content: "补充文本内容..."
```

```json
{
  "code": 0,
  "data": {
    "session_id": "uuid",
    "task_id": "celery-task-id",
    "sse_url": "/api/sse/stream/{session_id}"
  }
}
```

#### 识别测试点

```http
POST /api/v1/ai-case-generation/identify-points
Content-Type: application/json

{
  "session_id": "uuid",
  "project_id": "uuid",
  "document_content": "PRD文本...",
  "rule_ids": ["rule-uuid-1", "rule-uuid-2"],
  "knowledge_ids": ["doc-uuid-1", "doc-uuid-2"]
}
```

---

## 6. Celery异步任务

### 6.1 任务列表

| 任务名 | 说明 | 预计时长 |
|--------|------|---------|
| `parse_document_task` | Step 2: 解析文档 | 5-10秒 |
| `retrieve_knowledge_task` | Step 4: 知识库检索 | 2-5秒 |
| `identify_test_points_task` | Step 5: AI识别测试点 | 30-60秒 |
| `generate_test_cases_task` | Step 7: 批量生成用例 | 2-5分钟 |

### 6.2 SSE消息格式

```json
{
  "timestamp": "2026-08-18T14:30:00Z",
  "type": "system|ai|error|cost",
  "stage": "parse_doc|knowledge|generate|save",
  "content": "正在解析文档...",
  "progress": 0.3,
  "tokens_used": 500,
  "tokens_estimated_total": 5000
}
```

### 6.3 错误处理

- AI调用失败 → 自动尝试兜底provider
- 所有provider失败 → 返回错误，允许用户重试
- 文档解析失败 → 返回详细错误信息
- 任务超时（10分钟） → 自动取消，返回部分结果

---

## 7. 前端实现

### 7.1 页面文件

- `frontend/src/views/ai/CaseGenerate.vue` - 7步向导主页面
- `frontend/src/api/ai-case.js` - API调用封装

### 7.2 核心组件

```vue
<el-steps :active="currentStep" align-center>
  <el-step title="选择项目" />
  <el-step title="上传材料" />
  <el-step title="生成规则" />
  <el-step title="知识库检索" />
  <el-step title="识别测试点" />
  <el-step title="勾选测试点" />
  <el-step title="生成用例" />
</el-steps>
```

### 7.3 SSE集成

```javascript
const sseConnection = new EventSource(`/api/sse/stream/${sessionId}`)

sseConnection.onmessage = (event) => {
  const data = JSON.parse(event.data)
  
  // 更新直播消息
  liveMessages.value.push({
    timestamp: new Date(data.timestamp).toLocaleTimeString(),
    content: data.content,
    type: data.type
  })
  
  // 更新进度条
  progress.value = data.progress
  
  // 更新Token消耗
  tokensUsed.value = data.tokens_used
}
```

---

## 8. 性能优化

### 8.1 文档解析缓存

- 已解析文档缓存到Redis
- Key: `doc:parsed:{file_hash}`
- TTL: 1小时

### 8.2 向量检索优化

- pgvector IVFFlat索引
- 限制Top-K为10
- 只检索同项目文档

### 8.3 AI调用优化

- 批量生成时复用HTTP连接
- 实现请求速率限制
- Token预估提前计算

---

## 9. 边界情况处理

| 场景 | 处理方式 |
|------|---------|
| PRD文档过大（>10MB） | 前端限制文件大小 |
| 文档内容过长（>50000字） | 自动分块或提示用户精简 |
| AI返回格式不正确 | 重试3次，失败后标记"解析失败" |
| 知识库为空 | Step 4显示"未在知识库找到相关文档"，提供"跳过此步"按钮 |
| 未勾选任何规则 | 使用默认规则（自动化思维规则） |
| 未勾选测试点 | 提示至少选择1个 |
| Token配额不足 | 实时检测，提示用户，允许继续或停止 |
| 并发生成冲突 | 使用session_id隔离 |
| 用例生成部分失败 | 继续处理剩余，最后汇总成功/失败数量 |

---

## 10. 测试计划

### 10.1 单元测试

- AI网关服务测试
- 文档解析测试
- 知识库检索测试
- 幻觉检测测试

### 10.2 集成测试

- 端到端流程测试
- SSE消息推送测试
- Celery任务测试

### 10.3 测试覆盖目标

- 单元测试覆盖率：>80%
- API端点测试：100%

---

## 11. 后续扩展

### 11.1 Phase 2功能

- 用例评审与E2E精修
- 用例转自动化脚本

### 11.2 可插拔设计

- 文档解析器注册中心（支持扩展新格式）
- AI Provider注册中心（支持扩展新模型）

---

## 12. 验收标准

- [ ] 用户可以上传PRD文档并解析
- [ ] 知识库检索返回Top 10相关文档
- [ ] AI成功识别测试点并按页面分组
- [ ] 用户可以勾选、编辑、补充测试点
- [ ] 批量生成用例，SSE实时显示进度
- [ ] 幻觉检测正确标记疑似用例
- [ ] 所有异步任务有错误处理
- [ ] 单元测试覆盖率>80%

---

**文档状态**: ✅ 设计完成，等待用户审批
