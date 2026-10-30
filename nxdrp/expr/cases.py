# -*- coding: utf-8 -*-
"""规则级求值：把 ``Rule.expression`` 的 cases / exceptions 落到 Findng 字段。

约定：

* ``cases`` 按顺序求值，**首个命中生效**（DFM-27 的 >10→P1 放第一、>4→P2 放第二）；
* 无一命中 → 返回空列表（对应旧判定"恰在阈值不报"）；
* case 命中后按序求值 ``exceptions``：``{"skip": true}`` 抑制该条，
  ``{"severity_override": "P3"}`` 降级；豁免求值缺数据时**不豁免**（宁可报）。
* ``rounding`` 只作用于回填 Finding 的 measured/threshold，不参与判定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import parser as ast
from .errors import (
    ExprMissingSymbol,
    ExprParseError,
    ExprRuleError,
    ExprTypeError,
    ExprUnitError,
)
from .evaluator import SymbolContext, evaluate
from .units import Value, normalize_unit


@dataclass(frozen=True)
class CaseVerdict:
    """一条命中的判定。checker 用它填 Finding 的 severity/measured/threshold/unit。"""

    severity: str
    measured: float
    threshold: float | None
    unit: str
    when: str
    note: str = ""
    case_index: int = 0
    rounding: int | None = None


def _round_half_away(number: float, digits: int) -> float:
    import math

    factor = 10.0 ** digits
    scaled = number * factor
    return (math.floor(abs(scaled) + 0.5) * (1.0 if scaled >= 0 else -1.0)) / factor


def _number(source: str, ctx: SymbolContext, what: str) -> float:
    result = evaluate(ast.parse(source), ctx)
    if not isinstance(result, Value):
        raise ExprTypeError(f"{what} 必须是数值表达式，实际得到 {type(result).__name__}")
    return result.number


def _apply_exceptions(
    exceptions: list[dict], ctx: SymbolContext
) -> tuple[bool, str | None, str]:
    """返回 (是否跳过, severity 覆盖值, 命中的豁免说明)。"""
    for item in exceptions:
        when = item.get("when")
        if not isinstance(when, str) or not when.strip():
            continue
        try:
            result = evaluate(ast.parse(when), ctx)
        except ExprMissingSymbol:
            continue  # 缺豁免依据的数据 → 不豁免
        if not isinstance(result, bool):
            raise ExprTypeError("exceptions 的 when 必须是布尔表达式")
        if not result:
            continue
        if item.get("skip"):
            return True, None, item.get("note") or when
        override = item.get("severity_override")
        return False, override, item.get("note") or when
    return False, None, ""


def evaluate_rule(rule: Any, ctx: SymbolContext) -> list[CaseVerdict]:
    """按 rule.expression 求值；返回 0 或 1 个判定。

    ``rule`` 只需有 ``expression / severity / unit / rounding / exceptions`` 属性
    （duck typing，避免契约层与引擎互相 import）。
    """
    config = getattr(rule, "expression", None) or {}
    cases = config.get("cases") or []
    if not isinstance(cases, list) or not cases:
        raise ExprRuleError("规则没有可用的 expression.cases")
    units = config.get("units") or {}
    merged_ctx = SymbolContext(params=ctx.params, meas=ctx.meas, units={**ctx.units, **units})
    exceptions = getattr(rule, "exceptions", None) or []

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ExprRuleError(f"expression.cases[{index}] 必须是对象")
        when = case.get("when")
        if not isinstance(when, str) or not when.strip():
            raise ExprRuleError(f"expression.cases[{index}] 缺少 when")
        try:
            result = evaluate(ast.parse(when), merged_ctx)
        except ExprMissingSymbol:
            # 该 case 依赖的测量量缺失 → 本 case 不适用，继续看下一条。
            # 规则里可以并排放"锐边"和"圆角"两类 case，各取各的测量量。
            continue
        if not isinstance(result, bool):
            raise ExprTypeError(f"cases[{index}].when 必须是布尔表达式")
        if not result:
            continue

        skip, override, exception_note = _apply_exceptions(exceptions, merged_ctx)
        if skip:
            return []

        measured_source = case.get("measured", "meas.primary")
        if not isinstance(measured_source, str) or not measured_source.strip():
            raise ExprRuleError(f"cases[{index}].measured 必须是非空字符串")
        measured = _number(measured_source, merged_ctx, "measured")
        threshold_source = case.get("threshold")
        threshold = (
            _number(threshold_source, merged_ctx, "threshold")
            if isinstance(threshold_source, str) and threshold_source.strip()
            else None
        )
        rounding = case.get("rounding", getattr(rule, "rounding", None))
        if rounding is not None:
            digits = int(rounding)
            measured = _round_half_away(measured, digits)
            if threshold is not None:
                threshold = _round_half_away(threshold, digits)
        severity = case.get("severity") or getattr(rule, "severity", "P2") or "P2"
        if override:
            severity = override
        unit = case.get("unit") or getattr(rule, "unit", "") or ""
        note = case.get("note") or exception_note
        return [
            CaseVerdict(
                severity=severity,
                measured=measured,
                threshold=threshold,
                unit=unit,
                when=when,
                note=note,
                case_index=index,
                rounding=rounding,
            )
        ]
    return []


def _parse_problem(source: Any, where: str) -> list[str]:
    if not isinstance(source, str) or not source.strip():
        return [f"{where} 必须是非空字符串"]
    try:
        ast.parse(source)
    except ExprParseError as exc:
        return [f"{where} 语法错误：{exc.message}（位置 {exc.position}）"]
    except ExprUnitError as exc:
        return [f"{where} 单位错误：{exc}"]
    return []


def validate_expression(rule: Any) -> list[str]:
    """静态校验 expression 配置；返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    config = getattr(rule, "expression", None)
    if config is None or config == {}:
        return problems
    if not isinstance(config, dict):
        return ["expression 必须是对象"]
    cases = config.get("cases")
    if not isinstance(cases, list) or not cases:
        problems.append("expression.cases 必须是非空数组")
        cases = []
    units = config.get("units") or {}
    if not isinstance(units, dict):
        problems.append("expression.units 必须是对象")
        units = {}
    for key, unit in units.items():
        try:
            normalize_unit(str(unit))
        except ExprUnitError as exc:
            problems.append(f"expression.units[{key!r}]：{exc}")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            problems.append(f"cases[{index}] 必须是对象")
            continue
        problems.extend(_parse_problem(case.get("when"), f"cases[{index}].when"))
        if "measured" in case:
            problems.extend(_parse_problem(case.get("measured"), f"cases[{index}].measured"))
        if "threshold" in case and case.get("threshold") is not None:
            problems.extend(_parse_problem(case.get("threshold"), f"cases[{index}].threshold"))
        severity = case.get("severity")
        if severity is not None and severity not in ("P0", "P1", "P2", "P3"):
            problems.append(f"cases[{index}].severity 非法：{severity!r}")
        rounding = case.get("rounding")
        if rounding is not None and (not isinstance(rounding, int) or rounding < 0 or rounding > 9):
            problems.append(f"cases[{index}].rounding 必须是 0~9 的整数")
    rounding = getattr(rule, "rounding", None)
    if rounding is not None and (not isinstance(rounding, int) or rounding < 0 or rounding > 9):
        problems.append("rule.rounding 必须是 0~9 的整数")
    exceptions = getattr(rule, "exceptions", None) or []
    if not isinstance(exceptions, list):
        problems.append("exceptions 必须是数组")
        exceptions = []
    for index, item in enumerate(exceptions):
        if not isinstance(item, dict):
            problems.append(f"exceptions[{index}] 必须是对象")
            continue
        problems.extend(_parse_problem(item.get("when"), f"exceptions[{index}].when"))
        override = item.get("severity_override")
        if override is not None and override not in ("P0", "P1", "P2", "P3"):
            problems.append(f"exceptions[{index}].severity_override 非法：{override!r}")
    return problems
