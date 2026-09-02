# backend/app/services/batch_naming.py
"""用例批次相关的纯命名函数 (命名规范见 plan T1 / #case-batch T4)。"""
from datetime import datetime

VALID_TYPES = {"whitescan_api", "whitescan_ui", "ai_generate", "manual"}
_TS_FMT = "%Y%m%d%H%M%S"
_REQ_MAX = 50

_TEMPLATES = {
    "whitescan_api": "白盒测试生成接口回归用例{ts}",
    "whitescan_ui": "白盒测试生成UI回归用例{ts}",
    "ai_generate": "{req}生成的用例{ts}",
    "manual": "手工创建用例{ts}",
}


def truncate_requirement(text):
    """需求名截断至 50 字符；空/None 用兜底名。"""
    if not text or not str(text).strip():
        return "未命名需求"
    return str(text).strip()[:_REQ_MAX]


def build_batch_name(batch_type: str, ts: datetime, requirement=None) -> str:
    if batch_type not in VALID_TYPES:
        raise ValueError(f"invalid batch_type: {batch_type}")
    template = _TEMPLATES[batch_type]
    return template.format(ts=ts.strftime(_TS_FMT), req=truncate_requirement(requirement))


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
