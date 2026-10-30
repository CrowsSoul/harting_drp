# -*- coding: utf-8 -*-
"""递归下降解析器：把受限 DSL 文本解析成 AST，不经过任何 Python 代码执行。

语法（优先级从低到高）::

    expr    := or_expr
    or_expr := and_expr ('or' and_expr)*
    and_expr:= not_expr ('and' not_expr)*
    not_expr:= 'not' not_expr | cmp
    cmp     := add (('>'|'<'|'>='|'<='|'=='|'!=') add)?      # 只允许单层比较
    add     := mul (('+'|'-') mul)*
    mul     := unary (('*'|'/') unary)*
    unary   := '-' unary | power
    power   := primary ('^' unary)?                           # 右结合
    primary := NUMBER[unit]
             | NAME '(' args ')'
             | '(' expr ')'
             | ('params'|'meas') '.' NAME
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .errors import ExprParseError
from .tokenizer import Token, tokenize

#: 函数白名单 -> (最少参数, 最多参数)；None 表示不限
FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "min": (1, None),
    "max": (1, None),
    "abs": (1, 1),
    "round": (1, 2),
    "if": (3, 3),
    "table": (2, 2),
}

COMPARE_OPS = (">", "<", ">=", "<=", "==", "!=")
ADD_OPS = ("+", "-")
MUL_OPS = ("*", "/")


# ---------------------------- AST 节点 ----------------------------
@dataclass(frozen=True)
class Number:
    value: float
    unit: str
    pos: int


@dataclass(frozen=True)
class Var:
    namespace: str
    name: str
    pos: int


@dataclass(frozen=True)
class Unary:
    op: str
    operand: "Node"
    pos: int


@dataclass(frozen=True)
class Binary:
    op: str
    left: "Node"
    right: "Node"
    pos: int


@dataclass(frozen=True)
class Compare:
    op: str
    left: "Node"
    right: "Node"
    pos: int


@dataclass(frozen=True)
class BoolOp:
    op: str
    left: "Node"
    right: "Node"
    pos: int


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple["Node", ...]
    pos: int


Node = (
    Number | Var | Unary | Binary | Compare | BoolOp | Call
)


class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.index = 0

    # ---------------- 记号游标 ----------------
    def _peek(self) -> Token:
        return self.tokens[self.index]

    def _next(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _error(self, message: str, token: Token | None = None) -> ExprParseError:
        token = token or self._peek()
        return ExprParseError(message, token.pos, self.source)

    def _is_op(self, text: str) -> bool:
        token = self._peek()
        return token.kind == "op" and token.text == text

    def _is_kw(self, text: str) -> bool:
        token = self._peek()
        return token.kind == "kw" and token.text == text

    def _expect_op(self, text: str) -> Token:
        if not self._is_op(text):
            raise self._error(f"期望 {text!r}，实际是 {self._peek().text!r}")
        return self._next()

    # ---------------- 语法规则 ----------------
    def parse(self) -> Node:
        node = self._expr()
        if self._peek().kind != "eof":
            raise self._error(f"多余的内容 {self._peek().text!r}")
        return node

    def _expr(self) -> Node:
        node = self._and()
        while self._is_kw("or"):
            token = self._next()
            node = BoolOp("or", node, self._and(), token.pos)
        return node

    def _and(self) -> Node:
        node = self._not()
        while self._is_kw("and"):
            token = self._next()
            node = BoolOp("and", node, self._not(), token.pos)
        return node

    def _not(self) -> Node:
        if self._is_kw("not"):
            token = self._next()
            return Unary("not", self._not(), token.pos)
        return self._cmp()

    def _cmp(self) -> Node:
        node = self._add()
        token = self._peek()
        if token.kind == "op" and token.text in COMPARE_OPS:
            self._next()
            node = Compare(token.text, node, self._add(), token.pos)
            if self._peek().kind == "op" and self._peek().text in COMPARE_OPS:
                raise self._error("不支持连续比较（如 a < b < c），请拆成 and")
        return node

    def _add(self) -> Node:
        node = self._mul()
        while self._peek().kind == "op" and self._peek().text in ADD_OPS:
            token = self._next()
            node = Binary(token.text, node, self._mul(), token.pos)
        return node

    def _mul(self) -> Node:
        node = self._unary()
        while self._peek().kind == "op" and self._peek().text in MUL_OPS:
            token = self._next()
            node = Binary(token.text, node, self._unary(), token.pos)
        return node

    def _unary(self) -> Node:
        if self._is_op("-"):
            token = self._next()
            return Unary("-", self._unary(), token.pos)
        if self._is_op("+"):
            self._next()  # 一元正号：无操作
            return self._unary()
        return self._power()

    def _power(self) -> Node:
        node = self._primary()
        if self._is_op("^"):
            token = self._next()
            node = Binary("^", node, self._unary(), token.pos)
        return node

    def _primary(self) -> Node:
        token = self._peek()
        if token.kind == "num":
            self._next()
            return Number(token.value, token.unit, token.pos)
        if token.kind == "op" and token.text == "(":
            self._next()
            node = self._expr()
            self._expect_op(")")
            return node
        if token.kind == "name":
            self._next()
            if self._is_op("."):
                self._next()
                field = self._peek()
                if field.kind != "name":
                    raise self._error("命名空间后必须是变量名")
                self._next()
                if token.text not in ("params", "meas"):
                    raise self._error(
                        f"未知命名空间 {token.text!r}（只允许 params / meas）", token
                    )
                return Var(token.text, field.text, token.pos)
            if self._is_op("("):
                return self._call(token)
            raise self._error(
                f"未知标识符 {token.text!r}（变量必须写成 params.x 或 meas.x）", token
            )
        raise self._error(f"意外的记号 {token.text!r}")

    def _call(self, token: Token) -> Node:
        name = token.text
        if name not in FUNCTIONS:
            raise self._error(
                f"未知函数 {name!r}（白名单：{', '.join(sorted(FUNCTIONS))}）", token
            )
        self._expect_op("(")
        args: list[Node] = []
        if not self._is_op(")"):
            args.append(self._expr())
            while self._is_op(","):
                self._next()
                args.append(self._expr())
        self._expect_op(")")
        low, high = FUNCTIONS[name]
        if len(args) < low or (high is not None and len(args) > high):
            span = f"{low}" if high == low else f"{low}~{high or '∞'}"
            raise self._error(f"函数 {name} 需要 {span} 个参数，实际 {len(args)} 个", token)
        return Call(name, tuple(args), token.pos)


@lru_cache(maxsize=512)
def parse(source: str) -> Node:
    """解析表达式文本。同一段文本只解析一次（lru_cache）。"""
    if not isinstance(source, str) or not source.strip():
        raise ExprParseError("表达式为空")
    return _Parser(source).parse()
