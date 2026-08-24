# MoonTest 项目文档导航

欢迎来到 MoonTest 测试平台！本文档帮助您快速找到需要的信息。

---

## 📚 文档索引

### 🚀 快速开始

| 文档 | 描述 | 适用对象 |
|------|------|----------|
| [README.md](./README.md) | 项目概述和特性介绍 | 所有人 |
| [QUICKSTART.md](./QUICKSTART.md) | 详细的安装和启动指南 | 开发者、测试者 |
| [backend/README.md](./backend/README.md) | 后端详细文档 | 后端开发者 |

### 📊 开发文档

| 文档 | 描述 | 适用对象 |
|------|------|----------|
| [DEVELOPMENT_SUMMARY.md](./DEVELOPMENT_SUMMARY.md) | 开发进度和技术总结 | 项目经理、开发者 |
| [.claude/plans/element-library-implementation.md](./.claude/plans/element-library-implementation.md) | 元素库实施计划 | 开发者 |
| [COMPLETION_REPORT.md](./COMPLETION_REPORT.md) | 开发完成报告 | 项目经理、团队 |

### ✅ 验收文档

| 文档 | 描述 | 适用对象 |
|------|------|----------|
| [VERIFICATION_REPORT.md](./VERIFICATION_REPORT.md) | 验证清单和测试报告 | QA、开发者 |
| [FINAL_ACCEPTANCE_REPORT.md](./FINAL_ACCEPTANCE_REPORT.md) | 最终验收报告 | 项目经理、客户 |

### 📖 其他

| 文档 | 描述 |
|------|------|
| [LICENSE](./LICENSE) | MIT 开源许可证 |

---

## 🗂️ 项目结构

```
MoonTest/
├── 📄 README.md                          # 项目主文档
├── 📄 QUICKSTART.md                      # 快速启动指南
├── 📄 DEVELOPMENT_SUMMARY.md             # 开发总结
├── 📄 VERIFICATION_REPORT.md             # 验证报告
├── 📄 FINAL_ACCEPTANCE_REPORT.md         # 最终验收
├── 📄 COMPLETION_REPORT.md               # 完成报告
├── 📄 LICENSE                            # 开源许可证
├── 📄 docker-compose.yml                 # Docker 编排
│
├── 📁 .claude/                           # Claude 配置
│   └── plans/
│       └── element-library-implementation.md
│
├── 📁 backend/                           # 后端服务
│   ├── 📄 README.md                      # 后端文档
│   ├── 📄 requirements.txt               # Python 依赖
│   ├── 📄 init_db.py                     # 数据库初始化
│   ├── 📄 start.sh / start.bat           # 启动脚本
│   ├── 📄 pytest.ini                     # 测试配置
│   │
│   ├── 📁 app/                           # 应用代码
│   │   ├── main.py                       # 入口文件
│   │   ├── api/                          # API 路由
│   │   ├── core/                         # 核心配置
│   │   ├── models/                       # 数据模型
│   │   ├── services/                     # 业务服务
│   │   ├── tasks/                        # Celery 任务
│   │   └── schemas/                      # Pydantic schemas
│   │
│   └── 📁 tests/                         # 测试文件
│       ├── __init__.py
│       └── test_storage.py
│
└── 📁 frontend/                          # 前端应用
    ├── 📄 package.json                   # Node 依赖
    ├── 📄 vite.config.ts                 # Vite 配置
    │
    └── 📁 src/
        ├── main.ts                       # 入口文件
        ├── api/                          # API 调用
        ├── components/                   # 组件
        ├── views/                        # 页面
        └── router/                       # 路由
```

---

## 🎯 按角色查看

### 👨‍💼 项目经理 / 产品经理

**必读**：
1. [README.md](./README.md) - 了解项目概况
2. [FINAL_ACCEPTANCE_REPORT.md](./FINAL_ACCEPTANCE_REPORT.md) - 查看完成情况
3. [DEVELOPMENT_SUMMARY.md](./DEVELOPMENT_SUMMARY.md) - 了解开发进度

### 👨‍💻 开发者（新入职）

**推荐阅读顺序**：
1. [README.md](./README.md) - 项目概述
2. [QUICKSTART.md](./QUICKSTART.md) - 环境搭建
3. [backend/README.md](./backend/README.md) - 后端架构
4. [DEVELOPMENT_SUMMARY.md](./DEVELOPMENT_SUMMARY.md) - 技术细节

### 🧪 QA / 测试工程师

**推荐阅读顺序**：
1. [VERIFICATION_REPORT.md](./VERIFICATION_REPORT.md) - 测试清单
2. [QUICKSTART.md](./QUICKSTART.md) - 环境准备
3. [backend/README.md](./backend/README.md) - API 文档

### 🎓 学习者 / 贡献者

**推荐阅读顺序**：
1. [README.md](./README.md) - 项目介绍
2. [COMPLETION_REPORT.md](./COMPLETION_REPORT.md) - 开发过程
3. [.claude/plans/element-library-implementation.md](./.claude/plans/element-library-implementation.md) - 实施细节

---

## 🔍 按任务查看

### 🚀 我想快速启动项目

👉 [QUICKSTART.md](./QUICKSTART.md)

### 🐛 我遇到了问题

1. 查看 [QUICKSTART.md](./QUICKSTART.md) 的"常见问题"章节
2. 查看 [VERIFICATION_REPORT.md](./VERIFICATION_REPORT.md) 的验证清单
3. 查看 [FINAL_ACCEPTANCE_REPORT.md](./FINAL_ACCEPTANCE_REPORT.md) 的"已知问题"

### 📖 我想了解技术实现

1. [backend/README.md](./backend/README.md) - 后端架构和 API
2. [DEVELOPMENT_SUMMARY.md](./DEVELOPMENT_SUMMARY.md) - 技术选型
3. [COMPLETION_REPORT.md](./COMPLETION_REPORT.md) - 实现细节

### ✅ 我想进行测试验证

1. [VERIFICATION_REPORT.md](./VERIFICATION_REPORT.md) - 测试清单
2. [backend/README.md](./backend/README.md) - 运行测试

### 🤝 我想贡献代码

1. [README.md](./README.md) - 贡献指南
2. [DEVELOPMENT_SUMMARY.md](./DEVELOPMENT_SUMMARY.md) - 开发规范
3. [COMPLETION_REPORT.md](./COMPLETION_REPORT.md) - 技术债务

---

## 📞 获取帮助

- 📖 查看文档：本文件
- 🐛 报告问题：GitHub Issues
- 💬 讨论交流：GitHub Discussions
- 📧 联系作者：your.email@example.com

---

## 📝 文档更新日志

### 2026-08-18
- ✅ 创建项目所有核心文档
- ✅ 完成元素库模块开发
- ✅ 创建本导航文件

---

**提示**：所有文档都使用 Markdown 格式编写，可以在任何文本编辑器或 GitHub 中查看。
