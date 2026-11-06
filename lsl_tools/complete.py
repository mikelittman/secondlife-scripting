"""Completion for LSL and SLua.

Library names come from secondlife/lsl-definitions. `ll.Say` completes from the
`ll` module. `llOwnerSay` completes in LSL. Removed functions are omitted.
"""

from __future__ import annotations

import re

from lsl_tools.symbols import lsl_symbols, slua_symbols

FUNCTION = 3
METHOD = 2
VARIABLE = 6
MODULE = 9
CONSTANT = 21
EVENT = 23
DEPRECATED = 1

_MEMBER = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*([.:])\s*([A-Za-z0-9_]*)$")
_IDENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)$")

# Methods from slua_definitions.yaml classes. `self` is not shown.
_METHODS = {
    "LLEvents": {
        "on": ("event: LLEventName, callback: function", "function", "Registers a handler. Returns the same function."),
        "off": ("event: LLEventName, callback: function", "boolean", "Removes one handler."),
        "once": ("event: LLEventName, callback: function", "function", "Registers a handler that runs once."),
        "handlers": ("event: LLEventName", "{function}", "Returns the handlers registered for an event."),
        "eventNames": ("", "{string}", "Returns the event names that have handlers."),
    },
    "LLTimers": {
        "every": ("seconds: number, callback: function", "function", "Registers a repeating timer."),
        "once": ("seconds: number, callback: function", "function", "Registers a one-shot timer."),
        "off": ("callback: function", "boolean", "Removes a timer."),
    },
}


def complete(language_id: str, text: str, line: int, character: int) -> list[dict]:
    rows = text.split("\n")
    if line < 0 or line >= len(rows) or character < 0:
        return []
    source = rows[line][:character]
    if _inside_literal(source, language_id):
        return []
    member = _MEMBER.search(source)
    if member and member.end() == len(source):
        return _members(language_id, member.group(1), member.group(2), member.group(3), line, character)
    ident = _IDENT.search(source)
    if ident and ident.end() == len(source):
        return _idents(language_id, ident.group(1), line, character)
    return []


def _members(language_id: str, owner: str, separator: str, partial: str, line: int, character: int) -> list[dict]:
    items: list[dict] = []
    if language_id == "lsl":
        return items
    symbols = slua_symbols()
    if separator == ".":
        module = (symbols.get("modules") or {}).get(owner) or {}
        for name, info in (module.get("functions") or {}).items():
            if info.get("removed"):
                continue
            items.append(_item(name, FUNCTION, _call_signature(name, info), info.get("tooltip") or "", info.get("deprecated"), partial, line, character))
        for name, info in (module.get("constants") or {}).items():
            detail = info.get("type") or "constant"
            items.append(_item(name, CONSTANT, detail, info.get("tooltip") or "", None, partial, line, character))
    else:
        methods = _METHODS.get(owner) or {}
        for name, (params, returns, tooltip) in methods.items():
            detail = f"{name}({params})"
            if returns:
                detail += f" -> {returns}"
            items.append(_item(name, METHOD, detail, tooltip, None, partial, line, character))
    return _filter(items, partial)


def _idents(language_id: str, partial: str, line: int, character: int) -> list[dict]:
    items: list[dict] = []
    if language_id == "lsl":
        symbols = lsl_symbols()
        for name, info in (symbols.get("functions") or {}).items():
            items.append(_item(name, FUNCTION, _lsl_signature(name, info), info.get("tooltip") or "", info.get("deprecated"), partial, line, character))
        for name, info in (symbols.get("events") or {}).items():
            items.append(_item(name, EVENT, _lsl_signature(name, info), info.get("tooltip") or "", info.get("deprecated"), partial, line, character))
        if len(partial) >= 2:
            for name, info in (symbols.get("constants") or {}).items():
                if info.get("private"):
                    continue
                detail = info.get("type") or "constant"
                items.append(_item(name, CONSTANT, detail, info.get("tooltip") or "", info.get("deprecated"), partial, line, character))
        return _filter(items, partial)
    symbols = slua_symbols()
    for name, module in (symbols.get("modules") or {}).items():
        items.append(_item(name, MODULE, "module", module.get("tooltip") or "", None, partial, line, character))
    for item in symbols.get("globals") or []:
        items.append(_item(item.get("name") or "", VARIABLE, item.get("type") or "global", item.get("tooltip") or "", None, partial, line, character))
    for item in symbols.get("builtins") or []:
        if item.get("removed"):
            continue
        name = item.get("name") or ""
        items.append(_item(name, FUNCTION, _call_signature(name, item), item.get("tooltip") or "", item.get("deprecated"), partial, line, character))
    return _filter(items, partial)


def _item(label: str, kind: int, detail: str, tooltip: str, deprecated, partial: str, line: int, character: int) -> dict:
    if not label:
        return {}
    item = {
        "label": label,
        "kind": kind,
        "detail": detail,
        "filterText": label,
        "sortText": ("1" if deprecated else "0") + label.lower(),
        "textEdit": {
            "range": {
                "start": {"line": line, "character": max(character - len(partial), 0)},
                "end": {"line": line, "character": character},
            },
            "newText": label,
        },
    }
    if tooltip:
        item["documentation"] = {"kind": "markdown", "value": tooltip}
    if deprecated:
        item["tags"] = [DEPRECATED]
    return item


def _filter(items: list[dict], partial: str) -> list[dict]:
    items = [item for item in items if item]
    if not partial:
        return items
    folded = partial.lower()
    return [item for item in items if item["label"].lower().startswith(folded)]


def _call_signature(name: str, info: dict) -> str:
    params = [_param(param) for param in info.get("params") or [] if (param.get("name") or "") != "self"]
    rendered = f"{name}({', '.join(part for part in params if part)})"
    returns = info.get("return") or ""
    if returns and returns not in {"void", "()"}:
        rendered += f" -> {returns}"
    return rendered


def _param(param: dict) -> str:
    name = param.get("name") or ""
    typ = param.get("type") or ""
    if param.get("variadic") or name == "..." or typ.startswith("..."):
        return "..."
    text = name
    if typ:
        text += f": {typ}"
    if param.get("optional"):
        text += "?"
    return text


def _lsl_signature(name: str, info: dict) -> str:
    parts = []
    for arg in info.get("arguments") or []:
        label = arg.get("name") or ""
        typ = arg.get("type") or ""
        parts.append(f"{typ} {label}".strip())
    rendered = f"{name}({', '.join(parts)})"
    returns = info.get("return") or ""
    if returns and returns != "void":
        rendered = f"{returns} {rendered}"
    return rendered


def _inside_literal(source: str, language_id: str) -> bool:
    i = 0
    while i < len(source):
        if language_id == "lsl" and source.startswith("//", i):
            return True
        if language_id != "lsl" and source.startswith("--", i):
            return True
        if source[i] in "\"'`":
            quote = source[i]
            i += 1
            while i < len(source) and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            if i >= len(source):
                return True
        i += 1
    return False
