# MoonTest 运维部署手册（小白版）

> 面向第一次接手这套系统的人。看完这篇你能：把系统跑起来、登录数据库和 MinIO 看数据、重启服务、看日志排查问题。
> 更新：2026-08-31（11/11 模块合并后）

---

## 0. 这套系统由哪几块组成？

```
┌──────────┐     ┌──────────────┐     ┌─────────────┐
│  前端     │ --> │  后端 (FastAPI)│ --> │  PostgreSQL  │  数据都存这
│ (Vue3页面)│     │  端口 8000     │     │  端口 5432   │
└──────────┘     └──────┬───────┘     └─────────────┘
                        │
        ┌───────────────┼──────────────┐
        ▼               ▼              ▼
   ┌─────────┐    ┌──────────┐   ┌──────────┐
   │  Redis   │    │  MinIO    │   │ Playwright│
   │ 端口 6379 │   │ 端口 9000  │   │ (浏览器)  │
   │ 任务队列  │    │ 文件/截图  │   └──────────┘
   └─────────┘    └──────────┘
        ▲
        └── Celery Worker (后台干活的进程, 从 Redis 领任务)
```

**一句话记住**：前端只是壳；后端是大脑；PostgreSQL 存数据；Redis 传任务；MinIO 存截图文件；Celery 是后台打工人。

---

## 1. 启动前的检查清单

按顺序确认 4 个依赖都活着（**任何一个没起，后端都起不来或功能残缺**）：

```bash
# 1. PostgreSQL 能连吗？
psql -U moontest -h localhost -d moontest -c "SELECT 1;"
# 输入密码后看到表格输出 = OK（密码在 backend/.env 的 DATABASE_URL 里）

# 2. Redis 活着吗？
redis-cli ping
# 回 PONG = OK

# 3. MinIO 活着吗？
curl -s http://localhost:9000/minio/health/live -o /dev/null -w "%{http_code}\n"
# 回 200 = OK

# 4. 配置文件在吗？
# backend/.env 必须存在（没有就复制模板: cp backend/.env.example backend/.env 再填 key）
```

> **首次部署**：Redis 和 MinIO 一般用 Docker 起（见第 2 节）。数据库迁移跑一次 `python init_db.py`（建表，详见第 6 节）。

---

## 2. 起依赖服务（Redis / MinIO，Docker 方式）

```bash
# Redis
docker run -d --name moontest-redis --restart unless-stopped -p 6379:6379 redis:7

# MinIO（控制台在 9001 端口，网页登录用）
docker run -d --name moontest-minio --restart unless-stopped \
  -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=admin \
  -e MINIO_ROOT_PASSWORD=password123 \
  minio/minio server /data --console-address ":9001"
```

> 账号密码要和 `backend/.env` 里 `STORAGE_ACCESS_KEY` / `STORAGE_SECRET_KEY` 一致（默认 admin / password123）。
> `--restart unless-stopped` = 机器重启后自动拉起，不用管。
> MinIO 数据默认在容器里，删容器=删文件。要持久化加 `-v D:/moontest-minio-data:/data`。

**验证 MinIO 网页控制台**：浏览器开 `http://localhost:9001`，用上面账号密码登录，能看到 `moontest` 桶（后端首次启动会自动建）。

---

## 3. 起后端（3 个进程，缺一不可）

后端不是只有一个进程！**API 服务、Celery Worker、（开发时）uvicorn 是分开的**。

先确认在 backend 目录、依赖装好：

```bash
cd backend
pip install -r requirements.txt
```

### 3.1 API 服务（网页请求都走这）

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- `--reload` = 改代码自动重启（**只用于开发**；生产去掉）
- 起来后验证：浏览器开 `http://localhost:8000/docs` 能看到接口文档页
- **日志直接打在当前窗口**

### 3.2 Celery Worker（转脚本/跑测试/白盒扫描的后台任务都靠它）

**必须另开一个窗口**：

```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

- `--pool=solo` = Windows 必加（Windows 上 Celery 默认的 prefork 池会崩）
- 没起它的话：页面上点"转脚本""运行"会一直转圈没反应（任务发到 Redis 没人领）
- **日志直接打在当前窗口**

### 3.3 一键脚本（可选，嫌每次敲两行麻烦）

新建 `backend/start_backend.bat`：

```bat
@echo off
start "MoonTest-API" cmd /k "cd /d D:\MoonTest\backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
start "MoonTest-Worker" cmd /k "cd /d D:\MoonTest\backend && celery -A app.tasks.celery_app worker --loglevel=info --pool=solo"
echo 两个窗口已拉起，关闭对应窗口即停止服务
```

（路径按实际项目位置改。）

---

## 4. 起前端

**再开一个窗口**：

```bash
cd frontend
npm install     # 首次才需要
npm run dev
```

- 起来后浏览器开 `http://localhost:5173`（vite 默认端口，以实际输出为准）
- 前端会把 `/api` 请求自动转发到后端 8000（vite.config.js 里的 proxy 已配好，不用改）
- **生产部署**用 `npm run build`，产物在 `dist/` 目录，交给 nginx 托管（本文不展开）

---

## 5. 完整启动顺序（背下来）

```
① PostgreSQL（一般装好就是服务，开机自启）
② Redis、MinIO（docker run 过的会自动起，docker ps 确认）
③ Celery Worker     ← 顺序无硬要求，但要在"点页面按钮"之前起
④ 后端 uvicorn
⑤ 前端 npm run dev
```

**快速验证系统活了**：浏览器开前端页面 → 项目列表能加载（=后端+DB 通）→ 随便传个文档转脚本（=Celery+Redis 通）→ 失败截图能看（=MinIO 通）。

---

## 6. 数据库迁移（新环境/新模块合入后跑一次）

```bash
cd backend
python init_db.py
```

- 幂等：跑多次没副作用（表已存在会跳过，默认项目已存在会跳过）
- **什么时候要跑**：第一次部署；拉了含新表的代码之后（如 #8 regression_set、#9 whitescan 表）
- 表已存在但结构旧（缺列）时，init_db 只建缺的表不改旧表——若模型加了列，需手动 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`（历史先例：#4 给 script_asset 加列时就是这么做的）

---

## 7. 登录 PostgreSQL 看数据

```bash
# 方式一：命令行
psql -U moontest -h localhost -d moontest
# 密码见 backend/.env 的 DATABASE_URL（postgres://moontest:密码@localhost:5432/moontest）

# 常用命令（psql 里执行）：
\dt                          -- 看所有表
\d script_asset              -- 看某表结构
SELECT count(*) FROM script_asset;             -- 脚本总数
SELECT name, last_status, run_count FROM script_asset ORDER BY created_at DESC LIMIT 10;  -- 最近脚本
SELECT exec_id, exec_type, status, pass_rate FROM execution_record ORDER BY started_at DESC LIMIT 10;  -- 最近执行
\q                           -- 退出
```

```bash
# 方式二：图形界面（推荐小白）
# 用 DBeaver / Navicat / pgAdmin，连接参数照抄 .env：
#   Host: localhost  Port: 5432  库名: moontest  用户: moontest  密码: 见 .env
```

---

## 8. 登录 MinIO 看文件（截图等）

1. 浏览器开 `http://localhost:9001`
2. 账号 `admin` / 密码 `password123`（或 .env 里的 STORAGE_ACCESS_KEY/SECRET_KEY）
3. 左侧 Object Browser → `moontest` 桶 → 能看到 `fail_step1.png` 之类的失败截图
4. 页面上"查看截图"打不开时，来这里确认文件是否存在

---

## 9. 重启服务

| 要重启什么 | 怎么做 |
|---|---|
| 后端 API | 关掉 uvicorn 窗口 → 重新跑启动命令（开发模式 --reload 改代码会自动重启，不用手动） |
| Celery Worker | 关掉 worker 窗口 → 重新跑。**改了 tasks/ 下的代码必须重启 worker**（Celery 不热加载） |
| 前端 | vite 热更新，一般不用动；改了 vite.config.js 才要重启 |
| Redis/MinIO | `docker restart moontest-redis moontest-minio` |
| 全部重来 | 按第 5 节顺序从 ② 开始 |

**改了 backend/.env 之后**：uvicorn --reload 会自动重启；**Celery worker 必须手动重启**（它不读 .env 变更）。

---

## 10. 看日志 / 排查问题

### 10.1 日志在哪

| 进程 | 日志位置 |
|---|---|
| 后端 API | uvicorn 窗口实时输出 |
| Celery Worker | worker 窗口实时输出 |
| 前端 | 浏览器 F12 → Console / Network |
| Docker 容器 | `docker logs moontest-redis` / `docker logs moontest-minio` |

### 10.2 症状 → 排查表

| 症状 | 先查什么 | 常见原因 |
|---|---|---|
| 页面打不开/接口 502 | 后端窗口是否活着 | uvicorn 挂了；8000 端口被占（`netstat -ano \| findstr 8000`） |
| 接口报 "connect refused" 5432/6379/9000 | 第 1 节检查清单 | 对应依赖没起 |
| 点"运行/转脚本"没反应、一直转圈 | Celery worker 窗口 | worker 没起；或 Redis 没起 |
| 任务发了但 worker 报错退出 | worker 窗口报错 | Windows 忘了 `--pool=solo` |
| 截图看不到 / "查看截图" 404 | MinIO 起了吗；桶里有没有文件 | MinIO 没起；storage 配置和 MinIO 账号不一致 |
| 数据库连接失败 | `psql` 能连吗 | PG 没起；.env 密码不对 |
| 后端日志刷 "Provider 'xxx' not available" | .env 的 AI key | 对应厂商 API_KEY 没填（自愈 Level4/诊断需要 MOONSHOT_API_KEY） |
| 跑测试 2 个 storage 用例失败 | 是否起了 MinIO | 环境问题（已确认非代码），`--deselect tests/test_storage_get_object.py` 跳过 |

### 10.3 快速健康检查一条龙

```bash
redis-cli ping                                              # PONG
curl -s http://localhost:9000/minio/health/live -w "%{http_code}\n" -o /dev/null   # 200
curl -s http://localhost:8000/api/v1/health                 # 看后端自带健康检查返回
psql -U moontest -h localhost -d moontest -c "SELECT 1;"    # 正常出表格
```

---

## 11. 常用运维命令速查

```bash
# Docker
docker ps                        # 看活着的容器
docker restart moontest-redis moontest-minio
docker logs --tail 100 moontest-minio   # 看最近100行日志

# 端口占用排查（起服务报 port in use 时）
netstat -ano | findstr :8000     # 找到 PID
tasklist | findstr <PID>         # 看是什么进程
taskkill /PID <PID> /F           # 杀掉

# Celery 清空积压任务（worker 卡死重启后）
redis-cli del celery             # 清默认队列（谨慎：未执行任务会丢）

# 后端测试（改代码后验证）
cd backend
python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py --deselect tests/test_storage_get_object.py

# 前端构建验证
cd frontend && npx vite build
```

---

## 12. 已知注意事项（踩过的坑）

1. **Celery 在 Windows 必须 `--pool=solo`**，否则 worker 起来就崩。
2. **MinIO 数据默认在容器里**，`docker rm` 会连文件一起删——重要数据加 `-v` 挂载持久化。
3. **AI key 不配不影响启动**，但用到对应功能会报错：自愈 Level4 视觉和 AI 诊断需要 `MOONSHOT_API_KEY`（.env 已有该段，填 key 即可）。
4. **test_storage_get_object 2 个用例**在 MinIO 没起时失败，是环境问题不是代码问题。
5. **数据库密码**在 `.env` 的 DATABASE_URL 和 `.env.example` 里可见；PG16 实际密码与文档示例可能不同，以 `.env` 为准。
6. **另一个会话在做数据库迁移**——迁移工具落地后，第 6 节会替换为正式迁移命令（如 alembic），届时以新文档为准。

---

*有本文档没覆盖的情况：先看对应进程窗口的报错最后一行，拿关键词问 Claude。*
