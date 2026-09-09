-- Migration: for_regression flag and source_type (phase3 regression ownership)
-- Idempotent

ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS for_regression BOOLEAN DEFAULT FALSE;
ALTER TABLE test_case ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) DEFAULT 'ai_gen';
CREATE INDEX IF NOT EXISTS idx_script_asset_for_regression ON script_asset(for_regression);
