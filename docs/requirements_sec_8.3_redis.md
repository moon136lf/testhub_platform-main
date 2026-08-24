# 需求文档 §8.3 Redis缓存设计

来源：docs/design-doc-raw.xml 提取

8.3 Redis缓存设计
Key模式
类型
TTL
说明
来源
session:{user_id}
Hash
2h
用户会话信息
【deepseek】
page_repo:{project_id}:{url_path}
Hash
永久
页面仓库缓存
【deepseek】
element:{page_id}:{alias}
Hash
永久
元素定位缓存
【deepseek】
heal_cache:{element_id}
Hash
动态(30d/1h)
自愈定位器缓存
【deepseek】
execution:{exec_id}
Hash
1h
执行任务状态
【deepseek】
sse:{session_id}
List
30min
SSE消息暂存
【deepseek】
task:queue:{queue_name}
List
—
Celery任务队列
【deepseek】
token:counter:{project_id}
Hash
—
Token累计计数
【deepseek】
第9章 接口设计
