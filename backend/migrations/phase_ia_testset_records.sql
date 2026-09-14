-- IA改造 Task2: execution_record 关联测试集（幂等）
ALTER TABLE execution_record ADD COLUMN IF NOT EXISTS test_set_id UUID REFERENCES test_set(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_exec_record_test_set ON execution_record(test_set_id);
