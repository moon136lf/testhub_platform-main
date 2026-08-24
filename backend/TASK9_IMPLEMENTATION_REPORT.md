# Task 9: Database Model Extension - Implementation Report

**Task:** Extend database models for the element library module
**Date:** 2026-08-18 (updated 2026-08-20)
**Status:** DONE_WITH_CONCERNS

---

## Summary

Extended database models for the element library module supporting multi-layer locators,
semantic info for self-healing, fetch history, and change detection. After two rounds of
spec/code review, all identified issues have been fixed.

---

## Models (backend/app/models/element.py)

### PageRepository (extended)
- `page_url` VARCHAR(500) — renamed from `url_path` for plan consistency
- `last_fetch_at` — last fetch timestamp
- `created_by` — audit field
- Relationships: `elements`, `fetch_histories` with `lazy="selectin"` (async-safe)

### ElementRepository (extended)
- New identification: `element_id`, `element_name`, `element_text`
- `locator_strategies` JSONB — multi-locator array with scores
- `semantic_info` JSONB — for self-healing
- `position_x/y`, `width`, `height`, `attributes` JSONB
- `source` (manual/auto/healed), `last_verified_at`, `created_by`
- `UniqueConstraint("page_id", "element_id")` — enforces element uniqueness per page
- All JSON fields use JSONB (not generic JSON)

### FetchHistory (new)
- Tracks each fetch session with config, results, timing

### ChangeDetection (new)
- Tracks element changes over time with impact analysis

---

## Migration (backend/migrations/extend_element_tables.sql)

Fully rewritten to be **idempotent** and **data-safe**:

1. **page_repository**: Conditional rename `url_path` → `page_url`, then extend types
2. **element_repository** (in safe order):
   - 2a: Add new columns WITHOUT NOT NULL first
   - 2b: **Migrate data BEFORE dropping old columns**:
     - `alias` → `element_id` / `element_name`
     - `display_text` → `element_text`
     - `coord_x/y` → `position_x/y`
     - `locator_chain` → `locator_strategies` (wrapped intelligently based on shape)
   - 2c: **Backfill `project_id`** via page_repository join (sentinel UUID for orphans)
   - 2e: Enforce NOT NULL + defaults AFTER backfill
   - 2f: Add FK constraint idempotently
   - 2g: Drop old columns only after data migration
   - 2i: Add unique constraint idempotently
3. **fetch_history** + **change_detection** tables created with `IF NOT EXISTS`

All data-migration UPDATEs are guarded by `information_schema` existence checks,
so the migration can run on both fresh DBs and existing DBs with data.

---

## Cross-Cutting Fixes

- **hallucination_detector.py**: Updated `_element_exists` query to use new fields
  (`element_id`, `element_name`, `element_text`) with `or_()` instead of the removed
  `alias` / `display_text` columns. Restores AI case generation functionality.
- **element_service.py**: `create_page` / `get_page_by_url` updated to use `page_url`.
- **elements.py** (API): `batch_import_elements` endpoint updated to pass `page_url`.
- **element_service.batch_import_elements**: Marked with `TODO(Task 6)` docstring —
  this method still references removed fields (`alias`, `display_text`, `coord_x/y`,
  `locator_chain`) and will be fully rewritten in Task 6. Do NOT call it until then.

---

## Verification

```
✅ Syntax valid: app/models/element.py
✅ Syntax valid: app/services/element_service.py
✅ Syntax valid: app/services/hallucination_detector.py
✅ Syntax valid: app/api/v1/elements.py
✅ Syntax valid: app/models/__init__.py
✅ All 4 models load successfully
✅ All JSON fields use JSONB type
✅ UniqueConstraint(page_id, element_id) added
✅ Relationships use lazy=selectin (async-safe)
✅ hallucination_detector.py uses new field names
✅ batch_import_elements has TODO(Task 6) marker
```

---

## Remaining Concerns

1. **Migration NOT executed**: No database connection was available. The SQL script is
   ready and idempotent — run manually:
   `psql -U <user> -d <db> -f backend/migrations/extend_element_tables.sql`
2. **No git available**: Changes couldn't be committed. Manual commit required.
3. **batch_import_elements is broken** (acknowledged): Will be rewritten in Task 6.
4. **playwright_service data contract**: Will be aligned in Task 3 / Task 5.
