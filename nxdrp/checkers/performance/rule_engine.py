# -*- coding: utf-8 -*-
"""PERF 规则公式 DSL。

NX Check-Mate 的条件表达式支持比较、逻辑运算和相等容差。这里实现同一组
安全语义，但不使用 Python ``eval``，也不允许属性访问、下标或任意函数调用。

公式库把输入、单位、变量公式、求解未知量、比较判定和出处都放在 JSON 中。
代码只负责解析、数值求解和把结果装进 Finding。
"""

from __future__ import annotations

import ast
import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Mapping


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_FORMULA_LIBRARY = os.path.join(PROJECT_ROOT, "rules", "perf_formula_v2.json")


class FormulaError(ValueError):
    """公式不可计算或规则配置有误。"""


class FormulaSyntaxError(FormulaError):
    """表达式包含 DSL 不允许的语法。"""


class FormulaDataError(FormulaError):
    """输入缺项、范围无效或求解区间不收敛。"""


_FUNCTIONS = {
    "abs": abs,
    "acos": math.acos,
    "asin": math.asin,
    "atan": math.atan,
    "cos": math.cos,
    "degrees": math.degrees,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "max": max,
    "min": min,
    "radians": math.radians,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tan": math.tan,
}
_CONSTANTS = {"e": math.e, "pi": math.pi}
_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_OP_TEXT = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_number(value: Any, expression: str) -> float:
    if not _is_number(value):
        raise FormulaSyntaxError(f"表达式 {expression!r} 的结果不是数值：{type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise FormulaDataError(f"表达式 {expression!r} 的结果不是有限数：{number!r}")
    return number


class _Evaluator:
    def __init__(self, context: Mapping[str, Any], equality_tolerance: float = 0.0):
        self.context = context
        self.equality_tolerance = max(0.0, float(equality_tolerance))

    def evaluate(self, expression: str) -> Any:
        try:
            tree = ast.parse(str(expression), mode="eval")
        except SyntaxError as exc:
            raise FormulaSyntaxError(f"表达式语法错误：{expression!r}") from exc
        value = self._node(tree.body)
        if isinstance(value, (str, bytes, dict, list, tuple, set)):
            raise FormulaSyntaxError(f"表达式 {expression!r} 只能返回数值或布尔值")
        return value

    def _node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (bool, int, float)):
                return node.value
            raise FormulaSyntaxError(f"不允许的常量：{node.value!r}")

        if isinstance(node, ast.Name):
            if node.id in self.context:
                return self.context[node.id]
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            raise FormulaDataError(f"缺少公式变量：{node.id}")

        if isinstance(node, ast.BinOp):
            left = self._node(node.left)
            right = self._node(node.right)
            try:
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    if float(right) == 0.0:
                        raise FormulaDataError("公式发生除零")
                    return left / right
                if isinstance(node.op, ast.Pow):
                    if not _is_number(right) or abs(float(right)) > 64:
                        raise FormulaDataError("幂指数必须是绝对值不超过 64 的有限数")
                    return left ** right
                if isinstance(node.op, ast.Mod):
                    if float(right) == 0.0:
                        raise FormulaDataError("公式发生模零")
                    return left % right
            except (OverflowError, ValueError, TypeError) as exc:
                raise FormulaDataError(f"数值运算失败：{ast.dump(node)}") from exc
            raise FormulaSyntaxError(f"不允许的二元运算：{type(node.op).__name__}")

        if isinstance(node, ast.UnaryOp):
            value = self._node(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.Not):
                return not bool(value)
            raise FormulaSyntaxError(f"不允许的一元运算：{type(node.op).__name__}")

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for item in node.values:
                    if not bool(self._node(item)):
                        return False
                return True
            if isinstance(node.op, ast.Or):
                for item in node.values:
                    if bool(self._node(item)):
                        return True
                return False
            raise FormulaSyntaxError(f"不允许的逻辑运算：{type(node.op).__name__}")

        if isinstance(node, ast.Compare):
            left = self._node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._node(comparator)
                if not self._compare(left, op, right):
                    return False
                left = right
            return True

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise FormulaSyntaxError("只允许调用白名单数学函数")
            if node.keywords:
                raise FormulaSyntaxError("公式函数不接受关键字参数")
            args = [self._node(arg) for arg in node.args]
            try:
                return _FUNCTIONS[node.func.id](*args)
            except (OverflowError, ValueError, TypeError, ZeroDivisionError) as exc:
                raise FormulaDataError(f"函数 {node.func.id} 计算失败") from exc

        raise FormulaSyntaxError(f"不允许的表达式节点：{type(node).__name__}")

    def _compare(self, left: Any, op: ast.cmpop, right: Any) -> bool:
        if isinstance(op, (ast.Eq, ast.NotEq)) and _is_number(left) and _is_number(right):
            equal = abs(float(left) - float(right)) <= self.equality_tolerance
            return equal if isinstance(op, ast.Eq) else not equal
        try:
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.Lt):
                return left < right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.GtE):
                return left >= right
        except TypeError as exc:
            raise FormulaSyntaxError(f"无法比较 {type(left).__name__} 与 {type(right).__name__}") from exc
        raise FormulaSyntaxError(f"不允许的比较运算：{type(op).__name__}")


def _validate_expression(expression: str) -> set[str]:
    if not str(expression).strip():
        raise FormulaSyntaxError("表达式不能为空")
    try:
        tree = ast.parse(str(expression), mode="eval")
    except SyntaxError as exc:
        raise FormulaSyntaxError(f"表达式语法错误：{expression!r}") from exc
    names: set[str] = set()
    allowed = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.UnaryOp,
        ast.UAdd,
        ast.USub,
        ast.Not,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.Compare,
        *_COMPARE_OPS,
        ast.Call,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise FormulaSyntaxError(f"不允许的表达式节点：{type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (bool, int, float)):
            raise FormulaSyntaxError(f"不允许的常量：{node.value!r}")
        if isinstance(node, ast.Name):
            if node.id not in _FUNCTIONS and node.id not in _CONSTANTS:
                names.add(node.id)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise FormulaSyntaxError("只允许调用白名单数学函数")
            if node.keywords:
                raise FormulaSyntaxError("公式函数不接受关键字参数")
    return names


def _ordered_variables(variables: Mapping[str, str]) -> list[str]:
    deps = {name: _validate_expression(expr) & set(variables) for name, expr in variables.items()}
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise FormulaSyntaxError(f"公式变量存在循环依赖：{name}")
        visiting.add(name)
        for dep in sorted(deps[name]):
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in variables:
        visit(name)
    return ordered


@dataclass
class DecisionResult:
    condition: str
    triggered: bool
    measured: float | None = None
    threshold: float | None = None
    margin: float | None = None
    operator: str = ""
    unit: str = ""
    severity: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "condition": self.condition,
            "triggered": self.triggered,
            "measured": self.measured,
            "threshold": self.threshold,
            "margin": self.margin,
            "operator": self.operator,
            "unit": self.unit,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class FormulaResult:
    formula_id: str
    values: dict[str, Any]
    decisions: list[DecisionResult] = field(default_factory=list)
    iterations: int = 0
    residual: float = 0.0

    def to_dict(self) -> dict:
        return {
            "formula_id": self.formula_id,
            "values": dict(self.values),
            "decisions": [d.to_dict() for d in self.decisions],
            "iterations": self.iterations,
            "residual": self.residual,
        }


class FormulaProgram:
    """已校验的公式模型。构造后不再依赖 Python 业务公式。"""

    def __init__(self, spec: Mapping[str, Any]):
        self.spec = dict(spec)
        self.formula_id = str(spec.get("id") or "")
        if not self.formula_id:
            raise FormulaSyntaxError("公式模型缺少 id")

        inputs = spec.get("inputs") or {}
        if not isinstance(inputs, Mapping):
            raise FormulaSyntaxError(f"{self.formula_id}: inputs 必须是对象")
        self.inputs = dict(inputs)

        constants = spec.get("constants") or {}
        if not isinstance(constants, Mapping):
            raise FormulaSyntaxError(f"{self.formula_id}: constants 必须是对象")
        self.constants = dict(constants)
        for name, value in self.constants.items():
            if not _is_number(value):
                raise FormulaSyntaxError(f"{self.formula_id}: 常量 {name} 必须是数值")

        raw_variables = spec.get("variables") or {}
        if not isinstance(raw_variables, Mapping):
            raise FormulaSyntaxError(f"{self.formula_id}: variables 必须是对象")
        self.variables: dict[str, str] = {}
        self.units: dict[str, str] = {}
        for name, item in raw_variables.items():
            if isinstance(item, str):
                expr = item
                unit = ""
            elif isinstance(item, Mapping):
                expr = str(item.get("expression") or "")
                unit = str(item.get("unit") or "")
            else:
                raise FormulaSyntaxError(f"{self.formula_id}: 变量 {name} 定义格式错误")
            self.variables[str(name)] = expr
            self.units[str(name)] = unit
        if not self.variables:
            raise FormulaSyntaxError(f"{self.formula_id}: 至少需要一个变量")
        self.ordered_variables = _ordered_variables(self.variables)

        solve = spec.get("solve") or {}
        self.solve = dict(solve) if solve else {}
        self.unknown = str(self.solve.get("unknown") or "")
        self.equation = str(self.solve.get("equation") or "")
        if bool(self.solve) != bool(self.unknown and self.equation):
            raise FormulaSyntaxError(f"{self.formula_id}: solve 必须同时给出 unknown 和 equation")
        if self.unknown:
            for key in ("lower", "upper", "absolute_tolerance", "max_iterations"):
                if key not in self.solve:
                    raise FormulaSyntaxError(f"{self.formula_id}: solve 缺少 {key}")
            _validate_expression(self.equation)
            _validate_expression(str(self.solve["lower"]))
            _validate_expression(str(self.solve["upper"]))

        decisions = spec.get("decisions")
        if decisions is None:
            decisions = [spec["decision"]] if spec.get("decision") else []
        if not isinstance(decisions, list) or not decisions:
            raise FormulaSyntaxError(f"{self.formula_id}: 至少需要一条 decision")
        self.decisions: list[dict] = []
        for item in decisions:
            if not isinstance(item, Mapping) or not str(item.get("condition") or "").strip():
                raise FormulaSyntaxError(f"{self.formula_id}: decision 缺少 condition")
            decision = dict(item)
            _validate_expression(str(decision["condition"]))
            if decision.get("margin"):
                _validate_expression(str(decision["margin"]))
            self.decisions.append(decision)

        declared_inputs = set(self.inputs)
        base_names = declared_inputs | set(self.constants) | set(self.variables)
        if self.unknown:
            base_names.add(self.unknown)
        for name, expr in self.variables.items():
            missing = _validate_expression(expr) - base_names
            if missing:
                raise FormulaSyntaxError(f"{self.formula_id}: 变量 {name} 引用未声明输入 {sorted(missing)}")
        for decision in self.decisions:
            missing = _validate_expression(str(decision["condition"])) - base_names
            if missing:
                raise FormulaSyntaxError(
                    f"{self.formula_id}: 判定式引用未声明输入 {sorted(missing)}"
                )
        if self.unknown and self.unknown in declared_inputs:
            raise FormulaSyntaxError(f"{self.formula_id}: 求解未知量不能同时是输入")

    def _validate_inputs(self, inputs: Mapping[str, Any]) -> tuple[dict[str, float], list[str]]:
        values: dict[str, float] = {}
        missing: list[str] = []
        for name in self.inputs:
            if name not in inputs or inputs[name] is None:
                missing.append(name)
                continue
            value = inputs[name]
            if not _is_number(value):
                raise FormulaDataError(f"{self.formula_id}: 输入 {name} 必须是数值")
            values[name] = float(value)
        if missing:
            raise FormulaDataError("缺少公式输入：" + "、".join(missing))
        return values, missing

    def _values_for(self, inputs: Mapping[str, Any], unknown_value: float | None = None) -> dict[str, Any]:
        context: dict[str, Any] = dict(self.constants)
        context.update(inputs)
        tolerance = float(self.spec.get("equality_tolerance", 0.0))
        evaluator = _Evaluator(context, equality_tolerance=tolerance)
        if unknown_value is not None:
            context[self.unknown] = float(unknown_value)
        for name in self.ordered_variables:
            value = evaluator.evaluate(self.variables[name])
            context[name] = value
        return context

    def _solve(self, inputs: Mapping[str, Any]) -> tuple[float, int, float]:
        base_context = dict(self.constants)
        base_context.update(inputs)
        evaluator = _Evaluator(base_context)
        lower = _as_number(evaluator.evaluate(str(self.solve["lower"])), str(self.solve["lower"]))
        upper = _as_number(evaluator.evaluate(str(self.solve["upper"])), str(self.solve["upper"]))
        if not lower < upper:
            raise FormulaDataError(f"{self.formula_id}: 求解区间必须满足 lower < upper")

        def residual(value: float) -> float:
            context = self._values_for(inputs, value)
            return _as_number(_Evaluator(context).evaluate(self.equation), self.equation)

        f_low = residual(lower)
        f_high = residual(upper)
        if abs(f_low) <= 1e-12:
            return lower, 0, f_low
        if abs(f_high) <= 1e-12:
            return upper, 0, f_high
        if f_low * f_high > 0.0:
            raise FormulaDataError(
                f"{self.formula_id}: 方程在 [{lower:g}, {upper:g}] 内没有符号变化，无法求稳态"
            )

        max_iterations = int(self.solve["max_iterations"])
        tolerance = float(self.solve["absolute_tolerance"])
        if max_iterations <= 0 or tolerance <= 0:
            raise FormulaSyntaxError(f"{self.formula_id}: 求解迭代数和容差必须为正")
        lo, hi = lower, upper
        f_lo = f_low
        best_value = 0.5 * (lo + hi)
        best_residual = residual(best_value)
        for iteration in range(1, max_iterations + 1):
            mid = 0.5 * (lo + hi)
            f_mid = residual(mid)
            best_value, best_residual = mid, f_mid
            if abs(f_mid) <= tolerance or 0.5 * (hi - lo) <= tolerance:
                return mid, iteration, f_mid
            if f_lo * f_mid <= 0.0:
                hi = mid
            else:
                lo, f_lo = mid, f_mid
        raise FormulaDataError(
            f"{self.formula_id}: {max_iterations} 次迭代未收敛，残差 {best_residual:g}"
        )

    def _decision_result(
        self,
        decision: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> DecisionResult:
        condition = str(decision["condition"])
        tolerance = float(decision.get("equality_tolerance", self.spec.get("equality_tolerance", 0.0)))
        evaluator = _Evaluator(context, equality_tolerance=tolerance)
        triggered = bool(evaluator.evaluate(condition))
        measured = None
        threshold = None
        margin = None
        operator = ""
        try:
            tree = ast.parse(condition, mode="eval")
            if isinstance(tree.body, ast.Compare) and len(tree.body.ops) == 1:
                left = _Evaluator(context, tolerance).evaluate(ast.unparse(tree.body.left))
                right = _Evaluator(context, tolerance).evaluate(ast.unparse(tree.body.comparators[0]))
                if _is_number(left) and _is_number(right):
                    measured, threshold = float(left), float(right)
                    operator = _OP_TEXT.get(type(tree.body.ops[0]), "")
        except (SyntaxError, FormulaError):
            pass
        if measured is not None and threshold is not None:
            margin_expr = decision.get("margin")
            if margin_expr:
                margin = _as_number(evaluator.evaluate(str(margin_expr)), str(margin_expr))
            elif operator in (">", ">="):
                margin = threshold - measured
            elif operator in ("<", "<="):
                margin = measured - threshold
            else:
                margin = abs(measured - threshold)
        return DecisionResult(
            condition=condition,
            triggered=triggered,
            measured=measured,
            threshold=threshold,
            margin=margin,
            operator=operator,
            unit=str(decision.get("unit") or ""),
            severity=str(decision.get("severity") or ""),
            message=str(decision.get("message") or ""),
        )

    def evaluate(self, inputs: Mapping[str, Any]) -> FormulaResult:
        values, _missing = self._validate_inputs(inputs)
        iterations = 0
        residual = 0.0
        if self.unknown:
            solved, iterations, residual = self._solve(values)
            context = self._values_for(values, solved)
        else:
            context = self._values_for(values)
        decisions = [self._decision_result(item, context) for item in self.decisions]
        public_values = {
            name: value
            for name, value in context.items()
            if name not in self.constants and name not in self.inputs
        }
        return FormulaResult(
            formula_id=self.formula_id,
            values=public_values,
            decisions=decisions,
            iterations=iterations,
            residual=residual,
        )

    def apply_solver_overrides(
        self,
        inputs: Mapping[str, Any],
        overrides: Mapping[str, Any],
    ) -> FormulaResult:
        """用已收敛求解结果替换同名输出，再执行同一组规则比较式。

        该入口不把求解结果写回公式输入，只替换规则可见的输出，便于同时保留
        ``formula_values``（交叉校核）和 ``solver_outputs``（正式判定依据）。
        """
        values, _missing = self._validate_inputs(inputs)
        unknown_value = overrides.get(self.unknown) if self.unknown else None
        context = self._values_for(values, unknown_value)
        allowed = set(self.variables) | ({self.unknown} if self.unknown else set())
        for name, value in overrides.items():
            if name not in allowed:
                raise FormulaDataError(f"{self.formula_id}: 不能覆盖未声明输出 {name}")
            if not _is_number(value):
                raise FormulaDataError(f"{self.formula_id}: 求解输出 {name} 必须是数值")
            context[name] = float(value)
        decisions = [self._decision_result(item, context) for item in self.decisions]
        public_values = {
            name: context[name]
            for name in self.ordered_variables
            if name in context
        }
        if self.unknown:
            public_values[self.unknown] = context[self.unknown]
        return FormulaResult(
            formula_id=self.formula_id,
            values=public_values,
            decisions=decisions,
        )

    def validate(self) -> dict:
        """静态检查公式和单位标注，返回可用于规则页展示的摘要。"""
        missing_units = [name for name, unit in self.units.items() if not unit]
        missing_input_units = [
            name
            for name, item in self.inputs.items()
            if not isinstance(item, Mapping) or not str(item.get("unit") or "")
        ]
        if missing_units or missing_input_units:
            raise FormulaSyntaxError(
                f"{self.formula_id}: 以下变量缺单位；variables={missing_units}, inputs={missing_input_units}"
            )
        return {
            "id": self.formula_id,
            "inputs": sorted(self.inputs),
            "variables": list(self.ordered_variables),
            "unknown": self.unknown,
            "decisions": [d["condition"] for d in self.decisions],
        }


def compile_formula(spec: Mapping[str, Any]) -> FormulaProgram:
    return FormulaProgram(spec)


@lru_cache(maxsize=64)
def _load_library(path: str, mtime_ns: int) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if str(payload.get("schema_version") or "") != "2.0.0":
        raise FormulaSyntaxError(f"{path}: formula library schema_version 必须为 2.0.0")
    models = payload.get("models")
    if not isinstance(models, dict):
        raise FormulaSyntaxError(f"{path}: models 必须是对象")
    return models


def load_formula(formula_ref: str, path: str = DEFAULT_FORMULA_LIBRARY) -> FormulaProgram:
    resolved = os.path.abspath(path)
    models = _load_library(resolved, os.stat(resolved).st_mtime_ns)
    if formula_ref not in models:
        raise FormulaDataError(f"公式库 {path} 中不存在 {formula_ref}")
    return compile_formula(models[formula_ref])


def formula_for_rule(rule: Any, path: str = DEFAULT_FORMULA_LIBRARY) -> FormulaProgram:
    inline = getattr(rule, "formula", None) or {}
    if inline:
        return compile_formula(inline)
    ref = str(getattr(rule, "formula_ref", "") or getattr(rule, "check_item_id", "") or "")
    if not ref:
        raise FormulaDataError("规则没有 formula 或 formula_ref")
    return load_formula(ref, path)


def validate_formula_library(path: str = DEFAULT_FORMULA_LIBRARY) -> list[dict]:
    resolved = os.path.abspath(path)
    models = _load_library(resolved, os.stat(resolved).st_mtime_ns)
    return [compile_formula(spec).validate() for spec in models.values()]


def round_value(value: float | None, decision: Mapping[str, Any] | None = None, default_digits: int | None = None) -> float | None:
    """按判定配置舍入；舍入只作用于展示，不改变比较结果。"""
    if value is None:
        return None
    digits = default_digits
    if decision and decision.get("rounding_digits") is not None:
        digits = int(decision["rounding_digits"])
    if digits is None:
        return value
    return round(float(value), digits)
