"""#8 AI 识别规则引擎 (§3.6.6 六规则, spec §3.1 口径).

纯函数: 输入脚本数据 dict, 输出 (score: int, reason: str).
零 DB/零 LLM — 数据组装由调用方 (RegressionService) 完成;
included = score >= INCLUDED_THRESHOLD 由调用方判定.
"""
INCLUDED_THRESHOLD = 3
MAX_REASON_LEN = 200
CORE_CATEGORIES = ("core_flow", "ui_smoke")
PASS_RATE_THRESHOLD = 0.8
PASS_RATE_MIN_RUNS = 3
PASS_RATE_WINDOW = 10
FLAKY_WINDOW = 5
FLAKY_MIN_RUNS = 2
FLIP_THRESHOLD = 2
MAX_STEPS = 10
MAX_ELEMENTS = 8


def _flip_count(runs):
    """pass↔fail 翻转次数."""
    return sum(1 for a, b in zip(runs, runs[1:]) if a != b)


def score_script(data: dict):
    """六规则打分. 返回 (score, reason).

    规则口径 (spec §3.1):
    R1 优先级(高): P0=2/P1=1/其他=0
    R2 通过率(高): 近10次 pass率>=80% -> 2; 运行<3次 -> 0 不罚
    R3 核心覆盖(中): category in {core_flow,ui_smoke} -> 1; type_label 含"正常" 再+1
    R4 模块代表(中): module 非空且该 module 无 included -> 1; module 空 -> 跳过
    R5 稳定性(中): 近5次翻转>=2 -> flaky 0; 否则 1; 运行<2次不判(0)
    R6 依赖(低): 步骤<=10 且去重元素<=8 -> 1

    recent_runs 按旧→新排列; "近N次"取序列尾部 N 个.
    """
    score = 0
    hits = []

    # R1
    priority = (data.get("priority") or "P1").upper()
    if priority == "P0":
        score += 2
        hits.append("P0核心用例")
    elif priority == "P1":
        score += 1
        hits.append("P1用例")

    # R2
    runs = list(data.get("recent_runs") or [])
    if len(runs) >= PASS_RATE_MIN_RUNS:
        window = runs[-PASS_RATE_WINDOW:]
        rate = sum(1 for r in window if r) / len(window)
        if rate >= PASS_RATE_THRESHOLD:
            score += 2
            hits.append(f"历史通过率{rate:.0%}")

    # R3
    if (data.get("category") or "") in CORE_CATEGORIES:
        score += 1
        hits.append("核心流程覆盖")
        tl = data.get("type_label") or ""
        if "正常" in tl:
            score += 1

    # R4
    if data.get("module") and not data.get("module_has_included"):
        score += 1
        hits.append(f"模块[{data['module']}]代表")

    # R5
    if len(runs) >= FLAKY_MIN_RUNS:
        window = runs[-FLAKY_WINDOW:]
        if _flip_count(window) < FLIP_THRESHOLD:
            score += 1
            hits.append("运行稳定")

    # R6
    if (data.get("step_count") or 0) <= MAX_STEPS and (data.get("element_count") or 0) <= MAX_ELEMENTS:
        score += 1
        hits.append("依赖少")

    reason = "；".join(hits)[:MAX_REASON_LEN]
    return score, reason
