-- Migration: test_set table (phase2 execution planning layer)
-- Idempotent.

CREATE TABLE IF NOT EXISTS test_set (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    case_ids JSONB NOT NULL DEFAULT '[]',
    description VARCHAR(500),
    last_run_at TIMESTAMPTZ,
    last_pass_rate NUMERIC(5,2) DEFAULT 0,
    last_exec_id VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    created_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_test_set_project_name UNIQUE (project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_test_set_project ON test_set(project_id);
