# -*- coding: utf-8 -*-
"""受限表达式引擎（DFM 规则 v2）。

用法::

    from nxdrp.expr import SymbolContext, evaluate_rule, validate_expression

    verdicts = evaluate_rule(rule, SymbolContext(params=params, meas={"ratio": 4.5}))
    for v in verdicts:
        ...  # v.severity / v.measured / v.threshold / v.unit

设计约束：零第三方依赖、不做任何 Python 代码执行（不用 eval/exec），
缺数据抛 ``ExprMissingSymbol`` 由 checker 跳过，规则写错由 ``RuleBook.validate()``
加载时拦截。完整语法见 ``parser.py`` 顶部说明。
"""

from .cases import CaseVerdict, evaluate_rule, validate_expression
from .errors import (
    ExprError,
    ExprMissingSymbol,
    ExprParseError,
    ExprRuleError,
    ExprTypeError,
    ExprUnitError,
)
from .evaluator import SymbolContext, evaluate, evaluate_str
from .parser import FUNCTIONS, Node, parse
from .units import Value

__all__ = [
    "CaseVerdict",
    "ExprError",
    "ExprMissingSymbol",
    "ExprParseError",
    "ExprRuleError",
    "ExprTypeError",
    "ExprUnitError",
    "FUNCTIONS",
    "Node",
    "SymbolContext",
    "Value",
    "evaluate",
    "evaluate_rule",
    "evaluate_str",
    "parse",
    "validate_expression",
]
