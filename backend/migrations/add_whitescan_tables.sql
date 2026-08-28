-- #9: whitescan tables (code_scan + code_issue) + test_case.source_issue_id
-- Idempotent.
CREATE TABLE IF NOT EXISTS code_scan (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
    repo_url VARCHAR(500) NOT NULL,
    branch VARCHAR(100) DEFAULT 'main',
    status VARCHAR(20) DEFAULT 'scanning',
    total_issues INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    mid_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    error_msg TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_code_scan_project ON code_scan(project_id);

CREATE TABLE IF NOT EXISTS code_issue (
    id UUID PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES code_scan(id) ON DELETE CASCADE,
    severity VARCHAR(10) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    line_no INTEGER,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    ai_suggestion JSONB,
    example_code TEXT,
    status VARCHAR(20) DEFAULT 'open',
    source_commit VARCHAR(100),
    fingerprint VARCHAR(200),
    case_outdated BOOLEAN DEFAULT FALSE,
    handled_by VARCHAR(50),
    handled_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_code_issue_scan ON code_issue(scan_id);
CREATE INDEX IF NOT EXISTS idx_code_issue_fingerprint ON code_issue(fingerprint);

ALTER TABLE test_case ADD COLUMN IF NOT EXISTS source_issue_id UUID REFERENCES code_issue(id) ON DELETE SET NULL;
