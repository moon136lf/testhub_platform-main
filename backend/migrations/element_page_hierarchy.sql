-- Migration: page hierarchy (P3 workbench) — parent_id for page tree
-- Idempotent: safe to run multiple times.

ALTER TABLE page_repository ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES page_repository(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_page_repository_parent ON page_repository(parent_id);

COMMENT ON COLUMN page_repository.parent_id IS '父页面 ID（页面树层级，NULL=顶级）';
