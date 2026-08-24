# MoonTest Backend

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并修改配置：

```bash
cp .env.example .env
```

### 3. 初始化数据库

```bash
python init_db.py
```

### 4. 启动服务

**Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:**
```bash
start.bat
```

或手动启动：

```bash
# Terminal 1: Celery Worker
celery -A app.tasks worker --loglevel=info --concurrency=4 --pool=solo

# Terminal 2: FastAPI Server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_storage.py

# 查看覆盖率
pytest --cov=app --cov-report=html
```

## 项目结构

```
backend/
├── app/
│   ├── api/              # API 路由
│   │   └── v1/
│   │       ├── elements.py
│   │       ├── projects.py
│   │       ├── health.py
│   │       └── sse.py
│   ├── core/             # 核心配置
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── redis.py
│   │   ├── storage.py
│   │   └── sse.py
│   ├── models/           # 数据模型
│   │   ├── project.py
│   │   ├── element.py
│   │   ├── test_case.py
│   │   └── execution.py
│   ├── services/         # 业务服务
│   │   ├── element_service.py
│   │   └── playwright_service.py
│   ├── tasks/            # Celery 任务
│   │   └── element_tasks.py
│   ├── schemas/          # Pydantic schemas
│   └── main.py           # 应用入口
├── tests/                # 测试文件
├── requirements.txt
└── init_db.py
```

## 核心功能

### 元素库

- **元素抓取**: `/api/v1/elements/fetch`
- **批量导入**: `/api/v1/elements/batch-import`
- **SSE 流**: `/api/sse/stream/{session_id}`

### 使用示例

```python
import requests

# 1. 触发抓取
response = requests.post('http://localhost:8000/api/v1/elements/fetch', json={
    'project_id': 'your-project-id',
    'url': 'https://example.com',
    'username': 'admin',  # 可选
    'password': 'password'  # 可选
})

session_id = response.json()['data']['session_id']

# 2. 连接 SSE 流
from sseclient import SSEClient
messages = SSEClient(f'http://localhost:8000/api/sse/stream/{session_id}')

for msg in messages:
    print(msg.data)
```

## 环境要求

- Python 3.12+
- PostgreSQL 15+
- Redis 7.0+
- MinIO (可选，用于截图存储)

## 常见问题

### Celery 任务不执行

检查 Redis 连接和 Celery worker 是否正常启动。

### Playwright 浏览器启动失败

```bash
playwright install chromium
playwright install-deps
```

### 数据库连接失败

确认 PostgreSQL 服务正在运行，并检查 `.env` 中的连接配置。
