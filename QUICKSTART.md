# MoonTest 快速启动指南（无 Docker）

## 前提条件

在开始之前，请确保已安装以下软件：

### 必需软件
- ✅ Python 3.11+ （已安装：3.11.9）
- ⬜ PostgreSQL 15+
- ⬜ Redis 7.0+
- ⬜ Node.js 18+

### 可选软件
- MinIO（用于截图存储，也可使用本地文件系统）

---

## 方案一：完整安装（推荐）

### 1. 安装 PostgreSQL

**Windows 下载地址**：
- https://www.postgresql.org/download/windows/

**安装后创建数据库**：
```sql
CREATE DATABASE moontest;
CREATE USER moontest WITH PASSWORD 'moontest123';
GRANT ALL PRIVILEGES ON DATABASE moontest TO moontest;
```

### 2. 安装 Redis

**Windows 下载地址**：
- https://github.com/microsoftarchive/redis/releases
- 或使用 Memurai（Redis 的 Windows 替代品）：https://www.memurai.com/

**启动 Redis**：
```bash
redis-server
```

### 3. 配置后端环境变量

编辑 `backend/.env`：
```env
# Database
DATABASE_URL=postgresql+asyncpg://moontest:moontest123@localhost:5432/moontest

# Redis
REDIS_URL=redis://localhost:6379/0

# MinIO (可选，留空则使用本地存储)
STORAGE_ENDPOINT=http://localhost:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STORAGE_BUCKET=moontest

# JWT
SECRET_KEY=your-super-secret-key-change-in-production
```

### 4. 安装 Python 依赖

```bash
cd D:\MoonTest\backend
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 5. 初始化数据库

```bash
python init_db.py
```

### 6. 启动后端服务

**Terminal 1 - Celery Worker**：
```bash
cd D:\MoonTest\backend
.\venv\Scripts\activate
celery -A app.tasks worker --loglevel=info --concurrency=2 --pool=solo
```

**Terminal 2 - FastAPI Server**：
```bash
cd D:\MoonTest\backend
.\venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7. 启动前端

```bash
cd D:\MoonTest\frontend
npm install
npm run dev
```

### 8. 访问应用

- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs

---

## 方案二：Docker 安装（需要 Docker Desktop）

### 1. 安装 Docker Desktop

下载地址：https://www.docker.com/products/docker-desktop

### 2. 启动所有服务

```bash
cd D:\MoonTest
docker compose up -d
```

### 3. 初始化数据库

```bash
cd backend
python init_db.py
```

### 4. 使用 start.bat 启动

```bash
cd D:\MoonTest\backend
start.bat
```

---

## 方案三：开发模式（最小化依赖）

如果只想快速测试前端和 API 结构，可以：

### 1. 使用 SQLite 代替 PostgreSQL

修改 `backend/.env`：
```env
DATABASE_URL=sqlite+aiosqlite:///./moontest.db
```

修改 `backend/requirements.txt`，添加：
```
aiosqlite==0.19.0
```

### 2. 使用内存 Redis（Fakeredis）

修改 `backend/requirements.txt`，添加：
```
fakeredis==2.21.1
```

修改 `backend/app/core/redis.py`：
```python
# 开发模式使用 fakeredis
import fakeredis.aioredis
redis_client.redis = fakeredis.aioredis.FakeRedis()
```

### 3. 跳过 MinIO

修改 `backend/app/core/storage.py`，改为本地文件存储：
```python
async def upload_bytes(self, data: bytes, object_name: str) -> str:
    # 保存到本地
    file_path = f"./uploads/{object_name}"
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'wb') as f:
        f.write(data)
    return f"/uploads/{object_name}"
```

---

## 常见问题

### Q1: Celery 启动报错 "No module named 'app'"

**解决**：确保在 backend 目录下运行，且虚拟环境已激活。

### Q2: Playwright 浏览器下载失败

**解决**：
```bash
playwright install chromium --with-deps
```

### Q3: PostgreSQL 连接失败

**解决**：
1. 确认 PostgreSQL 服务正在运行
2. 检查 `.env` 中的连接字符串
3. 确认数据库和用户已创建

### Q4: 前端启动报错 "Cannot find module"

**解决**：
```bash
rm -rf node_modules package-lock.json
npm install
```

---

## 验证安装

### 1. 检查后端 API

访问：http://localhost:8000/docs

测试端点：
- `GET /api/v1/health` - 应返回 `{"status": "ok"}`

### 2. 检查前端

访问：http://localhost:5173

应该看到 MoonTest 登录页面或仪表盘。

### 3. 测试元素抓取

1. 进入"元素库"页面
2. 输入 URL：`https://www.baidu.com`
3. 点击"抓取元素"
4. 观察 SSE 实时进度
5. 查看元素列表

---

## 下一步

安装完成后，请参考：
- `VERIFICATION_REPORT.md` - 完整测试清单
- `DEVELOPMENT_SUMMARY.md` - 开发总结
- `backend/README.md` - 后端详细文档

准备好后，运行 `/superpowers:verification-before-completion` 进行最终验收。
