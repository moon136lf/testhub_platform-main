# backend/app/services/batch_naming.py
"""用例批次相关的纯命名函数 (#case-batch T4)。"""
from datetime import datetime


def build_script_name(batch_name: str | None, fallback_title: str,
                      ts: datetime, taken: set[str] | None = None) -> str:
    """脚本名: 批次名-自动化脚本HHmmss; 无批次回退用例标题.
    taken 为已占用名集合, 撞名追加 -2/-3... 直至可用 (上限 10 次)。"""
    taken = taken or set()
    base = (f"{batch_name}-自动化脚本{ts.strftime('%H%M%S')}"
            if batch_name else fallback_title)
    candidate = base
    for n in range(2, 12):
        if candidate not in taken:
            return candidate
        candidate = f"{base}-{n}"
    return candidate
