"""ExecutionDetail model tests."""
from app.models.execution import ExecutionDetail, ExecutionRecord


class TestExecutionDetailColumns:
    def test_required_columns(self):
        cols = {c.name for c in ExecutionDetail.__table__.c}
        for expected in ("id", "execution_record_id", "script_id", "case_id",
                         "step", "action", "status", "error_type", "error_msg",
                         "stack_trace", "screenshot_url", "dom_snapshot",
                         "heal_status", "heal_log", "duration_ms", "created_at"):
            assert expected in cols

    def test_has_index_on_execution_record_id(self):
        indexes = [i.name for i in ExecutionDetail.__table__.indexes]
        assert "idx_exec_detail_record" in indexes

    def test_fk_to_execution_record_cascade(self):
        fks = ExecutionDetail.__table__.foreign_keys
        assert any(
            "execution_record" in str(f.target_fullname) and f.ondelete == "CASCADE"
            for f in fks
        )
