"""步骤化编辑器 → Playwright 代码生成（阶段2 核心件）。

行式步骤存储（每行 = seq/action/target/value/element_name/expected），
codegen 把它转成可执行的 Playwright 同步脚本。操作词表与转脚本链路
ActionIntent 对齐，扩展 assert_db 数据库断言（SQL+期望值）。

assert_db 执行语义：生成的脚本里调用 assert_db(page, sql=..., expected=...)，
该函数由脚本执行器（script_executor）在运行上下文注入——本模块只管生成。"""
from typing import Dict, List
import json

SUPPORTED_ACTIONS = [
    "navigate", "click", "input", "select", "wait",
    "assert_text", "assert_visible", "assert_db",
]

_HEADER = '''"""{title} — 由步骤化编辑器生成"""
from playwright.sync_api import sync_playwright, expect

def run(page):
'''


def _escape(v: str) -> str:
    """生成 Python 安全的双引号字符串字面量（json.dumps 兼容 Python 字符串转义）。
    输出含首尾双引号，调用处模板不需再包引号。"""
    return json.dumps(v or "", ensure_ascii=False)


def _loc(target: str) -> str:
    return f'page.locator({_escape(target)})'


def _gen_step(step: Dict) -> str:
    action = step.get("action", "")
    target = step.get("target", "")
    value = step.get("value", "")
    # 行内断言：非 assert_db 动作行带非空 expected → 动作完成后追加 to_have_text
    # （阶段3验收反馈：断言合并进行内，不再每步另起一行）
    inline_expected = step.get("expected", "") if action != "assert_db" else ""

    if action == "navigate":
        line = f'    page.goto({_escape(value)})'
        if inline_expected:
            line += f'\n    # 行内断言（navigate 无元素定位，仅记录期望）: {_escape(inline_expected)}'
        return line
    if action == "click":
        if not target:
            raise ValueError("click 需要 target（元素定位）")
        line = f"    {_loc(target)}.click()"
    elif action == "input":
        if not target:
            raise ValueError("input 需要 target（元素定位）")
        line = f'    {_loc(target)}.fill({_escape(value)})'
    elif action == "select":
        if not target:
            raise ValueError("select 需要 target（元素定位）")
        line = f'    {_loc(target)}.select_option({_escape(value)})'
    elif action == "wait":
        try:
            ms = int(float(value or 1) * 1000)
        except (ValueError, TypeError):
            ms = 1000
        line = f"    page.wait_for_timeout({ms})"
    elif action == "assert_text":
        if not target:
            raise ValueError("assert_text 需要 target（元素定位）")
        line = f'    expect({_loc(target)}).to_have_text({_escape(value)})'
    elif action == "assert_visible":
        if not target:
            raise ValueError("assert_visible 需要 target（元素定位）")
        line = f"    expect({_loc(target)}).to_be_visible()"
    elif action == "assert_db":
        sql = _escape(value)
        expected = _escape(step.get("expected", ""))
        return (f'    assert_db(page, sql={sql}, expected={expected}, '
                f'name={_escape(step.get("element_name", ""))})  # DB断言：expected 一律为字符串，比较语义由执行器决定')
    else:
        raise ValueError(f"不支持的操作类型: {action}")

    # 动作行的行内断言追加（expected 非空时）
    if inline_expected and target:
        line += f'\n    expect({_loc(target)}).to_have_text({_escape(inline_expected)})'
    elif inline_expected:
        line += f'\n    # 行内断言（无元素定位，仅记录期望）: {_escape(inline_expected)}'
    return line


def generate_script(title: str, steps: List[Dict]) -> str:
    """行式步骤 → Playwright 脚本文本。步骤空/操作未知/缺 target 抛 ValueError。"""
    if not steps:
        raise ValueError("至少需要一个步骤")
    body = [_gen_step(s) for s in sorted(steps, key=lambda x: x.get("seq", 0))]
    return _HEADER.format(title=_escape(title)) + "\n".join(body) + "\n"
