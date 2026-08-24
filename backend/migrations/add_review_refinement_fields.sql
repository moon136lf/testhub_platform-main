-- W5: review & refinement fields (idempotent)
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending';
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS review_comment TEXT;
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS feasibility_level VARCHAR(20);
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS cannot_automate_reason VARCHAR(200);
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS refinement_report JSONB;
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS refined_at TIMESTAMP;
