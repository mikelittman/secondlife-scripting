"""Lexer for Linden Scripting Language, following Tailslide's token set."""

from __future__ import annotations

from lsl_tools.model import Span, Token

KEYWORDS = {
    "default",
    "state",
    "event",
    "jump",
    "return",
    "if",
    "else",
    "for",
    "do",
    "while",
    "print",
}
TYPES = {"integer", "float", "string", "key", "vector", "quaternion", "rotation", "list"}
TWO_CHAR = ("++", "--", "+=", "-=", "*=", "/=", "%=", "==", "!=", ">=", "<=", "&&", "||", "<<", ">>")
SINGLE = set(".;{}=,()-+*/%@:><][&|^~!")


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
            self._skip_space()
            if self.i >= self.n:
                break
            start_i, start_line, start_col = self.i, self.line, self.col
            ch = self.source[self.i]
            if ch == "/" and self._peek(1) == "/":
                self._line_comment()
                tokens.append(self._token("comment", start_i, start_line, start_col))
                continue
            if ch == "/" and self._peek(1) == "*":
                self._block_comment()
                tokens.append(self._token("comment", start_i, start_line, start_col))
                continue
            if ch == '"' or (ch == "L" and self._peek(1) == '"'):
                self._string()
                tokens.append(self._token("string", start_i, start_line, start_col))
                continue
            if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
                self._number()
                tokens.append(self._token("number", start_i, start_line, start_col))
                continue
            if ch.isalpha() or ch == "_":
                self._word()
                text = self.source[start_i : self.i]
                kind = "type" if text in TYPES else "keyword" if text in KEYWORDS else "identifier"
                tokens.append(self._token(kind, start_i, start_line, start_col))
                continue
            two = self.source[self.i : self.i + 2]
            if two in TWO_CHAR:
                self._bump()
                self._bump()
                tokens.append(self._token("operator", start_i, start_line, start_col))
                continue
            if ch in SINGLE:
                self._bump()
                tokens.append(self._token("operator", start_i, start_line, start_col))
                continue
            self._bump()
            tokens.append(self._token("error", start_i, start_line, start_col))
        eof = Span(self.line, self.col, self.line, self.col, self.i, self.i)
        tokens.append(Token("eof", "", eof))
        return tokens

    def _token(self, kind: str, start_i: int, start_line: int, start_col: int) -> Token:
        span = Span(start_line, start_col, self.line, self.col, start_i, self.i)
        return Token(kind, self.source[start_i : self.i], span)

    def _peek(self, offset: int = 0) -> str:
        index = self.i + offset
        return self.source[index] if index < self.n else ""

    def _bump(self) -> str:
        ch = self.source[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _skip_space(self) -> None:
        while self.i < self.n and self.source[self.i] in " \t\r\n":
            self._bump()

    def _line_comment(self) -> None:
        while self.i < self.n and self.source[self.i] != "\n":
            self._bump()

    def _block_comment(self) -> None:
        self._bump()
        self._bump()
        while self.i < self.n:
            if self.source[self.i] == "*" and self._peek(1) == "/":
                self._bump()
                self._bump()
                return
            self._bump()

    def _string(self) -> None:
        if self.source[self.i] == "L":
            self._bump()
        self._bump()
        while self.i < self.n:
            ch = self._bump()
            if ch == "\\":
                if self.i < self.n:
                    self._bump()
                continue
            if ch == '"':
                return

    def _word(self) -> None:
        while self.i < self.n and (self.source[self.i].isalnum() or self.source[self.i] == "_"):
            self._bump()

    def _number(self) -> None:
        if self.source[self.i] == "0" and self._peek(1) in "xX":
            self._bump()
            self._bump()
            while self.i < self.n and self.source[self.i] in "0123456789abcdefABCDEF":
                self._bump()
            return
        saw_dot = False
        saw_exp = False
        while self.i < self.n:
            ch = self.source[self.i]
            if ch.isdigit():
                self._bump()
                continue
            if ch == "." and not saw_dot and not saw_exp:
                saw_dot = True
                self._bump()
                continue
            if ch in "eE" and not saw_exp:
                saw_exp = True
                self._bump()
                if self._peek() in "+-":
                    self._bump()
                continue
            if ch in "fF" and (saw_dot or saw_exp or self.source[self.i - 1].isdigit()):
                self._bump()
            break
