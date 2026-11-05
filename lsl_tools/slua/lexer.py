"""Lexer for SLua. The syntax is Luau, including long strings and interpolation."""

from __future__ import annotations

from lsl_tools.model import Span, Token

KEYWORDS = {
    "and",
    "break",
    "continue",
    "do",
    "else",
    "elseif",
    "end",
    "export",
    "false",
    "for",
    "function",
    "if",
    "in",
    "local",
    "nil",
    "not",
    "or",
    "repeat",
    "return",
    "then",
    "true",
    "type",
    "typeof",
    "until",
    "while",
}
THREE = ("//=", "..=", "...")
TWO = ("..", "//", "<<", ">>", "==", "~=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "^=", "::", "->")
SINGLE = set("+-*/%^#=<>(){}[];:,.~&|?.")


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.n = len(source)
        self.i = 0
        self.line = 1
        self.col = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.i < self.n:
            self._space()
            if self.i >= self.n:
                break
            start = (self.i, self.line, self.col)
            if self.source[self.i] == "-" and self._at(1) == "-":
                self._comment()
                tokens.append(self._token("comment", *start))
                continue
            if self.source[self.i] in "\"'":
                self._short_string(self.source[self.i])
                tokens.append(self._token("string", *start))
                continue
            if self.source[self.i] == "`":
                self._interp()
                tokens.append(self._token("string", *start))
                continue
            level = self._open_long(self.i)
            if level is not None:
                self._long(level)
                tokens.append(self._token("string", *start))
                continue
            if self._is_number_start():
                self._number()
                tokens.append(self._token("number", *start))
                continue
            if self.source[self.i].isalpha() or self.source[self.i] == "_":
                self._word()
                text = self.source[start[0] : self.i]
                kind = "keyword" if text in KEYWORDS else "identifier"
                tokens.append(self._token(kind, *start))
                continue
            three = self.source[self.i : self.i + 3]
            if three in THREE:
                self._bump(3)
                tokens.append(self._token("operator", *start))
                continue
            two = self.source[self.i : self.i + 2]
            if two in TWO:
                self._bump(2)
                tokens.append(self._token("operator", *start))
                continue
            if self.source[self.i] in SINGLE:
                self._bump()
                tokens.append(self._token("operator", *start))
                continue
            self._bump()
            tokens.append(self._token("error", *start))
        eof = Span(self.line, self.col, self.line, self.col, self.i, self.i)
        tokens.append(Token("eof", "", eof))
        return tokens

    def _token(self, kind: str, start_i: int, start_line: int, start_col: int) -> Token:
        return Token(kind, self.source[start_i : self.i], Span(start_line, start_col, self.line, self.col, start_i, self.i))

    def _at(self, offset: int) -> str:
        index = self.i + offset
        return self.source[index] if index < self.n else ""

    def _bump(self, count: int = 1) -> None:
        for _ in range(count):
            if self.i >= self.n:
                return
            ch = self.source[self.i]
            self.i += 1
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1

    def _space(self) -> None:
        while self.i < self.n and self.source[self.i] in " \t\r\n":
            self._bump()

    def _comment(self) -> None:
        self._bump(2)
        level = self._open_long(self.i)
        if level is None:
            while self.i < self.n and self.source[self.i] != "\n":
                self._bump()
            return
        self._long(level)

    def _open_long(self, index: int) -> int | None:
        if index >= self.n or self.source[index] != "[":
            return None
        level = 0
        cursor = index + 1
        while cursor < self.n and self.source[cursor] == "=":
            level += 1
            cursor += 1
        if cursor < self.n and self.source[cursor] == "[":
            return level
        return None

    def _long(self, level: int) -> None:
        self._bump(2 + level)
        close = "]" + ("=" * level) + "]"
        while self.i < self.n and not self.source.startswith(close, self.i):
            self._bump()
        if self.i < self.n:
            self._bump(len(close))

    def _short_string(self, quote: str) -> None:
        self._bump()
        while self.i < self.n:
            ch = self.source[self.i]
            self._bump()
            if ch == "\\":
                if self.i < self.n:
                    self._bump()
                continue
            if ch == quote or ch == "\n":
                return

    def _interp(self) -> None:
        self._bump()
        depth = 0
        while self.i < self.n:
            ch = self.source[self.i]
            if ch == "`" and depth == 0:
                self._bump()
                return
            if ch == "{":
                depth += 1
                self._bump()
                continue
            if ch == "}" and depth:
                depth -= 1
                self._bump()
                continue
            if depth and ch in "\"'":
                self._short_string(ch)
                continue
            if depth and ch == "`":
                self._interp()
                continue
            if depth and ch == "-" and self._at(1) == "-":
                self._comment()
                continue
            if ch == "\\":
                self._bump()
                if self.i < self.n:
                    self._bump()
                continue
            self._bump()

    def _is_number_start(self) -> bool:
        ch = self.source[self.i]
        if ch.isdigit():
            return True
        return ch == "." and self._at(1).isdigit()

    def _number(self) -> None:
        if self.source[self.i] == "0" and self._at(1) in "xXbB":
            self._bump(2)
            while self.i < self.n and (self.source[self.i].isalnum() or self.source[self.i] == "_"):
                self._bump()
            return
        saw_exp = False
        saw_dot = False
        while self.i < self.n:
            ch = self.source[self.i]
            if ch.isdigit() or ch == "_":
                self._bump()
                continue
            if ch == "." and not saw_dot and not saw_exp:
                saw_dot = True
                self._bump()
                continue
            if ch in "eE" and not saw_exp:
                saw_exp = True
                self._bump()
                if self._at(0) in "+-":
                    self._bump()
                continue
            break

    def _word(self) -> None:
        while self.i < self.n and (self.source[self.i].isalnum() or self.source[self.i] == "_"):
            self._bump()
