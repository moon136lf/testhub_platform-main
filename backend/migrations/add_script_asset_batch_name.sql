-- script_asset 来源批次名 (case_batch 冗余). Idempotent.
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS batch_name VARCHAR(200);
