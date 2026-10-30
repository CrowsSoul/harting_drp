# -*- coding: utf-8 -*-
"""表达式引擎的异常层级与失败语义。

约定（与 CLAUDE.md「缺数据一律 skipped / missing_data」一致）：

* ``ExprParseError``    规则书写错误 —— 加载规则时由 ``RuleBook.validate()`` 暴露；
* ``ExprRuleError``     expression 配置结构错误 —— 同上；
* ``ExprMissingSymbol`` 缺测量量 / 参数 / 查表键 —— checker 对该特征**跳过**，不猜；
* ``ExprTypeError``     类型错误（布尔参与算术、未知函数等）—— 规则数据问题，响亮报错；
* ``ExprUnitError``     单位量纲冲突 —— 规则数据问题，响亮报错。
"""

from __future__ import annotations


class ExprError(Exception):
    """表达式引擎错误基类。"""


class ExprParseError(ExprError):
    """语法错误。位置是源字符串里的 0 基下标。"""

    def __init__(self, message: str, position: int | None = None, source: str = ""):
        self.message = message
        self.position = position
        self.source = source
        super().__init__(str(self))

    def __str__(self) -> str:
        text = self.message
        if self.position is not None:
            text += f"（位置 {self.position}）"
        if self.source:
            text += f"\n  {self.source}\n  {' ' * self.position}^"
        return text


class ExprRuleError(ExprError):
    """expression 配置本身不成立（没有 cases、字段类型不对等）。"""


class ExprMissingSymbol(ExprError):
    """缺数据：变量不存在、值为 None、查表键不在表内。"""

    def __init__(self, namespace: str, name: str):
        self.namespace = namespace
        self.name = name
        super().__init__(f"缺少 {namespace}.{name}（缺数据跳过，不猜结果）")


class ExprTypeError(ExprError):
    """类型不匹配。"""


class ExprUnitError(ExprError):
    """单位量纲冲突。"""

    def __init__(self, message: str, left_unit: str = "", right_unit: str = ""):
        self.left_unit = left_unit
        self.right_unit = right_unit
        super().__init__(message)
