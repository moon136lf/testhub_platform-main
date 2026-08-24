-- W6: test_point.status enum normalize (idempotent)
-- pending 保留；approved -> selected（已勾选）；rejected -> pending（待勾选，保守归并）
UPDATE test_point SET status = 'selected' WHERE status = 'approved';
UPDATE test_point SET status = 'pending' WHERE status = 'rejected';
