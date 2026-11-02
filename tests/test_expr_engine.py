# -*- coding: utf-8 -*-
"""表达式引擎（nxdrp/expr）单测：语法、单位、函数、失败语义与规则求值。"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from nxdrp.expr import (
    ExprMissingSymbol,
    ExprParseError,
    ExprRuleError,
    ExprTypeError,
    ExprUnitError,
    SymbolContext,
    Value,
    evaluate_rule,
    evaluate_str,
    parse,
    validate_expression,
)


def num(result: Value | bool | str) -> float:
    assert isinstance(result, Value), f"期望 Value，实际 {type(result).__name__}"
    return result.number


def ctx(**kwargs) -> SymbolContext:
    return SymbolContext(**kwargs)


@dataclass
class StubRule:
    """模拟 contracts.Rule 的表达式相关字段（引擎按 duck typing 读取）。"""

    expression: dict = field(default_factory=dict)
    severity: str = "P2"
    unit: str = ""
    rounding: int | None = None
    exceptions: list = field(default_factory=list)


class PrecedenceTests(unittest.TestCase):
    def test_mul_before_add(self):
        self.assertEqual(evaluate_str("2 + 3 * 4", ctx()).number, 14)

    def test_parens(self):
        self.assertEqual(evaluate_str("(2 + 3) * 4", ctx()).number, 20)

    def test_power_right_assoc(self):
        self.assertEqual(evaluate_str("2 ^ 3 ^ 2", ctx()).number, 512)

    def test_unary_minus_and_tolerance(self):
        self.assertAlmostEqual(evaluate_str("0.5 - 1e-9", ctx()).number, 0.5 - 1e-9)

    def test_logical_precedence(self):
        self.assertIs(evaluate_str("not 1 > 0", ctx()), False)
        self.assertIs(evaluate_str("1 > 0 and 2 > 1", ctx()), True)
        self.assertIs(evaluate_str("1 > 2 or 2 > 1", ctx()), True)

    def test_chained_comparison_rejected(self):
        with self.assertRaises(ExprParseError):
            parse("1 < 2 < 3")

    def test_unknown_identifier_rejected(self):
        with self.assertRaises(ExprParseError):
            parse("foo > 1")
        with self.assertRaises(ExprParseError):
            parse("other.x > 1")


class UnitTests(unittest.TestCase):
    def test_length_addition_converts(self):
        self.assertAlmostEqual(num(evaluate_str("1m + 1mm", ctx())), 1001.0)

    def test_inch_conversion(self):
        self.assertAlmostEqual(num(evaluate_str("1inch + 0mm", ctx())), 25.4)

    def test_division_yields_ratio(self):
        self.assertEqual(num(evaluate_str("2mm / 1mm", ctx())), 2.0)

    def test_multiplication_yields_area(self):
        result = evaluate_str("2mm * 3mm", ctx())
        self.assertEqual(result.unit, "mm2")
        self.assertEqual(result.number, 6.0)

    def test_mm_squared_suffix_normalized(self):
        result = evaluate_str("6mm² / 2mm", ctx())
        self.assertEqual(result.unit, "mm")
        self.assertEqual(result.number, 3.0)

    def test_ratio_times_length_keeps_length(self):
        c = ctx(params={"k": 0.5}, meas={"t": 2.0}, units={"meas.t": "mm"})
        result = evaluate_str("params.k * meas.t", c)
        self.assertEqual(result.unit, "mm")
        self.assertEqual(result.number, 1.0)

    def test_dimension_conflict_rejected(self):
        with self.assertRaises(ExprUnitError):
            evaluate_str("1mm + 1deg", ctx())

    def test_compare_dimension_conflict_rejected(self):
        with self.assertRaises(ExprUnitError):
            evaluate_str("1mm > 1deg", ctx())

    def test_unknown_unit_suffix_rejected(self):
        # 白名单外的后缀不被当作单位，解析时报"未知标识符"
        with self.assertRaises(ExprParseError):
            parse("1kg + 1mm")


class FunctionTests(unittest.TestCase):
    def test_min_max(self):
        self.assertEqual(num(evaluate_str("min(3, 1, 2)", ctx())), 1)
        self.assertEqual(num(evaluate_str("max(3, 1, 2)", ctx())), 3)
        self.assertAlmostEqual(num(evaluate_str("max(1mm, 0.5m)", ctx())), 500.0)

    def test_abs_round(self):
        self.assertEqual(num(evaluate_str("abs(-2.5)", ctx())), 2.5)
        self.assertEqual(num(evaluate_str("round(2.5)", ctx())), 3.0)      # 四舍五入
        self.assertEqual(num(evaluate_str("round(-2.5)", ctx())), -3.0)
        self.assertAlmostEqual(num(evaluate_str("round(2.345, 2)", ctx())), 2.35)

    def test_if_selects_branch(self):
        c = ctx(meas={"a": 1.0})
        self.assertEqual(num(evaluate_str("if(meas.a > 0, 10, 20)", c)), 10.0)
        self.assertEqual(num(evaluate_str("if(meas.a < 0, 10, 20)", c)), 20.0)

    def test_if_is_lazy(self):
        # 未走的分支里引用缺数据不应报错
        c = ctx(meas={"a": 1.0})
        self.assertEqual(num(evaluate_str("if(meas.a > 0, 1, meas.missing)", c)), 1.0)

    def test_nearest(self):
        c = ctx(meas={"d": 2.8, "series": [1.0, 2.0, 2.5, 3.0]})
        self.assertEqual(num(evaluate_str("nearest(meas.series, meas.d)", c)), 3.0)
        self.assertTrue(evaluate_str("abs(meas.d - nearest(meas.series, meas.d)) > 0.05", c))

    def test_nearest_empty_list_is_missing_data(self):
        c = ctx(meas={"d": 2.8, "series": []})
        with self.assertRaises(ExprMissingSymbol):
            evaluate_str("nearest(meas.series, meas.d)", c)

    def test_nearest_requires_numeric_list(self):
        c = ctx(meas={"d": 2.8, "series": "abc"})
        with self.assertRaises(ExprTypeError):
            evaluate_str("nearest(meas.series, meas.d)", c)

    def test_table_lookup(self):
        c = ctx(params={"table": {"PC": 1.5, "PBT": 0.8}}, meas={"material": "PC"})
        self.assertEqual(num(evaluate_str("table(params.table, meas.material)", c)), 1.5)

    def test_table_missing_key_is_missing_data(self):
        c = ctx(params={"table": {"PC": 1.5}}, meas={"material": "XYZ"})
        with self.assertRaises(ExprMissingSymbol):
            evaluate_str("table(params.table, meas.material)", c)

    def test_unknown_function(self):
        with self.assertRaises(ExprParseError):
            parse("sqrt(2)")

    def test_wrong_arity(self):
        with self.assertRaises(ExprParseError):
            parse("abs(1, 2)")


class FailureSemanticsTests(unittest.TestCase):
    def test_missing_meas(self):
        with self.assertRaises(ExprMissingSymbol):
            evaluate_str("meas.ratio > 4", ctx(params={"r": 4.0}))

    def test_missing_param(self):
        with self.assertRaises(ExprMissingSymbol):
            evaluate_str("meas.ratio > params.deep", ctx(meas={"ratio": 5.0}))

    def test_none_value_is_missing(self):
        with self.assertRaises(ExprMissingSymbol):
            evaluate_str("meas.ratio > 4", ctx(meas={"ratio": None}))

    def test_bool_in_arithmetic(self):
        with self.assertRaises(ExprTypeError):
            evaluate_str("meas.flag + 1", ctx(meas={"flag": True}))

    def test_number_as_when_rejected_by_rule(self):
        rule = StubRule(expression={"cases": [{"when": "1", "measured": "1"}]})
        with self.assertRaises(ExprTypeError):
            evaluate_rule(rule, ctx())

    def test_division_by_zero(self):
        with self.assertRaises(ExprTypeError):
            evaluate_str("1 / 0", ctx())


class RuleEvaluationTests(unittest.TestCase):
    def test_first_match_wins_with_severity_upgrade(self):
        rule = StubRule(
            expression={
                "cases": [
                    {"when": "meas.ratio > params.very", "severity": "P1",
                     "measured": "meas.ratio", "threshold": "params.very"},
                    {"when": "meas.ratio > params.base", "severity": "P2",
                     "measured": "meas.ratio", "threshold": "params.base"},
                ]
            }
        )
        params = {"very": 10.0, "base": 4.0}
        verdicts = evaluate_rule(rule, ctx(params=params, meas={"ratio": 12.0}))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].severity, "P1")
        self.assertEqual(verdicts[0].threshold, 10.0)

        verdicts = evaluate_rule(rule, ctx(params=params, meas={"ratio": 5.0}))
        self.assertEqual(verdicts[0].severity, "P2")

    def test_at_threshold_is_silent(self):
        rule = StubRule(expression={"cases": [
            {"when": "meas.ratio > params.base", "measured": "meas.ratio",
             "threshold": "params.base"}]})
        verdicts = evaluate_rule(rule, ctx(params={"base": 4.0}, meas={"ratio": 4.0}))
        self.assertEqual(verdicts, [])

    def test_threshold_can_be_formula(self):
        rule = StubRule(
            unit="mm",
            expression={"cases": [{
                "when": "meas.radius < params.ratio * meas.thickness - 1e-9",
                "measured": "meas.radius",
                "threshold": "params.ratio * meas.thickness",
            }]},
        )
        c = ctx(params={"ratio": 0.5}, meas={"radius": 0.2, "thickness": 1.0})
        verdicts = evaluate_rule(rule, c)
        self.assertEqual(len(verdicts), 1)
        self.assertAlmostEqual(verdicts[0].threshold, 0.5)
        self.assertEqual(verdicts[0].unit, "mm")

    def test_rounding_only_affects_output(self):
        rule = StubRule(
            rounding=1,
            expression={"cases": [{
                "when": "meas.ratio > 4.0", "measured": "meas.ratio",
                "threshold": "4.0"}]},
        )
        # 4.04 大于 4.0 应命中；舍入后展示为 4.0，但判定不因舍入而改变
        verdicts = evaluate_rule(rule, ctx(meas={"ratio": 4.04}))
        self.assertEqual(len(verdicts), 1)
        self.assertAlmostEqual(verdicts[0].measured, 4.0)

    def test_exception_skip(self):
        rule = StubRule(
            expression={"cases": [{"when": "meas.ratio > 4", "measured": "meas.ratio"}]},
            exceptions=[{"when": "meas.exempt == 1", "skip": True}],
        )
        self.assertEqual(evaluate_rule(rule, ctx(meas={"ratio": 5, "exempt": 1})), [])
        self.assertEqual(len(evaluate_rule(rule, ctx(meas={"ratio": 5, "exempt": 0}))), 1)

    def test_exception_missing_data_does_not_exempt(self):
        rule = StubRule(
            expression={"cases": [{"when": "meas.ratio > 4", "measured": "meas.ratio"}]},
            exceptions=[{"when": "meas.missing == 1", "skip": True}],
        )
        self.assertEqual(len(evaluate_rule(rule, ctx(meas={"ratio": 5}))), 1)

    def test_exception_severity_override(self):
        rule = StubRule(
            expression={"cases": [{"when": "meas.ratio > 4", "severity": "P1",
                                   "measured": "meas.ratio"}]},
            exceptions=[{"when": "meas.ratio < 5", "severity_override": "P3"}],
        )
        verdicts = evaluate_rule(rule, ctx(meas={"ratio": 4.5}))
        self.assertEqual(verdicts[0].severity, "P3")

    def test_case_with_missing_measurement_is_skipped(self):
        # DFM-33 形态：锐边 case 与圆角 case 并排，各取各的测量量
        rule = StubRule(expression={"cases": [
            {"when": "meas.sharp_edge_count > 0", "measured": "0",
             "threshold": "1", "unit": "mm"},
            {"when": "meas.radius < 0.5", "measured": "meas.radius",
             "threshold": "0.5", "unit": "mm"},
        ]})
        verdicts = evaluate_rule(rule, ctx(meas={"radius": 0.3}))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].measured, 0.3)
        # 只给锐边测量量时命中第一条
        verdicts = evaluate_rule(rule, ctx(meas={"sharp_edge_count": 2}))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].measured, 0.0)

    def test_case_may_omit_measured(self):
        # 布尔型判定（如"存在倒扣即报"）：measured 留空
        rule = StubRule(expression={"cases": [
            {"when": "meas.has_depth == 0", "threshold": "params.min_depth"}]})
        verdicts = evaluate_rule(rule, ctx(params={"min_depth": 0.5}, meas={"has_depth": 0}))
        self.assertEqual(len(verdicts), 1)
        self.assertIsNone(verdicts[0].measured)
        self.assertEqual(verdicts[0].threshold, 0.5)

    def test_matched_case_with_missing_measured_raises(self):
        rule = StubRule(expression={"cases": [
            {"when": "meas.flag == 1", "measured": "meas.width"}]})
        with self.assertRaises(ExprMissingSymbol):
            evaluate_rule(rule, ctx(meas={"flag": 1}))

    def test_no_cases_rejected(self):
        with self.assertRaises(ExprRuleError):
            evaluate_rule(StubRule(expression={}), ctx())

    def test_units_declaration_in_expression(self):
        rule = StubRule(expression={
            "units": {"meas.r": "mm"},
            "cases": [{"when": "meas.r < 1mm", "measured": "meas.r"}],
        })
        self.assertEqual(len(evaluate_rule(rule, ctx(meas={"r": 0.5}))), 1)


class ValidateExpressionTests(unittest.TestCase):
    def test_valid(self):
        rule = StubRule(expression={"cases": [
            {"when": "meas.ratio > params.base", "severity": "P2",
             "measured": "meas.ratio", "threshold": "params.base"}]})
        self.assertEqual(validate_expression(rule), [])

    def test_bad_syntax(self):
        rule = StubRule(expression={"cases": [{"when": "meas.ratio >", "measured": "1"}]})
        problems = validate_expression(rule)
        self.assertTrue(any("语法错误" in p for p in problems))

    def test_empty_cases(self):
        self.assertTrue(validate_expression(StubRule(expression={"cases": []})))

    def test_bad_severity_and_rounding(self):
        rule = StubRule(
            expression={"cases": [{"when": "1 > 0", "severity": "P9", "rounding": 12}]}
        )
        problems = validate_expression(rule)
        self.assertTrue(any("severity" in p for p in problems))
        self.assertTrue(any("rounding" in p for p in problems))

    def test_bad_exception(self):
        rule = StubRule(
            expression={"cases": [{"when": "1 > 0"}]},
            exceptions=[{"when": "meas.x >"}],
        )
        self.assertTrue(validate_expression(rule))

    def test_unknown_unit_in_declaration(self):
        rule = StubRule(expression={"units": {"meas.r": "kg"}, "cases": [{"when": "1 > 0"}]})
        self.assertTrue(any("units" in p for p in validate_expression(rule)))


if __name__ == "__main__":
    unittest.main()
