-- #4: script_asset extension + convert_session table
-- Idempotent.

-- 1. script_asset add columns
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS project_id UUID;
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS name VARCHAR(100);
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS description VARCHAR(500);
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS step_mapping JSONB;
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS locator_source VARCHAR(20) DEFAULT 'none_draft';
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS ai_diagnosis JSONB;

-- backfill project_id from case's project (for existing rows)
UPDATE script_asset sa
SET project_id = (SELECT tc.project_id FROM test_case tc WHERE tc.id = sa.case_id)
WHERE sa.project_id IS NULL;

ALTER TABLE script_asset ALTER COLUMN project_id SET NOT NULL;

-- backfill name from source case (req: 脚本名称继承用例名)
UPDATE script_asset sa
SET name = (SELECT tc.name FROM test_case tc WHERE tc.id = sa.case_id)
WHERE sa.name IS NULL;

ALTER TABLE script_asset ALTER COLUMN name SET NOT NULL;

-- FK: script_asset.project_id -> project.id (model declares ondelete CASCADE)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'fk_script_asset_project' AND table_name = 'script_asset'
  ) THEN
    ALTER TABLE script_asset
      ADD CONSTRAINT fk_script_asset_project
      FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_script_asset_project ON script_asset(project_id);
CREATE INDEX IF NOT EXISTS idx_script_asset_case ON script_asset(case_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_script_asset_project_name') THEN
    ALTER TABLE script_asset ADD CONSTRAINT uq_script_asset_project_name UNIQUE (project_id, name);
  END IF;
END$$;

-- 2. convert_session
CREATE TABLE IF NOT EXISTS convert_session (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    case_ids JSONB NOT NULL,
    ai_optimize BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'active',
    progress NUMERIC(5,2) DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_convert_session_project ON convert_session(project_id);
