# MoonTest 测试平台

> AI 驱动的智能测试平台 - 让测试更简单、更智能、更高效

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.5+-brightgreen.svg)](https://vuejs.org/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-orange.svg)](https://playwright.dev/)

## 📖 项目简介

MoonTest 是一个基于 AI 的测试平台，提供从用例生成到自动化执行的完整测试解决方案。

### 核心特性

- 🤖 **AI 智能用例生成** - 从 PRD 文档自动生成测试用例
- 🔍 **元素库管理** - Playwright 自动抓取页面元素，5 层定位策略
- 🔄 **自愈引擎** - playwright-healer 集成，自动修复失效定位器
- 📊 **实时进度推送** - SSE 技术实现文字直播效果
- 🚀 **UI 自动化测试** - 基于 Playwright 的 UI 测试执行
- 📈 **质量看板** - 测试数据可视化和统计分析
- 🎯 **白盒代码体检** - 代码质量分析和漏洞检测

### 技术栈

**后端**
- Python 3.12+ / FastAPI
- SQLAlchemy (异步) + PostgreSQL
- Celery + Redis (异步任务)
- Playwright (浏览器自动化)
- MinIO (对象存储)

**前端**
- Vue 3 + TypeScript
- Element Plus
- Vite
- ECharts

**AI 模型**
- 千问 / GLM（可插拔）

---

## 🚀 快速开始

### 方式一：完整安装（推荐）

详见 [QUICKSTART.md](./QUICKSTART.md)

**简要步骤**：

1. 安装依赖服务（PostgreSQL、Redis、MinIO）
2. 克隆项目并安装依赖
3. 初始化数据库
4. 启动后端和前端服务

### 方式二：Docker Compose（最简单）

```bash
# 克隆项目
git clone https://github.com/yourusername/moontest.git
cd moontest

# 启动所有服务
docker compose up -d

# 初始化数据库
cd backend
python init_db.py

# 启动后端
./start.sh  # Linux/Mac
start.bat   # Windows

# 启动前端
cd ../frontend
npm install
npm run dev
```

### 快速体验

访问以下地址：

- 前端应用：http://localhost:5173
- API 文档：http://localhost:8000/docs
- MinIO 控制台：http://localhost:9001

---

## 📁 项目结构

```
MoonTest/
├── backend/                  # 后端服务
│   ├── app/
│   │   ├── api/             # API 路由
│   │   ├── core/            # 核心配置
│   │   ├── models/          # 数据模型
│   │   ├── services/        # 业务服务
│   │   ├── tasks/           # Celery 任务
│   │   └── main.py          # 应用入口
│   ├── tests/               # 测试文件
│   ├── requirements.txt     # Python 依赖
│   └── README.md
├── frontend/                 # 前端应用
│   ├── src/
│   │   ├── api/             # API 调用
│   │   ├── components/      # 组件
│   │   ├── views/           # 页面
│   │   └── main.ts
│   └── package.json
├── docker-compose.yml        # Docker 编排
├── QUICKSTART.md            # 快速启动指南
├── DEVELOPMENT_SUMMARY.md   # 开发总结
└── README.md                # 本文件
```

---

## 🎯 功能模块

### 已完成功能（一期 Phase 0）

#### ✅ 元素库管理
- Playwright 页面元素抓取
- 自动登录支持
- 5 种定位策略生成（id/css/role/text/xpath）
- 页面截图
- SSE 实时进度推送
- 批量元素入库

#### ✅ 项目管理
- 项目 CRUD
- 项目配置
- 被测应用 URL 管理

#### ✅ 基础设施
- FastAPI 后端框架
- Vue 3 前端框架
- PostgreSQL 数据库
- Redis 缓存和任务队列
- MinIO 对象存储
- SSE 实时通信

### 规划中功能（一期 Phase 1-3）

#### 🔜 AI 用例生成
- PRD 文档解析
- AI 测试点识别
- 测试用例自动生成
- 幻觉检测

#### 🔜 用例管理
- 用例 CRUD
- 用例评审
- E2E 精修
- 用例转脚本

#### 🔜 UI 自动化测试
- 测试脚本执行
- 自愈引擎集成
- 执行记录
- 测试报告

#### 🔜 质量看板
- 测试数据统计
- 覆盖率分析
- 趋势图表

---

## 📚 文档

- [快速启动指南](./QUICKSTART.md) - 安装和配置
- [开发总结](./DEVELOPMENT_SUMMARY.md) - 开发进度和技术细节
- [验证报告](./VERIFICATION_REPORT.md) - 测试和验证清单
- [最终验收报告](./FINAL_ACCEPTANCE_REPORT.md) - 完整的验收文档
- [后端 README](./backend/README.md) - 后端详细文档
- [API 文档](http://localhost:8000/docs) - 在线 API 文档（需启动服务）

---

## 🧪 测试

### 运行测试

```bash
cd backend
pytest

# 查看覆盖率
pytest --cov=app --cov-report=html
```

### 测试清单

- [x] 存储客户端单元测试
- [ ] Playwright 服务测试
- [ ] 元素服务测试
- [ ] API 集成测试
- [ ] 前端组件测试

**当前测试覆盖率**：约 15%  
**目标测试覆盖率**：80%+

---

## 🛠️ 开发指南

### 后端开发

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate

# 启动开发服务器
uvicorn app.main:app --reload

# 启动 Celery worker
celery -A app.tasks worker --loglevel=info --pool=solo
```

### 前端开发

```bash
cd frontend
npm run dev

# 构建生产版本
npm run build
```

### 代码规范

- 后端：PEP 8
- 前端：Vue 3 Composition API + TypeScript
- 提交信息：Conventional Commits

---

## 🤝 贡献指南

我们欢迎所有形式的贡献！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

---

## 📊 开发进度

### 一期开发计划（2 个月）

- [x] **Phase 0**：框架搭建和元素库（完成度：90%）
- [ ] **Phase 1**：AI 用例生成（规划中）
- [ ] **Phase 2**：UI 自动化测试（规划中）
- [ ] **Phase 3**：质量看板和报告（规划中）

详见 [DEVELOPMENT_SUMMARY.md](./DEVELOPMENT_SUMMARY.md)

---

## 🐛 已知问题

1. **环境依赖**：需要手动安装 PostgreSQL、Redis（Docker 版本待完善）
2. **测试覆盖率**：当前仅 15%，目标 80%+
3. **Celery 结果**：前端暂时使用 mock 数据
4. **SSE 重连**：断线后未实现自动重连

详见 [FINAL_ACCEPTANCE_REPORT.md](./FINAL_ACCEPTANCE_REPORT.md)

---

## 📝 更新日志

### [0.1.0] - 2026-08-18

#### 新增
- 元素库管理核心功能
- Playwright 元素抓取
- SSE 实时进度推送
- MinIO 截图存储
- 项目管理基础功能

#### 技术
- FastAPI 后端框架
- Vue 3 + Element Plus 前端
- Celery 异步任务
- PostgreSQL 数据库

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](./LICENSE) 文件

---

## 💬 联系方式

- 项目主页：https://github.com/yourusername/moontest
- 问题反馈：https://github.com/yourusername/moontest/issues
- 邮箱：your.email@example.com

---

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Python Web 框架
- [Playwright](https://playwright.dev/) - 强大的浏览器自动化工具
- [Vue.js](https://vuejs.org/) - 渐进式 JavaScript 框架
- [Element Plus](https://element-plus.org/) - 优秀的 Vue 3 组件库

---

**使用 Superpowers 工程流程开发** 🚀
