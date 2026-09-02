-- 存量无批次用例清理. 先查数量并经用户确认后执行:
--   SELECT COUNT(*) FROM test_case WHERE batch_id IS NULL AND is_deleted = FALSE;
UPDATE test_case SET is_deleted = TRUE WHERE batch_id IS NULL AND is_deleted = FALSE;
