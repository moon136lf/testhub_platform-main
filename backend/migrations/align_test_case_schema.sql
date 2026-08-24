-- W2: align test_case schema (enums, steps JSONB, UNIQUE, indexes)
-- Idempotent: safe on fresh + existing DBs.

-- 1. case_type normalize: legacy -> functional/interface_case
UPDATE test_case SET case_type = 'functional'
  WHERE case_type IN ('performance','security','compatibility','usability');
UPDATE test_case SET case_type = 'interface_case'
  WHERE case_type = 'api';

-- 2. automation_status normalize: cannot_automate -> partial_automated
UPDATE test_case SET automation_status = 'partial_automated'
  WHERE automation_status = 'cannot_automate';

-- 3. steps key seq -> step (JSONB array elements)
UPDATE test_case
SET steps = (
  SELECT jsonb_agg(
    CASE WHEN elem ? 'seq'
         THEN (elem - 'seq') || jsonb_build_object('step', elem->'seq')
         ELSE elem END
  )
  FROM jsonb_array_elements(steps) AS t(elem)
)
WHERE steps IS NOT NULL AND jsonb_typeof(steps) = 'array';

-- 4. steps column type JSON -> JSONB (idempotent: skip if already JSONB)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='test_case' AND column_name='steps'
      AND data_type <> 'jsonb'
  ) THEN
    ALTER TABLE test_case ALTER COLUMN steps TYPE JSONB USING steps::jsonb;
  END IF;
END$$;

-- 5. UNIQUE(project_id, name): dedupe before adding constraint
DELETE FROM test_case a USING test_case b
  WHERE a.id > b.id AND a.project_id = b.project_id AND a.name = b.name;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_test_case_project_name'
  ) THEN
    ALTER TABLE test_case ADD CONSTRAINT uq_test_case_project_name UNIQUE (project_id, name);
  END IF;
END$$;

-- 6. indexes
CREATE INDEX IF NOT EXISTS idx_test_case_project ON test_case(project_id);
CREATE INDEX IF NOT EXISTS idx_test_case_automation ON test_case(automation_status);

-- 7. #4: automation_status enum extended with 'converted' (已转脚本).
--    Column is VARCHAR (no DB-level CHECK constraint in original DDL), so no
--    ALTER needed for the enum itself — just documented here for operators.
--    Canonical values now: pending / converted / automated / partial_automated
--    (CASE-MGMT-04: 定稿→已转脚本→脚本运行通过→已自动化)
