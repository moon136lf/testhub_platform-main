-- 用例生成批次 (case_batch) + test_case.batch_id. Idempotent.
CREATE TABLE IF NOT EXISTS case_batch (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    batch_name VARCHAR(200) NOT NULL,
    batch_type VARCHAR(20) NOT NULL,
    source_id UUID,
    case_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_case_batch_project_name UNIQUE (project_id, batch_name)
);
CREATE INDEX IF NOT EXISTS idx_case_batch_project ON case_batch(project_id);

ALTER TABLE test_case ADD COLUMN IF NOT EXISTS batch_id UUID REFERENCES case_batch(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_test_case_batch ON test_case(batch_id);
