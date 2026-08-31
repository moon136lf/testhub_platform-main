-- W10: system settings tables (idempotent)
-- Creates: system_setting, test_env, token_quota, operation_log, ai_call_log
-- Note: category/value_type are VARCHAR + CHECK (not native PG enum) to match the
-- model's Enum(native_enum=False) and keep migration friction low.

-- 1. system_setting
CREATE TABLE IF NOT EXISTS system_setting (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(20) NOT NULL,
    key VARCHAR(100) NOT NULL,
    value TEXT,
    value_encrypted TEXT,
    value_type VARCHAR(20) DEFAULT 'string',
    is_secret BOOLEAN DEFAULT FALSE,
    description VARCHAR(500),
    updated_by VARCHAR(50),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_system_setting_category CHECK (category IN ('ai','runtime')),
    CONSTRAINT chk_system_setting_value_type CHECK (value_type IN ('string','int','float','bool','json'))
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_system_setting_category_key') THEN
    ALTER TABLE system_setting ADD CONSTRAINT uq_system_setting_category_key UNIQUE (category, key);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_system_setting_category ON system_setting(category);

-- 2. test_env
CREATE TABLE IF NOT EXISTS test_env (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL,
    url VARCHAR(500) NOT NULL,
    env_type VARCHAR(20) NOT NULL DEFAULT 'dev',
    status VARCHAR(20) DEFAULT 'active',
    credentials JSONB,
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_test_env_type ON test_env(env_type);

-- 3. token_quota
CREATE TABLE IF NOT EXISTS token_quota (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    total_quota INTEGER DEFAULT 100000,
    alert_threshold INTEGER DEFAULT 10,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_token_quota_project') THEN
    ALTER TABLE token_quota ADD CONSTRAINT uq_token_quota_project UNIQUE (project_id);
  END IF;
END $$;

-- 3a. default quota row for every existing project (idempotent)
INSERT INTO token_quota (id, project_id, total_quota, alert_threshold)
SELECT gen_random_uuid(), p.id, 100000, 10
FROM project p
WHERE NOT EXISTS (
  SELECT 1 FROM token_quota tq WHERE tq.project_id = p.id
);

-- 4. operation_log
CREATE TABLE IF NOT EXISTS operation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(100),
    detail JSONB,
    operator VARCHAR(50),
    ip VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_op_log_created ON operation_log(created_at);
CREATE INDEX IF NOT EXISTS idx_op_log_module ON operation_log(module);

-- 5. ai_call_log (model exists in execution.py:54, table never created before)
CREATE TABLE IF NOT EXISTS ai_call_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
    model VARCHAR(50) NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    tokens_cost NUMERIC(10,4) DEFAULT 0,
    stage VARCHAR(30) NOT NULL,
    status VARCHAR(20) DEFAULT 'success',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_project ON ai_call_log(project_id);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_created ON ai_call_log(created_at);
