"""生成批次命名纯函数（命名规范见 plan T1）。"""
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
