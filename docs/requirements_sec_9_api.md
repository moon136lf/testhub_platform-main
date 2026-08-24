# 需求文档 §9 API设计

来源：docs/design-doc-raw.xml 提取

9.1 API概览
模块
端点前缀
数量
项目
/api/v1/projects
5
用例
/api/v1/cases
8
元素
/api/v1/elements
9
脚本
/api/v1/scripts
6
执行
/api/v1/executions
5
报告
/api/v1/reports
4
AI
/api/v1/ai
4
SSE
/api/sse
1
9.2 核心接口详细定义
##### 9.2.1 元素抓取
POST /api/v1/elements/fetch
请求体：
{
"project_id": "uuid",
"url": "https://example.com/login",
"username": "admin",
"password": "xxxxx"
}
响应体：
{
"code": 0,
"data": {
"session_id": "sse-xxx-xxx",
"elements": [
{
"id": "elem_001",
"type": "button",
"text": "登录",
"id_attr": "login-btn",
"class_attr": "btn-primary",
"xpath": "//button[@id='login-btn']",
"coords": {"x": 100, "y": 200, "width": 80, "height": 40}
}
],
"total": 53,
"screenshot_url": "/static/screenshots/xxx.png"
}
}
##### 9.2.2 元素一键入库
POST /api/v1/elements/batch-import
请求体：
{
"project_id": "uuid",
"page_id": "uuid",
"page_name": "登录页",
"page_url": "/login",
"element_ids": ["elem_001", "elem_002"],
"confirm": true
}
响应体：
{
"code": 0,
"data": {
"page_id": "uuid",
"imported": 10,
"failed": 0,
"element_ids": ["uuid1", "uuid2"]
}
}
##### 9.2.3 AI生成用例
POST /api/v1/cases/generate
请求体：
{
"project_id": "uuid",
"materials": {
"prd_url": "/uploads/prd_xxx.docx",
"design_url": "/uploads/design_xxx.pdf",
"text": "用户登录功能：支持用户名密码登录..."
},
"rules": {
"automation_thinking": true,
"boundary_value": true,
"scenario_analysis": true,
"equivalence_partition": true
},
"selected_points": ["point_001", "point_002"]
}
响应：SSE流推送（见6.1格式）
##### 9.2.4 脚本转换与执行
POST /api/v1/scripts/convert-and-run
请求体：
{
"case_ids": ["uuid1", "uuid2"],
"config": {
"headless": false,
"timeout": 60,
"max_failures": 8,
"ai_optimize": true
}
}
响应：SSE流推送
{
"timestamp": "2026-08-17T14:00:01Z",
"type": "system",
"stage": "convert_script",
"content": "正在转换用例 1/3：登录-正常登录",
"progress": 0.33,
"tokens_used": 1247
}
##### 9.2.5 AI诊断与修复
POST /api/v1/diagnostics/analyze
请求体：
{
"execution_id": "uuid",
"error_data": {
"step": "点击登录按钮",
"error_type": "locate_failed",
"error_msg": "Element not found: #login-btn",
"screenshot_url": "/static/screenshots/fail_xxx.png",
"dom_snapshot": "<html>...</html>",
"script_fragment": "await page.click('#login-btn')"
}
}
响应体：
{
"code": 0,
"data": {
"diagnosis": "定位器失效，页面ID已变更为 new-login-btn",
"suggestion": "更新定位器为 #new-login-btn",
"new_locator": "#new-login-btn",
"confidence": 0.92,
"apply_url": "/api/v1/diagnostics/apply"
}
}
##### 9.2.6 Token预警
GET /api/v1/tokens/status?project_id={uuid}
响应体：
{
"code": 0,
"data": {
"total_quota": 100000,
"used": 45672,
"remaining": 54328,
"percentage": 45.7,
"is_warning": false,
"warning_threshold": 10,
"recent_daily_avg": 3200,
"estimated_days_remaining": 17
}
}
当 percentage ≤ 10% 时，is_warning = true，前端自动弹窗预警。
第10章 核心流程时序图
