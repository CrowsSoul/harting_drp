# -*- coding: utf-8 -*-
"""轻量单位模型：只认白名单里的量纲，不做完整量纲分析。

量纲只有四类：

* ``length``：``mm`` / ``m`` / ``inch``
* ``angle``：``deg``
* ``area``：``mm2``
* ``ratio``：无单位（空串），比值、计数、系数都归这一类

规则里写 ``1.5mm`` 得到带 length 的量；``meas.radius`` 这类变量默认无量纲，
除非 expression 的 ``units`` 里显式声明（``{"meas.radius": "mm"}``）。
四则运算按量纲表粗查：长度×长度→面积、长度/长度→比值、长度±长度需同量纲；
比较要求两侧同量纲（无量纲字面量按另一侧的单位解释）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ExprUnitError

#: 单位 -> (量纲, 换算到基准单位的因子)。长度基准 mm，角度基准 deg，面积基准 mm2。
_UNIT_TABLE: dict[str, tuple[str, float]] = {
    "mm": ("length", 1.0),
    "m": ("length", 1000.0),
    "inch": ("length", 25.4),
    "deg": ("angle", 1.0),
    "mm2": ("area", 1.0),
}

NO_UNIT = ""

#: 每个量纲的基准单位：运算结果统一归到基准单位，保证 Finding 里总是 mm/deg/mm2
BASE_UNIT = {"length": "mm", "angle": "deg", "area": "mm2", "ratio": NO_UNIT}


@dataclass(frozen=True)
class Value:
    """带单位的数值。"""

    number: float
    unit: str = NO_UNIT

    def __repr__(self) -> str:  # 便于测试失败信息
        return f"Value({self.number!r}, {self.unit!r})"


def normalize_unit(text: str) -> str:
    """``mm²`` 归一为 ``mm2``；未知单位直接报错。"""
    unit = (text or "").strip()
    if unit in ("mm²", "mm^2"):
        unit = "mm2"
    if unit and unit not in _UNIT_TABLE:
        raise ExprUnitError(f"未知单位后缀 {unit!r}（白名单：mm / m / inch / deg / mm2）")
    return unit


def dimension(unit: str) -> str:
    if not unit:
        return "ratio"
    if unit not in _UNIT_TABLE:
        raise ExprUnitError(f"未知单位 {unit!r}")
    return _UNIT_TABLE[unit][0]


def same_dimension(a: str, b: str) -> bool:
    return dimension(a) == dimension(b)


def convert(number: float, from_unit: str, to_unit: str) -> float:
    """同量纲换算；量纲不同抛 ExprUnitError。"""
    if from_unit == to_unit:
        return number
    if not same_dimension(from_unit, to_unit):
        raise ExprUnitError(
            f"单位冲突：{from_unit or '无量纲'} 与 {to_unit or '无量纲'} 量纲不同",
            from_unit,
            to_unit,
        )
    _, from_factor = _UNIT_TABLE.get(from_unit, ("", 1.0))
    _, to_factor = _UNIT_TABLE.get(to_unit, ("", 1.0))
    return number * from_factor / to_factor


def to_base(value: Value) -> Value:
    """把带单位的值换到该量纲的基准单位（length→mm、area→mm2、angle→deg）。"""
    if not value.unit:
        return value
    base = BASE_UNIT[dimension(value.unit)]
    return Value(convert(value.number, value.unit, base), base)


def _align(a: Value, b: Value) -> tuple[float, float, str]:
    """把两个值对齐到同一单位，返回 (a 的数值, b 换算后的数值, 结果单位)。

    结果统一归一化到基准单位；无量纲字面量按另一侧的单位解释。
    """
    if not a.unit and not b.unit:
        return a.number, b.number, NO_UNIT
    if a.unit and b.unit:
        if not same_dimension(a.unit, b.unit):
            raise ExprUnitError(
                f"单位冲突：{a.unit} 与 {b.unit} 不能相加减或比较", a.unit, b.unit
            )
        base = BASE_UNIT[dimension(a.unit)]
        return convert(a.number, a.unit, base), convert(b.number, b.unit, base), base
    # 一侧无量纲：按另一侧的单位解释，再归一到基准单位
    unit = a.unit or b.unit
    base = BASE_UNIT[dimension(unit)]
    left = convert(a.number, a.unit, base) if a.unit else convert(a.number, unit, base)
    right = convert(b.number, b.unit, base) if b.unit else convert(b.number, unit, base)
    return left, right, base


def add(a: Value, b: Value) -> Value:
    left, right, unit = _align(a, b)
    return Value(left + right, unit)


def sub(a: Value, b: Value) -> Value:
    left, right, unit = _align(a, b)
    return Value(left - right, unit)


def mul(a: Value, b: Value) -> Value:
    if not a.unit and not b.unit:
        return Value(a.number * b.number)
    if not a.unit:
        return to_base(Value(a.number * b.number, b.unit))
    if not b.unit:
        return to_base(Value(a.number * b.number, a.unit))
    dim_a, dim_b = dimension(a.unit), dimension(b.unit)
    if dim_a == "length" and dim_b == "length":
        # 长度 × 长度 → 面积，统一换成 mm2
        left = convert(a.number, a.unit, "mm")
        right = convert(b.number, b.unit, "mm")
        return Value(left * right, "mm2")
    raise ExprUnitError(f"单位冲突：{a.unit} × {b.unit} 不在量纲白名单内", a.unit, b.unit)


def div(a: Value, b: Value) -> Value:
    if not b.unit:
        return to_base(Value(a.number / b.number, a.unit))
    if not a.unit:
        raise ExprUnitError(f"无量纲值不能除以 {b.unit}", a.unit, b.unit)
    if a.unit == b.unit:
        return Value(a.number / b.number)
    dim_a, dim_b = dimension(a.unit), dimension(b.unit)
    if dim_a == dim_b:
        return Value(convert(a.number, a.unit, b.unit) / b.number)
    if dim_a == "area" and dim_b == "length":
        return Value(convert(a.number, a.unit, "mm2") / convert(b.number, b.unit, "mm"), "mm")
    raise ExprUnitError(f"单位冲突：{a.unit} ÷ {b.unit} 不在量纲白名单内", a.unit, b.unit)


def compare(a: Value, b: Value) -> tuple[float, float]:
    left, right, _unit = _align(a, b)
    return left, right
