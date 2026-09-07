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

-- parent_id 约束统一为 ON DELETE SET NULL（删父页面保留子页面），幂等重建
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'page_repository'::regclass
      AND confrelid = 'page_repository'::regclass
      AND contype = 'f'
      AND pg_get_constraintdef(oid) LIKE '%parent_id%';
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE page_repository DROP CONSTRAINT %I', fk_name);
    END IF;
    ALTER TABLE page_repository
        ADD CONSTRAINT page_repository_parent_id_setnull_fkey
        FOREIGN KEY (parent_id) REFERENCES page_repository(id) ON DELETE SET NULL;
END
$$;
