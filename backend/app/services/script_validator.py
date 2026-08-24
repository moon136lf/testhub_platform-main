# backend/app/services/script_validator.py
"""skill 8 项质量自检 -> validate_script."""
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    checks: List[Check] = field(default_factory=list)

    def all_pass(self) -> bool:
        return all(c.passed for c in self.checks)


# click/fill/select 前接 .first/.nth/.last (skill 3.2)
# 注意: .first/.nth/.last 出现在 .click/.fill/.select 之前, 如 .first.click()
_INDEX_LOCATOR_RE = re.compile(r'\.(first|nth\(\d+\)|last)\.(click|fill|select(?:_option)?)\(')
# 永真断言 (skill 3.3): 只验证 is_visible / to_be_visible 不验证业务结果
_VISIBLE_ASSERT_RE = re.compile(r'assert\s+.*\.is_visible\(\)|expect\(.*\)\.to_be_visible\(\)')
# 硬编码长等待 (skill 3.4): wait_for_timeout > 500ms
_LONG_WAIT_RE = re.compile(r'wait_for_timeout\((\d+)\)')
# 编造的 id/class css (skill 3.5): #xxx-yyy 或 .xxx-yyy
_FABRICATED_CSS_RE = re.compile(r'page\.locator\(["\']#[a-z0-9_-]+["\']\)|page\.locator\(["\']\.[a-z0-9_-]+["\']\)')


def _check_no_index_locator(script: str) -> Check:
    m = _INDEX_LOCATOR_RE.search(script)
    return Check("no_index_locator_on_click", m is None,
                 f"禁止索引定位: {m.group(0)}" if m else "")


def _check_no_tautological(script: str) -> Check:
    m = _VISIBLE_ASSERT_RE.search(script)
    # 仅 is_visible/to_be_visible 不一定永真, 但若脚本只有此断言无业务验证则无效
    return Check("no_tautological_assertion", m is None,
                 f"疑似永真断言: {m.group(0)}" if m else "")


def _check_no_hardcoded_wait(script: str) -> Check:
    for m in _LONG_WAIT_RE.finditer(script):
        if int(m.group(1)) > 500:
            return Check("no_hardcoded_long_wait", False, f"硬编码等待: {m.group(0)}")
    return Check("no_hardcoded_long_wait", True, "")


def _check_no_fabricated_dom(script: str, step_mapping: list) -> Check:
    # 当存在 blocked 步骤却出现具体 css selector = 编造
    blocked = any(s.get("status") == "blocked" for s in step_mapping)
    m = _FABRICATED_CSS_RE.search(script)
    bad = blocked and m is not None
    return Check("no_fabricated_dom", not bad,
                 f"无来源却编造 DOM: {m.group(0)}" if bad else "")


def _check_all_steps_implemented(step_mapping: list) -> Check:
    blocked = [s for s in step_mapping if s.get("status") == "blocked"]
    return Check("all_steps_implemented", len(blocked) == 0,
                 f"阻塞步骤: {blocked}" if blocked else "")


def validate_script(script: str, step_mapping: list) -> ValidationReport:
    """skill 8 项中的脚本层守门检查 (#1/#2/#4/#6/#8 脚本部分)."""
    report = ValidationReport()
    report.checks.append(_check_no_index_locator(script))
    report.checks.append(_check_no_tautological(script))
    report.checks.append(_check_no_hardcoded_wait(script))
    report.checks.append(_check_no_fabricated_dom(script, step_mapping))
    report.checks.append(_check_all_steps_implemented(step_mapping))
    return report
