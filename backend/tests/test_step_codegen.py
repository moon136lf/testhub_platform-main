"""步骤化编辑器 → Playwright 代码生成。
操作类型词表 = 转脚本 ActionIntent 词表 + assert_db 数据库断言。"""
import pytest
from app.services.step_codegen import generate_script, SUPPORTED_ACTIONS


class TestCodegen:
    def test_generate_navigate_and_click(self):
        steps = [
            {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com/login",
             "element_name": ""},
            {"seq": 2, "action": "click", "target": "#login-btn", "value": "", "element_name": "登录按钮"},
        ]
        code = generate_script("登录用例", steps)
        assert 'page.goto("https://x.com/login")' in code
        assert 'page.locator("#login-btn").click()' in code

    def test_input_with_value(self):
        steps = [{"seq": 1, "action": "input", "target": "#user", "value": "admin", "element_name": "用户名"}]
        code = generate_script("t", steps)
        assert 'page.locator("#user").fill("admin")' in code

    def test_wait_seconds(self):
        steps = [{"seq": 1, "action": "wait", "target": "", "value": "2", "element_name": ""}]
        code = generate_script("t", steps)
        assert "page.wait_for_timeout(2000)" in code

    def test_wait_default_1s(self):
        steps = [{"seq": 1, "action": "wait", "target": "", "value": "", "element_name": ""}]
        code = generate_script("t", steps)
        assert "page.wait_for_timeout(1000)" in code

    def test_assert_text(self):
        steps = [{"seq": 1, "action": "assert_text", "target": ".title", "value": "仪表盘", "element_name": "标题"}]
        code = generate_script("t", steps)
        assert 'expect(page.locator(".title")).to_have_text("仪表盘")' in code

    def test_assert_visible(self):
        steps = [{"seq": 1, "action": "assert_visible", "target": ".card", "value": "", "element_name": "卡片"}]
        code = generate_script("t", steps)
        assert "expect(page.locator(\".card\")).to_be_visible()" in code

    def test_assert_db_generates_query_block(self):
        steps = [{"seq": 1, "action": "assert_db", "target": "",
                  "value": "SELECT count(*) FROM test_case", "element_name": "用例数",
                  "expected": "5"}]
        code = generate_script("t", steps)
        assert "assert_db" in code
        assert "SELECT count(*) FROM test_case" in code
        assert '"5"' in code

    def test_select_action(self):
        steps = [{"seq": 1, "action": "select", "target": "#env", "value": "dev", "element_name": "环境"}]
        code = generate_script("t", steps)
        assert 'select_option("dev")' in code

    def test_empty_steps_raises(self):
        with pytest.raises(ValueError):
            generate_script("t", [])

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="不支持"):
            generate_script("t", [{"seq": 1, "action": "hack", "target": "", "value": ""}])

    def test_click_requires_target(self):
        with pytest.raises(ValueError, match="target"):
            generate_script("t", [{"seq": 1, "action": "click", "target": "", "value": ""}])

    def test_header_has_imports(self):
        code = generate_script("t", [{"seq": 1, "action": "wait", "target": "", "value": "1"}])
        assert "from playwright.sync_api" in code and "expect" in code

    def test_steps_sorted_by_seq(self):
        steps = [
            {"seq": 2, "action": "click", "target": "#b", "value": "", "element_name": ""},
            {"seq": 1, "action": "click", "target": "#a", "value": "", "element_name": ""},
        ]
        code = generate_script("t", steps)
        assert code.index('#a') < code.index('#b')

    def test_quotes_escaped(self):
        steps = [{"seq": 1, "action": "input", "target": "#x", "value": '含"引号"文本', "element_name": ""}]
        code = generate_script("t", steps)
        assert '\\"' in code  # 内部引号被转义

    def test_supported_actions_exported(self):
        # 前端下拉数据源契约
        for a in ("navigate", "click", "input", "select", "wait", "assert_text", "assert_visible", "assert_db"):
            assert a in SUPPORTED_ACTIONS
