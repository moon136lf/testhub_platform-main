-- W3: case_version table (idempotent)
CREATE TABLE IF NOT EXISTS case_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    diff_summary TEXT,
    changed_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_case_version_case ON case_version(case_id);
CREATE INDEX IF NOT EXISTS idx_case_version_case_version ON case_version(case_id, version DESC);
