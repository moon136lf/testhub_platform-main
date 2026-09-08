"""
智能导入服务：自由文本 Excel 解析 + 模板生成

两种格式自动识别：
- template：平台 9 列模板（用例名/优先级/类型/步骤/动作/目标/数据/预期(步)/预期结果）
- freetext：自由文本表（用例编号/模块/标题/操作步骤/预期结果/优先级/…，步骤一段文字）

执行类列（测试结果/用例截图/失败原因）自动忽略。
"""
import io
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TEMPLATE_HEADERS = ["用例名", "优先级", "类型", "步骤", "动作", "目标", "数据", "预期(步)", "预期结果"]

_FREETEXT_REQUIRED = ("标题", "操作步骤")

# 执行类列：只采集，不导入
_EXECUTION_ONLY_COLS = {"测试结果", "用例截图", "失败原因"}

_PRIORITY_ZH_MAP = {"高": "P1", "中": "P2", "低": "P3"}

_STEP_NO_RE = re.compile(r"^(\d+)[.、．]\s*")
_ASSERT_RE = re.compile(r"^断言[：:]?\s*")
# 在X中输入Y / 在X输入Y
_IN_TARGET_DATA_RE = re.compile(r"在(.+?)(?:输入框|输入|框中|中|里)输入(.+)")
_CLICK_RE = re.compile(r"点击(.{1,30}?)(?:$|，|,|；|;|。|\s)")


def detect_format(headers: List[Optional[str]]) -> Optional[str]:
    """按表头识别格式。template：9 列齐全；freetext：标题+操作步骤；否则 None。"""
    hs = [str(h or "").strip() for h in headers]
    if all(h in hs for h in TEMPLATE_HEADERS):
        return "template"
    if all(h in hs for h in _FREETEXT_REQUIRED):
        return "freetext"
    return None


def _extract_target_data(action: str) -> tuple:
    """从动作文本提取 (target, data)。提取不到返回 ("", "")。"""
    m = _IN_TARGET_DATA_RE.search(action)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _CLICK_RE.search(action)
    if m:
        return m.group(1).strip(), ""
    return "", ""


def split_steps(text: str) -> List[Dict]:
    """把操作步骤段落拆成结构化步骤列表。

    规则：
    - `^数字.` 开头行开启新步骤；无序号行并入上一步 action
    - `断言：xxx` 设为当前步骤 expected（剥前缀）
    - 无断言标记的行文本若以"预期"等提示性开头同理；否则 expected="待补"
    """
    steps: List[Dict] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _STEP_NO_RE.match(line)
        if m:
            content = line[m.end():].strip()
            # 序号后紧跟断言前缀（如 "7.断言：xxx"）→ 作为上一步/本步预期而非动作
            am = _ASSERT_RE.match(content)
            if am:
                assertion = _ASSERT_RE.sub("", content).strip() or "待补"
                if steps:
                    steps[-1]["expected"] = assertion
                else:
                    steps.append({"step": 1, "action": "断言", "target": "",
                                  "data": "", "expected": assertion})
                continue
            steps.append({"step": len(steps) + 1, "action": content,
                          "target": "", "data": "", "expected": "待补"})
        elif _ASSERT_RE.match(line):
            assertion = _ASSERT_RE.sub("", line).strip()
            if steps:
                steps[-1]["expected"] = assertion or "待补"
            else:
                steps.append({"step": 1, "action": line, "target": "",
                              "data": "", "expected": assertion or "待补"})
        else:
            if steps:
                steps[-1]["action"] += f" {line}"
            else:
                steps.append({"step": 1, "action": line, "target": "",
                              "data": "", "expected": "待补"})

    for s in steps:
        target, data = _extract_target_data(s["action"])
        if target:
            s["target"] = target
        if data:
            s["data"] = data
    return steps


def _normalize_priority(raw) -> str:
    p = str(raw or "").strip().upper()
    if p in ("P0", "P1", "P2", "P3"):
        return p
    zh = _PRIORITY_ZH_MAP.get(str(raw or "").strip())
    return zh or "P1"


def parse_free_text_row(row: Dict) -> Dict:
    """自由文本行 → 候选用例 dict。"""
    title = str(row.get("标题") or "").strip()
    module = str(row.get("模块") or "").strip()
    name = f"{module}-{title}" if module else title
    if not name:
        name = "未命名用例"

    steps = split_steps(str(row.get("操作步骤") or ""))
    if not steps:
        steps = [{"step": 1, "action": "待补", "target": "", "data": "", "expected": "待补"}]

    expected_result = str(row.get("预期结果") or "").strip()
    if not expected_result:
        first_non_pending = next(
            (s["expected"] for s in steps if s["expected"] != "待补"), "")
        expected_result = first_non_pending or "待补"
    # 预期结果上限 200（CaseCreateRequest 约束）
    expected_result = expected_result[:200]

    return {
        "name": name[:100],
        "priority": _normalize_priority(row.get("优先级")),
        "case_type": "functional",
        "precondition": str(row.get("前置条件") or "").strip() or None,
        "steps": steps,
        "expected_result": expected_result,
    }


class SmartImportService:
    """智能导入：格式识别 + 解析为候选用例（不写库）+ 模板生成。"""

    @staticmethod
    def generate_template() -> bytes:
        """生成 9 列导入模板 xlsx（表头 + 1 条示例行）。"""
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "测试用例"
        ws.append(TEMPLATE_HEADERS)
        ws.append(["登录-正确密码登录成功", "P1", "functional", 1,
                   "输入用户名", "用户名输入框", "testuser", "输入框显示 testuser",
                   "登录成功跳转首页"])
        ws.append(["", "", "", 2, "点击登录按钮", "登录按钮", "", "跳转到首页", ""])
        # 列宽
        widths = [28, 8, 14, 6, 24, 18, 16, 24, 24]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def parse_preview(file_bytes: bytes, fmt: str) -> Dict:
        """解析上传文件为候选用例列表（不写库）。

        Returns:
            {"format": "template"|"freetext", "cases": [candidate...], "warnings": [str]}
        """
        if fmt != "xlsx":
            # 非 xlsx 走原解析路径（csv/md 仅模板式）
            from app.services.import_export_service import ImportExportService
            rows = ImportExportService.__new__(ImportExportService)._parse(file_bytes, fmt) \
                if hasattr(ImportExportService, "_parse") else []
            return {"format": "template", "cases": rows, "warnings": []}

        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(file_bytes))
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            headers = [str(c).strip() if c is not None else "" for c in next(rows_iter)]
        except StopIteration:
            return {"format": "freetext", "cases": [], "warnings": ["空文件"]}

        fmt_detected = detect_format(headers)
        if fmt_detected is None:
            raise ValueError(
                f"无法识别的表头格式：{headers[:5]}…。请使用平台模板（下载模板获取）或自由文本格式（含'标题'和'操作步骤'列）")

        warnings: List[str] = []
        cases: List[Dict] = []

        if fmt_detected == "freetext":
            for r in rows_iter:
                if all(c is None or str(c).strip() == "" for c in r):
                    continue
                row = dict(zip(headers, r))
                # 执行类列忽略（不报 warning，属预期）
                for col in _EXECUTION_ONLY_COLS:
                    row.pop(col, None)
                cases.append(parse_free_text_row(row))
        else:
            from app.services.import_export_service import ImportExportService
            svc = ImportExportService.__new__(ImportExportService)  # 不需要 db
            rows = svc._parse_xlsx(file_bytes)
            for row in rows:
                cases.append({
                    "name": str(row.get("name") or "未命名用例")[:100],
                    "priority": _normalize_priority(row.get("priority")),
                    "case_type": row.get("case_type") or "functional",
                    "precondition": row.get("precondition") or None,
                    "steps": row.get("steps") or [{"step": 1, "action": "待补",
                                                   "target": "", "data": "", "expected": "待补"}],
                    "expected_result": (row.get("expected_result") or "待补")[:200],
                })

        if not cases:
            warnings.append("未解析到任何用例数据")
        return {"format": fmt_detected, "cases": cases, "warnings": warnings}
