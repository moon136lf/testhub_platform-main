-- 测试点关联生成会话：第五步"只显示本次会话识别的测试点"
-- 幂等：IF NOT EXISTS

ALTER TABLE test_point ADD COLUMN IF NOT EXISTS session_id UUID REFERENCES generation_session(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_test_point_session ON test_point(session_id);
