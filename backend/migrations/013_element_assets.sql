-- Migration: element assets restructure (page tree + global elements + recycle)
-- Idempotent: safe to run multiple times.

-- 页面树层级
ALTER TABLE page_repository ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES page_repository(id) ON DELETE CASCADE;
ALTER TABLE page_repository ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_page_repository_parent ON page_repository(parent_id);

-- 全局元素 + 回收站时间
ALTER TABLE element_repository ADD COLUMN IF NOT EXISTS scope VARCHAR(20) DEFAULT 'page';
ALTER TABLE element_repository ALTER COLUMN page_id DROP NOT NULL;
ALTER TABLE element_repository ADD COLUMN IF NOT EXISTS recycled_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_element_repository_scope ON element_repository(scope);

COMMENT ON COLUMN element_repository.scope IS 'page=页面级(挂page_id) global=全局共享(导航/菜单,page_id为空)';
COMMENT ON COLUMN element_repository.recycled_at IS '软删进回收站时间; status=deleted 且 30天可恢复';
