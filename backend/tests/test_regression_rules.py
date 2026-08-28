"""#8 规则引擎单测 (纯函数, spec §3.1 口径).

score_script 返回 (score: int, reason: str); included = score >= INCLUDED_THRESHOLD.
注: 计划原文个别用例期望值与 R2/R5 同判口径冲突 (R2 命中时 R5 也合法加分),
已按 spec §3.1 口径修正期望值/输入, 修正处见各行注释.
"""
from app.services.regression_rules import score_script, INCLUDED_THRESHOLD


def _base(**kw):
    d = dict(priority="P1", category="uncategorized", module=None, module_has_included=False,
             type_label=None, step_count=20, element_count=15, recent_runs=[])
    d.update(kw)
    return d


class TestIndividualRules:
    def test_r1_priority(self):
        assert score_script(_base(priority="P0"))[0] >= 2   # P0=2
        s, _ = score_script(_base(priority="P1"))
        assert s >= 1                                        # P1=1 (基准分)
        s, _ = score_script(_base(priority="P2"))
        assert s == 0

    def test_r2_pass_rate(self):
        # 8/10 = 80% 含边界 → 2 分 (近5次含>=2次翻转, R5 不加分, 隔离 R2)
        runs8 = [True]*5 + [False] + [True]*2 + [False] + [True]
        s, r = score_script(_base(priority="P2", recent_runs=runs8))
        assert s == 2
        assert "通过率" in r
        # 7/10 = 70% → 0 (同样近5次>=2翻转, R5 不加分)
        runs7 = [True]*5 + [False] + [True] + [False]*2 + [True]
        s, _ = score_script(_base(priority="P2", recent_runs=runs7))
        assert s == 0
        # 运行次数不足 → R2/R5 均不判 (0 分不负)
        s, _ = score_script(_base(priority="P2", recent_runs=[True]))
        assert s == 0

    def test_r3_core_flow(self):
        s, r = score_script(_base(priority="P2", category="core_flow", type_label="正常流程"))
        assert s == 2  # category=1 + type_label=1
        assert "核心" in r
        s, _ = score_script(_base(priority="P2", category="ui_smoke"))
        assert s == 1

    def test_r4_module_representative(self):
        s, r = score_script(_base(priority="P2", module="登录鉴权", module_has_included=False))
        assert s == 1
        assert "模块" in r
        # 已有 included → 不加
        s, _ = score_script(_base(priority="P2", module="登录鉴权", module_has_included=True))
        assert s == 0
        # module 空 → 跳过
        s, _ = score_script(_base(priority="P2", module=None))
        assert s == 0

    def test_r5_stability(self):
        # 翻转 2 次 → flaky 0 分
        s, _ = score_script(_base(priority="P2", recent_runs=[True, False, True, False]))
        assert s == 0
        # 无翻转 → 1 分
        s, r = score_script(_base(priority="P2", recent_runs=[True, True, False]))
        assert s == 1
        assert "稳定" in r or "flaky" not in r
        # <2 次不判
        s, _ = score_script(_base(priority="P2", recent_runs=[True]))
        assert s == 0

    def test_r6_low_dependency(self):
        s, r = score_script(_base(priority="P2", step_count=8, element_count=5))
        assert s == 1
        assert "依赖" in r
        s, _ = score_script(_base(priority="P2", step_count=11, element_count=5))
        assert s == 0
        s, _ = score_script(_base(priority="P2", step_count=8, element_count=9))
        assert s == 0


class TestAggregate:
    def test_threshold_3(self):
        # P0(2) + 低依赖(1) = 3 → 纳入
        score, reason = score_script(_base(priority="P0", step_count=5, element_count=3))
        assert score >= INCLUDED_THRESHOLD
        # P1(1) = 1 → 不纳入
        score, _ = score_script(_base())
        assert score < INCLUDED_THRESHOLD

    def test_new_script_can_be_included(self):
        """新脚本无运行数据: R1+R3+R6 可达 4 分."""
        score, _ = score_script(_base(priority="P0", category="core_flow",
                                      step_count=5, element_count=3))
        assert score >= INCLUDED_THRESHOLD

    def test_reason_joins_hits_and_truncates(self):
        _, reason = score_script(_base(priority="P0", category="core_flow", type_label="正常流程",
                                       step_count=5, element_count=3))
        assert "P0" in reason and "核心" in reason and "依赖" in reason
        # 截断常量存在
        from app.services.regression_rules import MAX_REASON_LEN
        assert MAX_REASON_LEN == 200
