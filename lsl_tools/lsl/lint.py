"""LSL lint rules.

Severities live in languages/lsl/lint.toml so an editor can turn a rule off
without changing the checkers.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lsl_tools.model import Diagnostic, Node, ParseResult
from lsl_tools.symbols import lsl_symbols, project_root


def load_rules(path: Path | None = None) -> dict[str, str]:
    file = path or project_root() / "languages" / "lsl" / "lint.toml"
    if not file.is_file():
        return {}
    data = tomllib.loads(file.read_text(encoding="utf-8"))
    return {name: str(body.get("severity", "warning")) for name, body in data.get("rules", {}).items()}


def lint(result: ParseResult, rules: dict[str, str] | None = None) -> list[Diagnostic]:
    symbols = lsl_symbols()
    configured = load_rules() if rules is None else rules
    found: list[Diagnostic] = []

    def report(code: str, fallback: str, message: str, node: Node) -> None:
        severity = configured.get(code, fallback)
        if severity == "off" or node is None:
            return
        found.append(Diagnostic(code, severity, message, node.span))

    def visit(node: Node) -> None:
        kind = node.kind
        if kind == "call_expression":
            _call(node, symbols, report)
        elif kind == "event_handler":
            _event(node, symbols, report)
        elif kind == "state_definition":
            if not node.get("events"):
                report("empty-state", "warning", f"state {node.get('name')} has no event handlers", node)
        elif kind in {"if_statement", "while_statement", "do_statement", "for_statement"}:
            condition = node.get("condition")
            if condition is not None and condition.kind == "binary_expression" and condition.get("op") == "=":
                report("assignment-in-condition", "warning", "assignment used as a condition", condition)
        elif kind == "identifier":
            _constant(node, symbols, report)
        for value in node.props.values():
            if isinstance(value, Node):
                visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        visit(item)

    visit(result.tree)
    states = result.tree.get("states", [])
    globals_ = result.tree.get("globals", [])
    has_default = any(state.get("name") == "default" for state in states)
    if (states or globals_) and not has_default:
        report("missing-default", "warning", "script has no default state", result.tree)
    return found


def _call(node: Node, symbols: dict, report) -> None:
    name = node.get("name") or ""
    functions = symbols["functions"]
    if name not in functions:
        if name.startswith("ll") and len(name) > 2 and name[2].isupper():
            report("unknown-function", "warning", f"unknown library function {name}", node)
        return
    info = functions[name]
    deprecated = info.get("deprecated")
    if deprecated:
        extra = f" Use {deprecated['use']}." if deprecated.get("use") else ""
        reason = f" {deprecated['reason']}" if deprecated.get("reason") else ""
        report("deprecated-function", "warning", f"{name} is deprecated.{reason}{extra}", node)
    expected = len(info.get("arguments") or [])
    actual = len(node.get("args") or [])
    if actual != expected:
        report("arity", "error", f"{name} takes {expected} argument(s), not {actual}", node)


def _event(node: Node, symbols: dict, report) -> None:
    name = node.get("name") or ""
    events = symbols["events"]
    if name not in events:
        report("unknown-event", "warning", f"unknown event {name}", node)
        return
    info = events[name]
    if info.get("deprecated"):
        report("deprecated-event", "warning", f"event {name} is deprecated", node)
    expected = len(info.get("arguments") or [])
    actual = len(node.get("params") or [])
    if actual != expected:
        report("event-arity", "error", f"event {name} takes {expected} parameter(s), not {actual}", node)


def _constant(node: Node, symbols: dict, report) -> None:
    name = node.get("name") or ""
    info = symbols["constants"].get(name)
    if not info or not info.get("deprecated"):
        return
    deprecated = info["deprecated"]
    extra = f" Use {deprecated['use']}." if deprecated.get("use") else ""
    report("deprecated-constant", "warning", f"{name} is deprecated.{extra}", node)
