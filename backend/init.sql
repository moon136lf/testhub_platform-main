-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create project table
CREATE TABLE IF NOT EXISTS project (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL,
    code VARCHAR(20) NOT NULL UNIQUE,
    description VARCHAR(500),
    target_url VARCHAR(500) NOT NULL DEFAULT 'http://localhost:81',
    status VARCHAR(10) DEFAULT 'active',
    created_by VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_project_code ON project(code);
CREATE INDEX IF NOT EXISTS idx_project_status ON project(status) WHERE is_deleted = FALSE;

-- Insert default project
INSERT INTO project (name, code, description, target_url, created_by)
VALUES ('默认项目', 'DEFAULT', 'MoonTest默认测试项目', 'http://localhost:81', 'system')
ON CONFLICT (code) DO NOTHING;
