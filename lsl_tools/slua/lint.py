"""SLua lint rules. Severities live in languages/slua/lint.toml."""

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
    events = set(symbols.get("events") or {})

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
    deprecated = info.get("deprecated")
    if deprecated:
        extra = f" Use {deprecated['use']}." if deprecated.get("use") else ""
        reason = f" {deprecated['reason']}" if deprecated.get("reason") else ""
        report("deprecated-function", "warning", f"{label} is deprecated.{reason}{extra}", node)
    params = info.get("params") or []
    if any(param.get("name") == "..." or "..." in str(param.get("type", "")) for param in params):
        return
    if params and len(args) != len(params):
        report("arity", "error", f"{label} takes {len(params)} argument(s), not {len(args)}", node)


def _method(node: Node, events: set[str], report) -> None:
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
    if name not in events:
        report("unknown-event", "warning", f"unknown event {name}", args[0])
