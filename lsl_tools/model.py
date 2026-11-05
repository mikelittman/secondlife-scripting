"""Shared syntax tree, tokens, and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Span:
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    start_offset: int
    end_offset: int

    @staticmethod
    def merge(start: "Span", end: "Span") -> "Span":
        return Span(
            start.start_line,
            start.start_col,
            end.end_line,
            end.end_col,
            start.start_offset,
            end.end_offset,
        )

    def lsp(self) -> dict:
        return {
            "start": {"line": self.start_line - 1, "character": self.start_col - 1},
            "end": {"line": self.end_line - 1, "character": self.end_col - 1},
        }


@dataclass
class Token:
    kind: str
    text: str
    span: Span


@dataclass
class Node:
    kind: str
    span: Span
    leading: list[str] = field(default_factory=list)
    trailing: list[str] = field(default_factory=list)
    props: dict = field(default_factory=dict)

    def get(self, name: str, default=None):
        return self.props.get(name, default)

    def sexp(self) -> str:
        parts = [self.kind]
        for key, value in self.props.items():
            if isinstance(value, Node):
                parts.append(value.sexp())
            elif isinstance(value, list):
                if value and isinstance(value[0], Node):
                    parts.append("(" + " ".join(item.sexp() for item in value) + ")")
                elif value and isinstance(value[0], dict):
                    rendered = " ".join(
                        f"{item.get('type', '')}:{item.get('name', '')}".strip(":") for item in value
                    )
                    parts.append(f"[{rendered}]")
                elif not value:
                    parts.append("[]")
            elif key in {"name", "op", "type_name", "raw", "value"} and value not in (None, ""):
                parts.append(f"{key}:{value}")
        return "(" + " ".join(parts) + ")"


@dataclass
class Diagnostic:
    code: str
    severity: str
    message: str
    span: Span

    def lsp(self) -> dict:
        severity = {"error": 1, "warning": 2, "info": 3, "hint": 4}.get(self.severity, 2)
        return {
            "range": self.span.lsp(),
            "severity": severity,
            "code": self.code,
            "source": "lsl-tools",
            "message": self.message,
        }


@dataclass
class ParseResult:
    language: str
    tree: Node
    errors: list[Diagnostic]
    tokens: list[Token]
    source: str


def walk(node: Node):
    yield node
    for value in node.props.values():
        if isinstance(value, Node):
            yield from walk(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Node):
                    yield from walk(item)
