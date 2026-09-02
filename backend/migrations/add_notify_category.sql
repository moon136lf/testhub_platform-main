-- notify webhook 配置：扩展 system_setting.category 枚举加 'notify'
-- 幂等：先删 CHECK 再重建（PG CHECK 无 IF NOT EXISTS，用条件判断）

ALTER TABLE system_setting DROP CONSTRAINT IF EXISTS chk_system_setting_category;
ALTER TABLE system_setting ADD CONSTRAINT chk_system_setting_category
    CHECK (category IN ('ai','runtime','notify'));
