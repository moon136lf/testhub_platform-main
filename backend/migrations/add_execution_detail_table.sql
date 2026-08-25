-- #5a: execution_detail table (req §4 ER graph, DDL omitted in spec)
-- Idempotent.
CREATE TABLE IF NOT EXISTS execution_detail (
    id UUID PRIMARY KEY,
    execution_record_id UUID NOT NULL REFERENCES execution_record(id) ON DELETE CASCADE,
    script_id UUID REFERENCES script_asset(id) ON DELETE SET NULL,
    case_id UUID REFERENCES test_case(id) ON DELETE SET NULL,
    step INTEGER,
    action VARCHAR(50),
    status VARCHAR(20) NOT NULL,
    error_type VARCHAR(30),
    error_msg TEXT,
    stack_trace TEXT,
    screenshot_url TEXT,
    dom_snapshot TEXT,
    heal_status VARCHAR(20) DEFAULT 'none',
    heal_log JSONB,
    duration_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exec_detail_record ON execution_detail(execution_record_id);
