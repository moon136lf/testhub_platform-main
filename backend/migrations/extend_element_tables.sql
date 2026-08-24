-- Migration: Extend element tables for multi-locator and healing
-- Date: 2026-08-18
-- Idempotent: safe to run multiple times.

-- ============================================================
-- Step 1: Extend page_repository table
-- ============================================================
-- Rename url_path -> page_url (if exists), then extend column types
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'page_repository' AND column_name = 'url_path'
    ) THEN
        ALTER TABLE page_repository RENAME COLUMN url_path TO page_url;
    END IF;
END $$;

ALTER TABLE page_repository
    ALTER COLUMN page_name TYPE VARCHAR(100),
    ALTER COLUMN page_url TYPE VARCHAR(500),
    ADD COLUMN IF NOT EXISTS last_fetch_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS created_by VARCHAR(50) DEFAULT 'system';

COMMENT ON COLUMN page_repository.page_name IS '页面名称';
COMMENT ON COLUMN page_repository.page_url IS '页面URL';
COMMENT ON COLUMN page_repository.screenshot_url IS '页面截图URL (MinIO)';
COMMENT ON COLUMN page_repository.element_count IS '该页面下元素数量';
COMMENT ON COLUMN page_repository.last_fetch_at IS '最后一次抓取时间';

-- ============================================================
-- Step 2: Extend element_repository table
-- ============================================================
-- 2a: Add NEW columns first (without NOT NULL yet for project_id/element_id/locator_strategies)
ALTER TABLE element_repository
    ADD COLUMN IF NOT EXISTS project_id UUID,
    ADD COLUMN IF NOT EXISTS element_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS element_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS element_text VARCHAR(200),
    ADD COLUMN IF NOT EXISTS locator_strategies JSONB,
    ADD COLUMN IF NOT EXISTS semantic_info JSONB,
    ADD COLUMN IF NOT EXISTS position_x INTEGER,
    ADD COLUMN IF NOT EXISTS position_y INTEGER,
    ADD COLUMN IF NOT EXISTS attributes JSONB,
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS created_by VARCHAR(50) DEFAULT 'system',
    ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP WITH TIME ZONE;

-- 2b: MIGRATE DATA from old columns to new columns BEFORE dropping old columns.
--     Guard each UPDATE with existence checks so the migration is idempotent.
DO $$
BEGIN
    -- alias -> element_id / element_name
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'element_repository' AND column_name = 'alias'
    ) THEN
        UPDATE element_repository
        SET element_id = COALESCE(element_id, LEFT(alias, 100)),
            element_name = COALESCE(element_name, LEFT(alias, 100))
        WHERE alias IS NOT NULL;
    END IF;

    -- display_text -> element_text
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'element_repository' AND column_name = 'display_text'
    ) THEN
        UPDATE element_repository
        SET element_text = COALESCE(element_text, LEFT(display_text, 200))
        WHERE display_text IS NOT NULL;
    END IF;

    -- coord_x / coord_y -> position_x / position_y
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'element_repository' AND column_name = 'coord_x'
    ) THEN
        UPDATE element_repository
        SET position_x = COALESCE(position_x, coord_x)
        WHERE coord_x IS NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'element_repository' AND column_name = 'coord_y'
    ) THEN
        UPDATE element_repository
        SET position_y = COALESCE(position_y, coord_y)
        WHERE coord_y IS NOT NULL;
    END IF;

    -- locator_chain -> locator_strategies (wrap old chain into new structure if compatible)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'element_repository' AND column_name = 'locator_chain'
    ) THEN
        UPDATE element_repository
        SET locator_strategies = COALESCE(
            locator_strategies,
            CASE
                WHEN locator_chain IS NULL THEN '{"strategies": []}'::jsonb
                -- If locator_chain looks like a list, wrap it under "strategies"
                WHEN jsonb_typeof(locator_chain::jsonb) = 'array'
                    THEN jsonb_build_object('strategies', locator_chain::jsonb)
                -- If locator_chain already has a "strategies" key, keep as-is
                WHEN (locator_chain::jsonb) ? 'strategies'
                    THEN locator_chain::jsonb
                -- Otherwise wrap under "strategies" as a single-element list
                ELSE jsonb_build_object('strategies', jsonb_build_array(locator_chain::jsonb))
            END
        )
        WHERE locator_chain IS NOT NULL;
    END IF;
END $$;

-- 2c: Backfill project_id via page_repository join, then enforce NOT NULL.
--     Existing rows get project_id from their page; remaining NULLs get a sentinel
--     UUID to satisfy NOT NULL (orphan rows without a page are extremely unlikely
--     because page_id is NOT NULL with FK CASCADE).
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    UPDATE element_repository e
    SET project_id = p.project_id
    FROM page_repository p
    WHERE e.project_id IS NULL
      AND e.page_id = p.id;

    -- Fill any remaining NULL project_id with a sentinel to satisfy NOT NULL.
    -- (Should not normally happen, but prevents migration failure on orphan rows.)
    UPDATE element_repository
    SET project_id = '00000000-0000-0000-0000-000000000000'::uuid
    WHERE project_id IS NULL;

    SELECT COUNT(*) INTO orphan_count
    FROM element_repository
    WHERE project_id = '00000000-0000-0000-0000-000000000000'::uuid;

    IF orphan_count > 0 THEN
        RAISE NOTICE 'Found % orphan element_repository rows with no matching page_repository; filled project_id with sentinel UUID.', orphan_count;
    END IF;
END $$;

-- 2d: Backfill element_id / locator_strategies for any remaining NULLs
UPDATE element_repository
SET element_id = COALESCE(element_id, 'elem_' || SUBSTRING(id::text, 1, 8))
WHERE element_id IS NULL;

UPDATE element_repository
SET locator_strategies = COALESCE(locator_strategies, '{"strategies": []}'::jsonb)
WHERE locator_strategies IS NULL;

-- 2e: Enforce NOT NULL + defaults on the newly populated columns
ALTER TABLE element_repository
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN element_id SET NOT NULL,
    ALTER COLUMN locator_strategies SET NOT NULL,
    ALTER COLUMN locator_strategies SET DEFAULT '{"strategies": []}'::jsonb;

-- 2f: Add FK constraint on project_id (idempotent via DO block)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'element_repository_project_id_fkey'
    ) THEN
        ALTER TABLE element_repository
            ADD CONSTRAINT element_repository_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE RESTRICT;
    END IF;
END $$;

-- 2g: Drop OLD columns only after data migration is complete
ALTER TABLE element_repository
    DROP COLUMN IF EXISTS alias,
    DROP COLUMN IF EXISTS display_text,
    DROP COLUMN IF EXISTS coord_x,
    DROP COLUMN IF EXISTS coord_y,
    DROP COLUMN IF EXISTS locator_chain;

-- 2h: Widen element_type and status columns
ALTER TABLE element_repository
    ALTER COLUMN element_type TYPE VARCHAR(50);

ALTER TABLE element_repository
    ALTER COLUMN status TYPE VARCHAR(20);

-- 2i: Add unique constraint (page_id, element_id) - idempotent
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_element_repository_page_element'
    ) THEN
        ALTER TABLE element_repository
            ADD CONSTRAINT uq_element_repository_page_element UNIQUE (page_id, element_id);
    END IF;
END $$;

-- 2j: Add indexes (idempotent)
CREATE INDEX IF NOT EXISTS idx_element_repository_project_id ON element_repository(project_id);
CREATE INDEX IF NOT EXISTS idx_element_repository_element_id ON element_repository(element_id);

-- 2k: Add column comments
COMMENT ON COLUMN element_repository.element_id IS '元素唯一标识';
COMMENT ON COLUMN element_repository.element_name IS '元素名称（用户可编辑）';
COMMENT ON COLUMN element_repository.element_type IS 'button/input/link/select/other';
COMMENT ON COLUMN element_repository.element_text IS '元素显示文本';
COMMENT ON COLUMN element_repository.locator_strategies IS '多层定位器数组';
COMMENT ON COLUMN element_repository.semantic_info IS '元素语义信息';
COMMENT ON COLUMN element_repository.position_x IS '元素X坐标';
COMMENT ON COLUMN element_repository.position_y IS '元素Y坐标';
COMMENT ON COLUMN element_repository.width IS '元素宽度';
COMMENT ON COLUMN element_repository.height IS '元素高度';
COMMENT ON COLUMN element_repository.attributes IS '元素HTML属性';
COMMENT ON COLUMN element_repository.status IS 'active/deprecated/deleted';
COMMENT ON COLUMN element_repository.confidence IS '置信度 0-10';
COMMENT ON COLUMN element_repository.source IS 'manual/auto/healed';
COMMENT ON COLUMN element_repository.last_verified_at IS '最后验证时间';

-- ============================================================
-- Step 3: Create fetch_history table
-- ============================================================
CREATE TABLE IF NOT EXISTS fetch_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id UUID NOT NULL REFERENCES page_repository(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
    fetch_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    elements_found INTEGER DEFAULT 0,
    elements_imported INTEGER DEFAULT 0,
    screenshot_url VARCHAR(500),
    fetch_url VARCHAR(500),
    used_login BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    duration_seconds INTEGER,
    created_by VARCHAR(50) DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_fetch_history_page_id ON fetch_history(page_id);
CREATE INDEX IF NOT EXISTS idx_fetch_history_project_id ON fetch_history(project_id);

COMMENT ON COLUMN fetch_history.fetch_time IS '抓取时间';
COMMENT ON COLUMN fetch_history.elements_found IS '发现的元素数量';
COMMENT ON COLUMN fetch_history.elements_imported IS '实际入库的元素数量';
COMMENT ON COLUMN fetch_history.screenshot_url IS '本次抓取的截图URL';
COMMENT ON COLUMN fetch_history.fetch_url IS '抓取的URL';
COMMENT ON COLUMN fetch_history.used_login IS '是否使用了登录';
COMMENT ON COLUMN fetch_history.status IS 'success/failed/partial';
COMMENT ON COLUMN fetch_history.error_message IS '失败时的错误信息';
COMMENT ON COLUMN fetch_history.duration_seconds IS '抓取耗时（秒）';

-- ============================================================
-- Step 4: Create change_detection table
-- ============================================================
CREATE TABLE IF NOT EXISTS change_detection (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id UUID NOT NULL REFERENCES page_repository(id) ON DELETE CASCADE,
    check_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    change_type VARCHAR(20),
    element_id VARCHAR(100),
    element_name VARCHAR(100),
    old_locator JSONB,
    new_locator JSONB,
    affected_scripts JSONB,
    impact_level VARCHAR(20),
    status VARCHAR(20) DEFAULT 'pending',
    reviewed_by VARCHAR(50),
    reviewed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_change_detection_page_id ON change_detection(page_id);

COMMENT ON COLUMN change_detection.check_time IS '检测时间';
COMMENT ON COLUMN change_detection.change_type IS 'added/removed/modified';
COMMENT ON COLUMN change_detection.element_id IS '涉及的元素ID';
COMMENT ON COLUMN change_detection.element_name IS '元素名称';
COMMENT ON COLUMN change_detection.old_locator IS '旧定位器';
COMMENT ON COLUMN change_detection.new_locator IS '新定位器';
COMMENT ON COLUMN change_detection.affected_scripts IS '受影响的脚本列表';
COMMENT ON COLUMN change_detection.impact_level IS 'low/medium/high';
COMMENT ON COLUMN change_detection.status IS 'pending/reviewed/fixed';
COMMENT ON COLUMN change_detection.reviewed_by IS '审核人';
COMMENT ON COLUMN change_detection.reviewed_at IS '审核时间';
