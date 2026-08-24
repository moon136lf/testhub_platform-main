"""
Migration: 新增 self_heal_cache 表 + 扩展 change_detection 聚合字段 (P1 #8/#9)

幂等：可重复执行。
前置条件：page_repository / element_repository / fetch_history / change_detection 已存在。
"""

-- ============================================================
-- 1. 扩展 change_detection 表：补齐聚合字段 (ELEM-05/06/07)
-- ============================================================

DO $$
BEGIN
    -- project_id（聚合记录所属项目，便于项目级查询）
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'project_id'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN project_id UUID;
        -- 回填：通过 page_id 关联 page_repository 填充 project_id
        UPDATE change_detection cd
        SET project_id = p.project_id
        FROM page_repository p
        WHERE cd.page_id = p.id AND cd.project_id IS NULL;
        ALTER TABLE change_detection ALTER COLUMN project_id SET NOT NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'base_fetch_id'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN base_fetch_id UUID REFERENCES fetch_history(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'current_fetch_id'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN current_fetch_id UUID REFERENCES fetch_history(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'added'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN added JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'removed'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN removed JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'modified'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN modified JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'added_count'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN added_count INTEGER DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'removed_count'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN removed_count INTEGER DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'modified_count'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN modified_count INTEGER DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'affected_script_count'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN affected_script_count INTEGER DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'fixed_at'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN fixed_at TIMESTAMPTZ;
    END IF;
END $$;

-- affected_scripts 已存在则改为 JSONB（原模型定义即 JSONB），若无则补建
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'affected_scripts'
    ) THEN
        ALTER TABLE change_detection ADD COLUMN affected_scripts JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

-- impact_level 默认值补齐为 'low'
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'change_detection' AND column_name = 'impact_level'
    ) THEN
        ALTER TABLE change_detection ALTER COLUMN impact_level SET DEFAULT 'low';
    END IF;
END $$;

-- 索引
CREATE INDEX IF NOT EXISTS idx_change_detection_project ON change_detection (project_id);
CREATE INDEX IF NOT EXISTS idx_change_detection_status ON change_detection (status);
CREATE INDEX IF NOT EXISTS idx_change_detection_check_time ON change_detection (check_time);

-- 注释
COMMENT ON COLUMN change_detection.project_id IS '所属项目ID';
COMMENT ON COLUMN change_detection.base_fetch_id IS '基准抓取历史ID（上一次）';
COMMENT ON COLUMN change_detection.current_fetch_id IS '当前抓取历史ID';
COMMENT ON COLUMN change_detection.added IS '新增元素列表 [{element_id, element_name, locator}]';
COMMENT ON COLUMN change_detection.removed IS '消失元素列表 [{element_id, element_name, locator}]';
COMMENT ON COLUMN change_detection.modified IS '变更元素列表 [{element_id, element_name, old_locator, new_locator}]';
COMMENT ON COLUMN change_detection.added_count IS '新增数量';
COMMENT ON COLUMN change_detection.removed_count IS '消失数量';
COMMENT ON COLUMN change_detection.modified_count IS '变更数量';
COMMENT ON COLUMN change_detection.affected_scripts IS '受影响的脚本列表';
COMMENT ON COLUMN change_detection.affected_script_count IS '受影响脚本数量';
COMMENT ON COLUMN change_detection.fixed_at IS '一键更新定位器完成时间';

-- 旧的逐条字段 change_type/element_id/element_name/old_locator/new_locator 保留以兼容历史数据，
-- 新逻辑改用 added/removed/modified 聚合字段。

-- ============================================================
-- 2. 新建 self_heal_cache 表 (§8.2.8 自愈缓存)
-- ============================================================

CREATE TABLE IF NOT EXISTS self_heal_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    element_id VARCHAR(100) NOT NULL,
    element_db_id UUID REFERENCES element_repository(id) ON DELETE CASCADE,
    healed_locator JSONB NOT NULL,
    heal_strategy VARCHAR(50),
    confidence INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    original_locator JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_self_heal_cache_element_id ON self_heal_cache (element_id);
CREATE INDEX IF NOT EXISTS idx_self_heal_cache_element_db_id ON self_heal_cache (element_db_id);
CREATE INDEX IF NOT EXISTS idx_self_heal_cache_confidence ON self_heal_cache (confidence);

COMMENT ON TABLE self_heal_cache IS '自愈缓存表 - 记录元素定位器的自愈历史与置信度';
COMMENT ON COLUMN self_heal_cache.element_id IS '关联元素的 element_id（业务标识）';
COMMENT ON COLUMN self_heal_cache.element_db_id IS '关联元素记录ID';
COMMENT ON COLUMN self_heal_cache.healed_locator IS '自愈定位器 {type, value, score}';
COMMENT ON COLUMN self_heal_cache.heal_strategy IS '自愈策略：semantic/coords/text/aria';
COMMENT ON COLUMN self_heal_cache.confidence IS '置信度，命中+1/失效-1，>=3 回写仓库';
COMMENT ON COLUMN self_heal_cache.success_count IS '成功命中次数';
COMMENT ON COLUMN self_heal_cache.failure_count IS '连续失败次数（成功时归零）';
COMMENT ON COLUMN self_heal_cache.original_locator IS '原失败定位器';
