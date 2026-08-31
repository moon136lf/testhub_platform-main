-- 012: code_scan 加进度字段（白盒扫描分阶段进度：10拉镜像/30 clone/30-90 semgrep/100 入库）
ALTER TABLE code_scan ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0;
ALTER TABLE code_scan ADD COLUMN IF NOT EXISTS stage VARCHAR(30);
