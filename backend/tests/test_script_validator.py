# backend/tests/test_script_validator.py
"""Script validator (skill 8-item self-check) tests."""
from app.services.script_validator import validate_script, ValidationReport


class TestValidateScript:
    def test_clean_script_passes(self):
        script = (
            'def test_login(page):\n'
            '    page.get_by_label("用户名").fill("admin")\n'
            '    page.get_by_role("button", name="登录").click()\n'
            '    assert "首页" in page.title()\n'
        )
        report = validate_script(script, step_mapping=[
            {"step": 1, "status": "ok"}, {"step": 2, "status": "ok"}])
        assert report.all_pass() is True

    def test_index_locator_fails(self):
        script = 'def t(page):\n    page.locator(".btn").first.click()\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        check = [c for c in report.checks if c.name == "no_index_locator_on_click"][0]
        assert check.passed is False
        assert report.all_pass() is False

    def test_index_locator_select_option_fails(self):
        script = 'def t(page):\n    page.locator(".sel").first.select_option("x")\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        idx = [c for c in report.checks if c.name == "no_index_locator_on_click"][0]
        assert idx.passed is False

    def test_tautological_assertion_fails(self):
        script = 'def t(page):\n    assert page.get_by_role("button").is_visible()\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        check = [c for c in report.checks if c.name == "no_tautological_assertion"][0]
        assert check.passed is False
        assert report.all_pass() is False

    def test_hardcoded_wait_fails(self):
        script = 'def t(page):\n    page.wait_for_timeout(3000)\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        check = [c for c in report.checks if c.name == "no_hardcoded_long_wait"][0]
        assert check.passed is False
        assert report.all_pass() is False

    def test_fabricated_css_fails(self):
        # 无定位器来源却出现具体 css selector = 编造
        script = 'def t(page):\n    page.locator("#login-btn-xyz").click()\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "blocked"}])
        check = [c for c in report.checks if c.name == "no_fabricated_dom"][0]
        assert check.passed is False
        assert report.all_pass() is False

    def test_blocked_step_fails(self):
        script = 'def t(page):\n    pass\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "blocked"}])
        check = [c for c in report.checks if c.name == "all_steps_implemented"][0]
        assert check.passed is False
        assert report.all_pass() is False
