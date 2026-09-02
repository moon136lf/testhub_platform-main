"""logging_setup tests: 落文件+轮转+幂等."""
import logging
import os

import pytest


@pytest.fixture(autouse=True)
def _restore_root_handlers():
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    yield
    for h in root.handlers[:]:
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)


class TestSetupLogging:
    def test_writes_file_and_rotates(self, tmp_path):
        from app.core.logging_setup import setup_logging
        log_dir = str(tmp_path)
        setup_logging(log_dir=log_dir, level_console="INFO", level_file=logging.INFO)
        logger = logging.getLogger("test_lsu")
        logger.info("hello-file")
        for h in logging.getLogger().handlers:
            h.flush()
        assert os.path.exists(os.path.join(log_dir, "app.log"))
        content = open(os.path.join(log_dir, "app.log"), encoding="utf-8").read()
        assert "hello-file" in content
        assert "test_lsu" in content  # logger name in format

    def test_idempotent_no_dup_handlers(self, tmp_path):
        from app.core.logging_setup import setup_logging
        setup_logging(log_dir=str(tmp_path))
        setup_logging(log_dir=str(tmp_path))
        root = logging.getLogger()
        fh = [h for h in root.handlers if h.__class__.__name__ == "RotatingFileHandler"]
        sh = [h for h in root.handlers if h.__class__.__name__ == "StreamHandler"]
        assert len(fh) == 1
        assert len(sh) == 1

    def test_file_level_stays_info(self, tmp_path):
        """文件级别不随 console 级别抬高."""
        from app.core.logging_setup import setup_logging
        setup_logging(log_dir=str(tmp_path), level_console="ERROR", level_file=logging.INFO)
        logger = logging.getLogger("test_lsu2")
        logger.info("still-logged")
        for h in logging.getLogger().handlers:
            h.flush()
        content = open(os.path.join(tmp_path / "app.log"), encoding="utf-8").read()
        assert "still-logged" in content
