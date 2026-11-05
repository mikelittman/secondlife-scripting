"""ANSI highlighting from the same token kinds the editor queries use."""

from __future__ import annotations

import re

from lsl_tools.model import Token
from lsl_tools.registry import Language
from lsl_tools.symbols import lsl_symbols, slua_symbols

_COLOR = {
    "comment": "\033[32m",
    "string": "\033[33m",
    "number": "\033[35m",
    "keyword": "\033[34m",
    "type": "\033[36m",
    "function": "\033[93m",
    "constant": "\033[91m",
    "event": "\033[96m",
    "operator": "\033[37m",
    "error": "\033[31m",
}
_RESET = "\033[0m"
_LL = re.compile(r"^ll[A-Z]")
_CONST = re.compile(r"^[A-Z][A-Z0-9_]*$")


def highlight(source: str, language: Language, color: bool = True) -> str:
    tokens = language.tokenize(source)
    classes = _classes(language)
    pieces = []
    cursor = 0
    for token in tokens:
        if token.kind == "eof":
            break
        pieces.append(source[cursor : token.span.start_offset])
        kind = _kind(token, classes)
        text = source[token.span.start_offset : token.span.end_offset]
        if color and kind in _COLOR:
            text = _COLOR[kind] + text + _RESET
        pieces.append(text)
        cursor = token.span.end_offset
    pieces.append(source[cursor:])
    return "".join(pieces)


def _classes(language: Language) -> dict[str, str]:
    if language.id == "lsl":
        symbols = lsl_symbols()
        kinds = {name: "function" for name in symbols["functions"]}
        kinds.update({name: "constant" for name in symbols["constants"]})
        kinds.update({name: "event" for name in symbols["events"]})
        return kinds
    symbols = slua_symbols()
    kinds = {item["name"]: "function" for item in symbols.get("builtins", [])}
    for module, body in symbols.get("modules", {}).items():
        kinds[module] = "constant"
        for name in body.get("functions", {}):
            kinds[f"{module}.{name}"] = "function"
    return kinds


def _kind(token: Token, classes: dict[str, str]) -> str:
    if token.kind == "identifier":
        if token.text in classes:
            return classes[token.text]
        if _LL.match(token.text):
            return "function"
        if _CONST.match(token.text):
            return "constant"
    if token.kind == "keyword":
        return "keyword"
    return token.kind
