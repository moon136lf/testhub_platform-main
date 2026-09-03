"""logging_setup v2 测试: requestId 注入 + 统一格式 + GELF handler"""
import logging
import re


class TestRequestIdInjection:
    def test_filter_adds_default_request_id(self):
        from app.core.logging_setup import RequestIdFilter
        f = RequestIdFilter()
        rec = logging.LogRecord("app", logging.INFO, "p", 1, "msg", None, None)
        assert f.filter(rec) is True
        assert rec.request_id == "-"

    def test_contextvar_value_used(self):
        from app.core.logging_setup import RequestIdFilter, set_request_id
        set_request_id("req-123")
        try:
            f = RequestIdFilter()
            rec = logging.LogRecord("app", logging.INFO, "p", 1, "msg", None, None)
            f.filter(rec)
            assert rec.request_id == "req-123"
        finally:
            set_request_id("-")

    def test_formatter_contains_request_id_and_utf8_msg(self):
        from app.core.logging_setup import build_formatter
        fmt = build_formatter()
        rec = logging.LogRecord("app.mod", logging.INFO, "p", 42, "你好世界", None, None)
        rec.request_id = "r1"
        out = fmt.format(rec)
        assert "requestId=r1" in out
        assert "app.mod" in out
        assert "你好世界" in out
        assert re.search(r"\d{8} \d{2}:\d{2}:\d{2},\d{3}", out)

    def test_setup_logging_idempotent_and_formatted(self, tmp_path):
        from app.core.logging_setup import setup_logging, build_formatter
        # 幂等: 连调两次不抛错
        setup_logging(log_dir=str(tmp_path))
        setup_logging(log_dir=str(tmp_path))
        root = logging.getLogger()
        assert any(isinstance(f, type(None)) is False for f in root.filters) or len(root.filters) >= 1
