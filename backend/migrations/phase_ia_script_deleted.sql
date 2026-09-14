-- IA改造T1：script_asset 软删标记
-- Idempotent. Run: psql -h localhost -p 5433 -U moontest -d moontest -f migrations/phase_ia_script_deleted.sql

ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN script_asset.is_deleted IS '软删标记（IA改造T1）';
