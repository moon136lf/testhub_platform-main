-- 阶段10 结构调整：execution_record 软删 + execution_bug 缺陷表
-- Idempotent. Run: psql -h localhost -p 5433 -U moontest -d moontest -f migrations/phase10_execution_bugs.sql

ALTER TABLE execution_record ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN execution_record.is_deleted IS '软删标记（阶段10）';

CREATE TABLE IF NOT EXISTS execution_bug (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id UUID NOT NULL REFERENCES execution_record(id) ON DELETE CASCADE,
    detail_id UUID REFERENCES execution_detail(id) ON DELETE SET NULL,
    step_snapshot JSONB,
    screenshot_url TEXT,
    error_stack TEXT,
    ai_diagnosis TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exec_bug_record ON execution_bug(record_id);
COMMENT ON TABLE execution_bug IS '缺陷记录表——失败执行自动生成 bug 行（阶段10）';
