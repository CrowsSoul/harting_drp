# -*- coding: utf-8 -*-
"""手写词法器：只认受限 DSL 里的几类记号，全程不用 Python 的 eval/tokenize。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ExprParseError
from .units import normalize_unit

#: 数字：整数 / 小数 / 科学计数法
_NUMBER = re.compile(r"(\d+(?:\.\d*)?|\.\d+)([eE][+-]?\d+)?")
#: 单位后缀紧跟在数字后面，且后面不能再接标识符字符（避免把 ``2nd`` 切成 ``2`` + ``n``）
_UNIT = re.compile(r"(mm2|mm²|mm|deg|inch|m)(?![A-Za-z0-9_])")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

KEYWORDS = {"and", "or", "not"}
#: 需要 ``namespace.name`` 形式引用的两张变量表
NAMESPACES = {"params", "meas"}

_TWO_CHAR_OPS = (">=", "<=", "==", "!=")
_ONE_CHAR_OPS = "><+-*/^(),."


@dataclass(frozen=True)
class Token:
    kind: str          # num / name / kw / op / eof
    text: str
    pos: int
    value: float | None = None
    unit: str = ""

    def __repr__(self) -> str:  # 便于测试失败信息
        return f"Token({self.kind!r}, {self.text!r}, pos={self.pos})"


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    size = len(source)
    while i < size:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < size and source[i + 1].isdigit()):
            match = _NUMBER.match(source, i)
            assert match is not None
            text = match.group(0)
            number = float(text)
            i = match.end()
            unit = ""
            unit_match = _UNIT.match(source, i)
            if unit_match:
                unit = normalize_unit(unit_match.group(1))
                i = unit_match.end()
            tokens.append(Token("num", text, match.start(), number, unit))
            continue
        if ch.isalpha() or ch == "_":
            match = _IDENT.match(source, i)
            assert match is not None
            text = match.group(0)
            kind = "kw" if text in KEYWORDS else "name"
            tokens.append(Token(kind, text, match.start()))
            i = match.end()
            continue
        two = source[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("op", two, i))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(Token("op", ch, i))
            i += 1
            continue
        raise ExprParseError(f"无法识别的字符 {ch!r}", i, source)
    tokens.append(Token("eof", "", size))
    return tokens
