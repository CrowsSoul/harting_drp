# -*- coding: utf-8 -*-
"""表达式求值：AST + 符号上下文 -> 数值 / 布尔。

不做任何动态代码执行；所有类型与单位检查都在这里显式完成。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from . import parser as ast
from .errors import ExprMissingSymbol, ExprTypeError, ExprUnitError
from .units import (
    BASE_UNIT,
    Value,
    add,
    compare,
    convert,
    dimension,
    div,
    mul,
    normalize_unit,
    sub,
)


@dataclass(frozen=True)
class SymbolContext:
    """求值上下文。

    params : 合并后的规则参数（default_params ∪ rule.params）
    meas   : 单个特征的测量量（由 checker 组装）
    units  : 变量单位声明，如 ``{"meas.radius": "mm"}``；未声明的变量视为无量纲
    """

    params: dict[str, Any] = field(default_factory=dict)
    meas: dict[str, Any] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)


def _to_value(raw: Any, unit: str, namespace: str, name: str) -> Any:
    """把 dict 里的原始值转成求值用的类型。None 视为缺数据。"""
    if raw is None:
        raise ExprMissingSymbol(namespace, name)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return Value(float(raw), unit)
    if isinstance(raw, (str, dict, list, tuple)):
        return raw
    raise ExprTypeError(f"{namespace}.{name} 的类型 {type(raw).__name__} 不受支持")


def _as_value(result: Any, what: str) -> Value:
    if not isinstance(result, Value):
        raise ExprTypeError(f"{what} 需要数值表达式，实际得到 {type(result).__name__}")
    return result


def _as_bool(result: Any, what: str) -> bool:
    if not isinstance(result, bool):
        raise ExprTypeError(f"{what} 需要布尔表达式，实际得到 {type(result).__name__}")
    return result


def _lookup(var: ast.Var, ctx: SymbolContext) -> Any:
    table = ctx.params if var.namespace == "params" else ctx.meas
    if var.name not in table:
        raise ExprMissingSymbol(var.namespace, var.name)
    unit = normalize_unit(ctx.units.get(f"{var.namespace}.{var.name}", ""))
    return _to_value(table[var.name], unit, var.namespace, var.name)


def _unify(values: list[Value], what: str) -> tuple[list[float], str]:
    """把一组数值对齐到同一单位（无量纲值跟随第一个带单位的参数）。"""
    unit_hint = next((v.unit for v in values if v.unit), "")
    if not unit_hint:
        return [v.number for v in values], ""
    target = BASE_UNIT[dimension(unit_hint)]
    numbers: list[float] = []
    for value in values:
        if not value.unit:
            numbers.append(value.number)      # 无量纲按目标单位解释
            continue
        try:
            numbers.append(convert(value.number, value.unit, target))
        except ExprUnitError as exc:
            raise ExprUnitError(
                f"{what} 的单位不一致：{value.unit} vs {target}", value.unit, target
            ) from exc
    return numbers, target


def _round_half_away(number: float, digits: int) -> float:
    factor = 10.0 ** digits
    scaled = number * factor
    rounded = math.floor(abs(scaled) + 0.5) * (1.0 if scaled >= 0 else -1.0)
    return rounded / factor


def _eval_call(call: ast.Call, ctx: SymbolContext) -> Any:
    name = call.name
    if name == "if":
        cond = _as_bool(_eval(call.args[0], ctx), "if 的条件")
        return _eval(call.args[1] if cond else call.args[2], ctx)  # 惰性：只算命中分支
    if name == "table":
        mapping = _eval(call.args[0], ctx)
        if not isinstance(mapping, dict):
            raise ExprTypeError("table 的第一个参数必须是查表字典（如 params.material_min_wall_thickness_mm）")
        key = _eval(call.args[1], ctx)
        if isinstance(key, Value):
            key = key.number
        if key not in mapping:
            if str(key) in mapping:
                key = str(key)
            else:
                raise ExprMissingSymbol("table", str(key))
        raw = mapping[key]
        return _to_value(raw, "", "table", str(key))

    if name == "nearest":
        pool = _eval(call.args[0], ctx)
        if not isinstance(pool, (list, tuple)):
            raise ExprTypeError("nearest 的第一个参数必须是数值列表（如 params.standard_diameters）")
        if not pool:
            raise ExprMissingSymbol("nearest", "list")   # 空系列 = 缺数据，checker 跳过
        value = _as_value(_eval(call.args[1], ctx), "nearest 的第二个参数")
        numbers = []
        for item in pool:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ExprTypeError("nearest 的列表里只能有数值")
            numbers.append(float(item))
        best = min(numbers, key=lambda n: abs(n - value.number))
        return Value(best, value.unit)

    args = [_as_value(_eval(arg, ctx), f"{name} 的参数") for arg in call.args]
    if name in ("min", "max"):
        numbers, unit = _unify(args, name)
        result = min(numbers) if name == "min" else max(numbers)
        return Value(result, unit)
    if name == "abs":
        return Value(abs(args[0].number), args[0].unit)
    if name == "round":
        digits = 0
        if len(args) == 2:
            digits_value = args[1]
            if digits_value.unit or not float(digits_value.number).is_integer():
                raise ExprTypeError("round 的第二个参数必须是无单位整数")
            digits = int(digits_value.number)
        return Value(_round_half_away(args[0].number, digits), args[0].unit)
    raise ExprTypeError(f"未知函数 {name!r}")


def _eval(node: ast.Node, ctx: SymbolContext) -> Any:
    if isinstance(node, ast.Number):
        return Value(node.value, node.unit)
    if isinstance(node, ast.Var):
        return _lookup(node, ctx)
    if isinstance(node, ast.Unary):
        if node.op == "-":
            value = _as_value(_eval(node.operand, ctx), "一元负号")
            return Value(-value.number, value.unit)
        if node.op == "not":
            return not _as_bool(_eval(node.operand, ctx), "not")
        raise ExprTypeError(f"未知一元算子 {node.op!r}")
    if isinstance(node, ast.BoolOp):
        left = _as_bool(_eval(node.left, ctx), node.op)
        if node.op == "and":
            return left and _as_bool(_eval(node.right, ctx), node.op)
        if node.op == "or":
            return left or _as_bool(_eval(node.right, ctx), node.op)
        raise ExprTypeError(f"未知逻辑算子 {node.op!r}")
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        right = _eval(node.right, ctx)
        if isinstance(left, bool) or isinstance(right, bool):
            if not (isinstance(left, bool) and isinstance(right, bool)):
                raise ExprTypeError(f"不能把布尔与 {type(right if isinstance(left, bool) else left).__name__} 比较")
            if node.op == "==":
                return left == right
            if node.op == "!=":
                return left != right
            raise ExprTypeError(f"布尔值不支持 {node.op} 比较")
        if isinstance(left, Value) and isinstance(right, Value):
            a, b = compare(left, right)
            return {
                ">": a > b,
                "<": a < b,
                ">=": a >= b,
                "<=": a <= b,
                "==": a == b,
                "!=": a != b,
            }[node.op]
        if isinstance(left, str) and isinstance(right, str):
            if node.op == "==":
                return left == right
            if node.op == "!=":
                return left != right
            raise ExprTypeError(f"字符串不支持 {node.op} 比较")
        raise ExprTypeError(
            f"无法比较 {type(left).__name__} 与 {type(right).__name__}"
        )
    if isinstance(node, ast.Binary):
        left = _eval(node.left, ctx)
        right = _eval(node.right, ctx)
        if node.op == "+":
            return add(_as_value(left, "+"), _as_value(right, "+"))
        if node.op == "-":
            return sub(_as_value(left, "-"), _as_value(right, "-"))
        if node.op == "*":
            return mul(_as_value(left, "*"), _as_value(right, "*"))
        if node.op == "/":
            divisor = _as_value(right, "/")
            if divisor.number == 0:
                raise ExprTypeError("除数为零")
            return div(_as_value(left, "/"), divisor)
        if node.op == "^":
            base = _as_value(left, "^")
            exponent = _as_value(right, "^")
            if exponent.unit:
                raise ExprUnitError(f"指数不能带单位：{exponent.unit}")
            if not base.unit:
                return Value(base.number ** exponent.number)
            if base.unit in ("mm", "m", "inch") and exponent.number == 2:
                mm_value = base.number * {"mm": 1.0, "m": 1000.0, "inch": 25.4}[base.unit]
                return Value(mm_value ** 2, "mm2")
            raise ExprUnitError(f"不支持 {base.unit}^{exponent.number} 的幂运算", base.unit)
        raise ExprTypeError(f"未知二元算子 {node.op!r}")
    if isinstance(node, ast.Call):
        return _eval_call(node, ctx)
    raise ExprTypeError(f"未知节点 {type(node).__name__}")


def evaluate(node: ast.Node, ctx: SymbolContext) -> Any:
    """求值。返回 ``Value``（数值）、``bool`` 或 ``str``。"""
    return _eval(node, ctx)


def evaluate_str(source: str, ctx: SymbolContext) -> Any:
    """解析并求值一段表达式文本。"""
    return evaluate(ast.parse(source), ctx)
