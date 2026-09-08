# 元素库 P3 工作台打磨轮 + 遗留问题清单（2026-09-08 深夜存档）

> 用户密集验收反馈轮。全部已提交（9369a00 等），658 tests passed，build 绿。**明日用户逐项验证。**

## 本轮已完成

1. **重复直播区删除**：tab 化重构后残留的第二套 live-feed+结果区（L130-216）已删除——用户截图"两个抓取进度直播"根因
2. **入库重复计数提示**：batch_import_elements 返回 (objects, skipped_duplicates)；/import 与 capture-session import 的 failed_count=skipped；前端 toast 显示"N 条重复未入库"。189→74 的谜底：element_id 按 text 生成，表格 '--'×20、'查看'×10 等大量同文本元素去重所致
3. **入库弹窗**：宽 700→900px（策略预览看不全）
4. **已入库元素列表**：加序号列（全页序号，el-table type=index）
5. **URL 预填**：会话工作台选项目后自动填 target_url
6. **别名默认中文**：TYPE_CN 映射（按钮1/输入框2...），用户填 > aria_label > text > 中文序号；两个 import 映射都传 element_name=aria_label
7. **pick-element 诊断日志**：miss 时记录实际视口/滚动位置
8. **headed 窗口大小稳定**：headed no_viewport 跟随真实窗口（用户可最大化），headless 固定 1920；点选坐标用 status 返回的动态 viewport
9. **SemanticInfo.context 可选** + batch_import 写 context（列表 500 修复）
10. **Playwright 全链路桥接**：capture/pick/status 的所有调用经 Proactor 桥接线程（uvicorn --reload 的 Selector loop 无子进程权限）

## ⚠️ 用户反馈未完成项（明日优先）

1. **元素列表可编辑别名**（一次性抓取结果区）——用户验收时要能改名再入库。注意：入库弹窗里已有别名编辑列（element_name），确认用户指的是哪一层
2. **置信度全是 0**：导入写死 0，设计是自愈计数。用户期望初始值=抓取定位器最高分。改法：batch_import_elements 里 `confidence=max(strategies score)//10`（可选）
3. **会话式抓取加调试模式+截图高亮框**（ElementHighlight 复用到工作台）
4. **SSE 直播加回会话式 tab**（capture 端点同步返回，需改异步+事件推送，或前端 loading 态模拟）
5. **pick-element miss 根因**：已加诊断日志（viewport/scroll），等用户复现提供日志。可能原因：截图缩放后点击坐标 vs elementFromPoint 视口坐标偏差、页面滚动
6. **入库确认弹框"选父级层级"**：parent_id 已有 schema/树端点，入库弹窗缺父页面下拉
7. **F12 检查模式方案**（用户问询）：技术上=CDP session 或 playwright locator 高亮注入脚本，比 elementFromPoint 更精准（显示完整路径）。可行性高，工作量中等，待用户拍板

## 测试状态
658 passed / build 绿。工作区仅剩另一会话的 sse.py/json_utils/logging_setup 等文件（勿动）。
