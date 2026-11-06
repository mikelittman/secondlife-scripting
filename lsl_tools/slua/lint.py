"""SLua lint rules. Severities live in languages/slua/lint.toml.

Syntax is Luau. Library checks follow secondlife/lsl-definitions, in particular
lsl_definitions/slua.py generate_ll_modules: slua-removed functions stay off ll,
llcompat functions are deprecated with no replacement, and slua-removed events
are not LLEventName values. A `?` in a Luau type allows nil. Only default-value
or optional: true means the argument may be left out.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lsl_tools.model import Diagnostic, Node, ParseResult
from lsl_tools.symbols import project_root, slua_symbols


def load_rules(path: Path | None = None) -> dict[str, str]:
    file = path or project_root() / "languages" / "slua" / "lint.toml"
    if not file.is_file():
        return {}
    data = tomllib.loads(file.read_text(encoding="utf-8"))
    return {name: str(body.get("severity", "warning")) for name, body in data.get("rules", {}).items()}


def lint(result: ParseResult, rules: dict[str, str] | None = None) -> list[Diagnostic]:
    symbols = slua_symbols()
    configured = load_rules() if rules is None else rules
    found: list[Diagnostic] = []
    modules = symbols["modules"]
    builtins = {item["name"]: item for item in symbols.get("builtins", [])}
    removed = set(symbols.get("removed_constants") or [])
    events = symbols.get("events") or {}

    def report(code: str, fallback: str, message: str, node: Node) -> None:
        severity = configured.get(code, fallback)
        if severity != "off":
            found.append(Diagnostic(code, severity, message, node.span))

    def visit(node: Node) -> None:
        if node.kind == "call_expression":
            _call(node, modules, builtins, report)
        elif node.kind == "method_call":
            _method(node, events, report)
        elif node.kind == "identifier" and node.get("name") in removed:
            report("removed-constant", "warning", f"{node.get('name')} is not a SLua constant", node)
        for value in node.props.values():
            _walk(value, visit)

    visit(result.tree)
    return found


def _walk(value, visit) -> None:
    if isinstance(value, Node):
        visit(value)
    elif isinstance(value, list):
        for item in value:
            _walk(item, visit)
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, visit)


def _call(node: Node, modules: dict, builtins: dict, report) -> None:
    callee = node.get("callee")
    args = node.get("args") or []
    if callee is None:
        return
    if callee.kind == "member_expression" and callee.get("object").kind == "identifier":
        module = callee.get("object").get("name")
        field = callee.get("field")
        info = (modules.get(module) or {}).get("functions", {}).get(field)
        if module in modules and info is None:
            report("unknown-function", "warning", f"unknown {module}.{field}", node)
            return
        if info:
            _function_info(f"{module}.{field}", info, args, node, report)
        return
    if callee.kind == "identifier":
        info = builtins.get(callee.get("name"))
        if info:
            _function_info(callee.get("name"), info, args, node, report)


def _function_info(label: str, info: dict, args: list[Node], node: Node, report) -> None:
    if info.get("removed"):
        report("removed-function", "warning", f"{label} is not available in SLua", node)
        return
    deprecated = info.get("deprecated")
    if deprecated:
        extra = f" Use {deprecated['use']}." if deprecated.get("use") else ""
        reason = f" {deprecated['reason']}" if deprecated.get("reason") else ""
        report("deprecated-function", "warning", f"{label} is deprecated.{reason}{extra}", node)
    signatures = [info.get("params") or []]
    signatures.extend(info.get("overloads") or [])
    if not any(_accepts(signature, len(args)) for signature in signatures):
        report("arity", "error", f"{label} takes {_arity_text(signatures)}, not {len(args)}", node)


def _accepts(params: list[dict], nargs: int) -> bool:
    required = 0
    fixed = 0
    variadic = False
    optional_started = False
    for param in params:
        name = param.get("name") or ""
        typ = str(param.get("type") or "")
        if name == "self":
            continue
        if param.get("variadic") or name == "..." or typ.startswith("..."):
            variadic = True
            continue
        fixed += 1
        if optional_started or param.get("optional"):
            optional_started = True
            continue
        required += 1
    if nargs < required:
        return False
    if variadic:
        return True
    return nargs <= fixed


def _arity_text(signatures: list[list[dict]]) -> str:
    counts = []
    for signature in signatures:
        required = 0
        fixed = 0
        variadic = False
        optional_started = False
        for param in signature:
            name = param.get("name") or ""
            typ = str(param.get("type") or "")
            if name == "self":
                continue
            if param.get("variadic") or name == "..." or typ.startswith("..."):
                variadic = True
                continue
            fixed += 1
            if optional_started or param.get("optional"):
                optional_started = True
            else:
                required += 1
        if variadic:
            counts.append(f"at least {required}")
        elif required != fixed:
            counts.append(f"{required} to {fixed}")
        else:
            counts.append(str(required))
    return " or ".join(counts) + " argument(s)"


def _method(node: Node, events: dict, report) -> None:
    obj = node.get("object")
    if obj is None or obj.kind != "identifier" or obj.get("name") != "LLEvents":
        return
    if node.get("method") not in {"on", "off", "once"}:
        return
    args = node.get("args") or []
    if not args or args[0].kind != "string":
        return
    raw = args[0].get("raw") or ""
    if raw[:1] in {"'", '"', "`"}:
        name = raw[1:-1]
    else:
        name = raw
    info = events.get(name)
    if info is None:
        report("unknown-event", "warning", f"unknown event {name}", args[0])
        return
    if info.get("slua_removed"):
        report("unknown-event", "warning", f"{name} is not an SLua event", args[0])
