# 需求文档 §11 详细设计

来源：docs/design-doc-raw.xml 提取

11.1 自愈引擎详细设计（整合增强）
挂载点：转换服务→脚本执行时，Playwright动作抛出定位失败异常触发。
技术选型：playwright-healer（PyPI，MIT，Python≥3.9，版本1.0+）
自愈管线（状态机）
Playwright action 抛错(quick_timeout=500ms)
│
├─[0] 试原定位符 ──命中──▶ 返回 Locator
│
└─[1] 查缓存 ──命中且有效──▶ 校验──▶ 返回
│缓存失效
├─[2] 启发式(免费~0ms)
│   ├ ID后缀替换/Class Jaccard/文本/ARIA role
│   └命中──▶ 缓存+置信度+1──▶ 返回
├─[3] DOM模糊(免费~50ms, rapidfuzz)
│   └命中──▶ 缓存+置信度+1──▶ 返回
├─[4] AI DOM(付费~1-3s, provider链)
│   └命中(置信度≥阈值)──▶ 缓存+置信度+1──▶ 返回
├─[5] 视觉模型(付费~2-5s)
│   └命中──▶ 缓存+置信度+1──▶ 返回
└─ 失败──▶ ElementNotFoundError
自愈管线分级
优先级
策略
成本
响应时间
预期命中率
来源
1
启发式预检（多定位策略链降级）
免费
~0ms
~70%
【deepseek】
2
DOM模糊匹配（文本/属性近似）
免费
~50ms
~15%
【deepseek】
3
AI DOM重定位（LLM分析页面结构）
付费
~1-3s
~10%
【deepseek】
4
视觉模型兜底（截图+CV定位）
付费
~2-5s
~5%
【deepseek】
置信度与缓存规则
事件
动作
TTL
来源
自愈成功
写缓存，confidence+1
稳定30天/失效1小时
【deepseek】
缓存命中
confidence+1
—
【deepseek】
缓存失效(校验失败)
confidence-1，标记miss
—
【deepseek】
连续3次失败
删除缓存，重新自愈
—
【专家·关忆北】
confidence≥3
回写全局页面对象仓库
永久
【deepseek】
provider兜底链（整合补充）
优先级
provider
成本
说明
1
千问/GLM（本地配置）
低
默认
2
Groq（免费）
免费
兜底
3
OpenAI/Anthropic
中
视觉模型兜底
策略配置
策略
触发链
适用
SMART
启发式→DOM模糊→AI DOM
默认，CI
HEURISTIC_ONLY
仅启发式
本地无AI配置
DOM_ONLY
DOM模糊
CI成本敏感
VISUAL_ONLY
视觉模型
高视觉UI
FULL
全链含视觉
最大自愈力
PARALLEL
并行各策略
速度优先
与已有机制分工
机制
定位
来源
脚本内置多级定位降级
第一道防线，免费快速
【提供】
页面记忆/失败回喂
生成期改进，沉淀失败经验
【提供】
自愈引擎
运行期实时修复，缓存复用，达标回写
【deepseek·L06】
11.2 全局页面对象仓库设计（整合补充）
两级存储模型
page_object
├── page_path: "/login"
│   ├── element_key: "username_input"
│   │   └── locator: {id,css,xpath,text,role}
│   ├── element_key: "password_input"
│   └── element_key: "login_button"
└── page_path: "/dashboard"
├── element_key: "device_table"
└── element_key: "refresh_button"
写入路径
路径
说明
来源
元素抓取入库
手动勾选入库，source=manual
【deepseek】
AI转换生成
未命中仓库→AI生成→人工确认→入库，source=ai_generated
【deepseek】
自愈回写
confidence≥3→自动回写，source=self_heal
【deepseek】
读取优先级：AI转换脚本时 > 元素抓取入库 > 自愈缓存校验。
硬性规则
规则
说明
来源
两级存储
强制"页面-元素"两级，元素必须挂载页面下，禁止用例级存储定位
【deepseek·L03】
优先查询
AI转换脚本时第一优先级查询仓库
【deepseek】
即时生成入库
仓库无该元素→AI即时生成→强制人工确认后入库
【deepseek】
自愈回写
自愈成功定位器置信度≥3后自动回写仓库
【deepseek】
11.3 SSE文字直播设计
通道：GET /api/sse/stream/{session_id}（EventSource长连接）
消息分发：见第6章6.1.2覆盖场景表。
断线重连：客户端自动重连+last_event_id续传，连接保持30分钟，空闲超时5分钟。
11.4 Token成本管理设计
采集点：大模型网关每次调用记录tokens_used（prompt+completion），写入ai_call_log表。
数据模型：token_usage（project_id, stage, tokens_used, model, cost, created_at）、token_quota（project_id, total_quota, used_quota, alert_threshold）。
预警：剩余<10%总额度→前端弹窗+顶部横幅。
11.5 幻觉/冲突检测设计
管线：见第6章6.5节。
规则引擎：禁用词检测+前置缺失检测+语义相似度比对（阈值0.6）。
处理：标记项状态置"待复核"，用户复核后"确认定稿"或"修改重新生成"。
11.6 协议模拟器设计
架构：独立服务，不直接暴露公网。
MQTT模拟：设备上行MQTT Publish到指定topic；平台下行订阅topic校验设备ACK；支持QoS 0/1/2。
HTTP模拟：设备上行HTTP POST；平台下行回调URL校验ACK。
模板库：MVP阶段空模板+手动录入；后续预置常用设备模板。
第12章 异常处理与部署
