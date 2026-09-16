-- Migration: static scan component hash table (source-code locator chain)
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS static_scan_component (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    scan_id UUID NOT NULL REFERENCES code_scan(id) ON DELETE CASCADE,
    file_path VARCHAR(500) NOT NULL,
    component_name VARCHAR(200),
    content_hash VARCHAR(64),
    page_id UUID REFERENCES page_repository(id) ON DELETE SET NULL,
    element_count INTEGER DEFAULT 0,
    ai_generated BOOLEAN DEFAULT FALSE,
    reused BOOLEAN DEFAULT FALSE,
    ai_failed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_static_scan_component_project ON static_scan_component(project_id);
COMMENT ON TABLE static_scan_component IS '静态扫描组件hash表：重扫hash未变跳过AI生成复用定位器';
