"""LSL formatter driven by languages/lsl/format.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from lsl_tools.model import Node, ParseResult
from lsl_tools.symbols import project_root

ASSIGN = {"=", "+=", "-=", "*=", "/=", "%="}


@dataclass
class Style:
    indent_width: int = 4
    use_tabs: bool = False
    brace_style: str = "same_line"
    blank_lines_between_items: int = 1

    @property
    def unit(self) -> str:
        return "\t" if self.use_tabs else " " * self.indent_width


def load_style(path: Path | None = None) -> Style:
    file = path or project_root() / "languages" / "lsl" / "format.toml"
    data = tomllib.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
    return Style(
        indent_width=int(data.get("indent_width", 4)),
        use_tabs=bool(data.get("use_tabs", False)),
        brace_style=str(data.get("brace_style", "same_line")),
        blank_lines_between_items=int(data.get("blank_lines_between_items", 1)),
    )


def format_source(result: ParseResult, style: Style | None = None) -> str:
    if result.errors:
        return result.source
    printer = Printer(result, style or load_style())
    return printer.print_script(result.tree)


class Printer:
    def __init__(self, result: ParseResult, style: Style):
        self.source = result.source
        self.tokens = result.tokens
        self.style = style
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.indent = 0
        self.at_start = True

    def print_script(self, node: Node) -> str:
        items = node.get("globals", []) + node.get("states", [])
        for index, item in enumerate(items):
            if index and self.style.blank_lines_between_items and not self._packed_globals(items[index - 1], item):
                self._blank(self.style.blank_lines_between_items)
            self._item(item)
            if item.kind == "state_definition":
                self.newline()
            elif not self.at_start:
                self.newline()
        for comment in node.trailing:
            self._comment(comment, trailing=False)
        text = "\n".join(self.lines)
        if self.buf:
            text = (text + "\n" if text else "") + "".join(self.buf).rstrip()
        if text and not text.endswith("\n"):
            text += "\n"
        return text

    def _packed_globals(self, previous: Node, item: Node) -> bool:
        return previous.kind == "global_variable" and item.kind == "global_variable"

    def _item(self, node: Node) -> None:
        self._leading(node)
        if node.kind == "global_variable":
            self._declaration(node.get("type_name"), node.get("name"), node.get("init"))
            self.write(";")
            self._trailing(node)
        elif node.kind == "function_definition":
            self._function(node)
            self._trailing(node)
        elif node.kind == "state_definition":
            self._state(node)
            self._trailing(node)
        elif node.kind == "error":
            self.write(self.source[node.span.start_offset : node.span.end_offset])

    def _function(self, node: Node) -> None:
        if node.get("type_name"):
            self.write(node.get("type_name") + " ")
        self.write(node.get("name"))
        self.write("(" + self._params(node.get("params", [])) + ")")
        self._compound(node.get("body"), attached=True)

    def _state(self, node: Node) -> None:
        if node.get("name") == "default":
            self.write("default")
        else:
            self.write("state " + node.get("name"))
        self._brace_open(attached=True)
        for index, event in enumerate(node.get("events", [])):
            if index:
                self.newline()
            self._event(event)
            self.newline()
        self._brace_close()

    def _event(self, node: Node) -> None:
        self._leading(node)
        self.write(node.get("name") + "(" + self._params(node.get("params", [])) + ")")
        self._compound(node.get("body"), attached=True)
        self._trailing(node)

    def _statement(self, node: Node) -> None:
        self._leading(node)
        kind = node.kind
        if kind == "empty_statement":
            self.write(";")
        elif kind == "compound":
            self._compound(node, attached=False)
        elif kind == "declaration":
            self._declaration(node.get("type_name"), node.get("name"), node.get("init"))
            self.write(";")
        elif kind == "expression_statement":
            self._expr(node.get("expression"))
            self.write(";")
        elif kind == "return_statement":
            self.write("return")
            if node.get("value") is not None:
                self.write(" ")
                self._expr(node.get("value"))
            self.write(";")
        elif kind == "jump_statement":
            self.write("jump " + node.get("name") + ";")
        elif kind == "label":
            self.write("@" + node.get("name") + ";")
        elif kind == "state_statement":
            self.write("state " + node.get("name") + ";")
        elif kind == "if_statement":
            self._if(node)
        elif kind == "while_statement":
            self.write("while (")
            self._expr(node.get("condition"))
            self.write(")")
            self._body(node.get("body"))
        elif kind == "do_statement":
            self.write("do")
            self._body(node.get("body"))
            if node.get("body").kind != "compound":
                self.newline()
            elif self.style.brace_style != "same_line":
                self.newline()
            else:
                self.write(" ")
            self.write("while (")
            self._expr(node.get("condition"))
            self.write(");")
        elif kind == "for_statement":
            self.write("for (")
            declaration = node.get("declaration")
            if declaration is not None:
                self._declaration(declaration.get("type_name"), declaration.get("name"), declaration.get("init"))
            else:
                self._exprs(node.get("init", []))
            self.write(";")
            condition = node.get("condition")
            if condition is not None and condition.kind != "error":
                self.write(" ")
                self._expr(condition)
            self.write(";")
            step = node.get("step", [])
            if step:
                self.write(" ")
                self._exprs(step)
            self.write(")")
            self._body(node.get("body"))
        elif kind == "error":
            self.write(self.source[node.span.start_offset : node.span.end_offset])
        self._trailing(node)

    def _if(self, node: Node) -> None:
        self.write("if (")
        self._expr(node.get("condition"))
        self.write(")")
        self._body(node.get("consequence"))
        alternative = node.get("alternative")
        if alternative is None:
            return
        same_line = self.style.brace_style == "same_line"
        if alternative.kind == "if_statement" and same_line:
            self.write(" else ")
            self._statement(alternative)
            return
        if node.get("consequence").kind == "compound" and same_line:
            self.write(" else")
        else:
            self.newline()
            self.write("else")
        self._body(alternative)

    def _body(self, node: Node) -> None:
        if node.kind == "compound":
            self._compound(node, attached=True)
            return
        self.newline()
        self.indent += 1
        self._statement(node)
        self.indent -= 1

    def _compound(self, node: Node, attached: bool) -> None:
        self._leading(node)
        self._brace_open(attached)
        for statement in node.get("statements", []):
            self._statement(statement)
            self.newline()
        self._brace_close()
        self._trailing(node)

    def _declaration(self, type_name: str, name: str, init: Node | None) -> None:
        self.write(f"{type_name} {name}")
        if init is not None:
            self.write(" = ")
            self._expr(init)

    def _params(self, params: list[dict]) -> str:
        return ", ".join(f"{param['type']} {param['name']}" for param in params)

    def _exprs(self, nodes: list[Node]) -> None:
        for index, node in enumerate(nodes):
            if index:
                self.write(", ")
            self._expr(node)

    def _expr(self, node: Node) -> None:
        if node is None:
            return
        if self._comment_inside(node):
            self.write(self.source[node.span.start_offset : node.span.end_offset])
            return
        kind = node.kind
        if kind in {"number", "string"}:
            self.write(node.get("raw"))
        elif kind == "identifier":
            self.write(node.get("name"))
        elif kind == "member_expression":
            self.write(node.get("object") + "." + node.get("field"))
        elif kind == "call_expression":
            self.write(node.get("name") + "(")
            self._exprs(node.get("args", []))
            self.write(")")
        elif kind == "print_expression":
            self.write("print(")
            self._expr(node.get("operand"))
            self.write(")")
        elif kind == "parenthesized_expression":
            self.write("(")
            self._expr(node.get("operand"))
            self.write(")")
        elif kind == "vector_literal":
            self.write("<")
            self._exprs([node.get("x"), node.get("y"), node.get("z")])
            self.write(">")
        elif kind == "quaternion_literal":
            self.write("<")
            self._exprs([node.get("x"), node.get("y"), node.get("z"), node.get("s")])
            self.write(">")
        elif kind == "list_literal":
            self.write("[")
            self._exprs(node.get("items", []))
            self.write("]")
        elif kind == "unary_expression":
            self.write(node.get("op"))
            self._expr(node.get("operand"))
        elif kind == "update_expression":
            if node.get("prefix"):
                self.write(node.get("op"))
                self._expr(node.get("operand"))
            else:
                self._expr(node.get("operand"))
                self.write(node.get("op"))
        elif kind == "cast_expression":
            self.write("(" + node.get("type_name") + ")")
            self._expr(node.get("operand"))
        elif kind == "binary_expression":
            self._expr(node.get("left"))
            self.write(" " + node.get("op") + " ")
            self._expr(node.get("right"))
        elif kind == "error":
            self.write(self.source[node.span.start_offset : node.span.end_offset])

    def _comment_inside(self, node: Node) -> bool:
        start, end = node.span.start_offset, node.span.end_offset
        return any(
            token.kind == "comment" and token.span.start_offset >= start and token.span.end_offset <= end
            for token in self.tokens
        )

    def _brace_open(self, attached: bool) -> None:
        if attached and self.style.brace_style == "same_line":
            self.write(" {")
        else:
            self.newline()
            self.write("{")
        self.newline()
        self.indent += 1

    def _brace_close(self) -> None:
        self.indent -= 1
        self.write("}")

    def _leading(self, node: Node) -> None:
        for comment in node.leading:
            self._comment(comment, trailing=False)

    def _trailing(self, node: Node) -> None:
        for comment in node.trailing:
            self._comment(comment, trailing=True)

    def _comment(self, text: str, trailing: bool) -> None:
        lines = text.split("\n")
        if trailing:
            self.write(" " + lines[0])
            for line in lines[1:]:
                self.newline()
                self.write(line)
            return
        for index, line in enumerate(lines):
            if index:
                self.newline()
            self.write(line)
        self.newline()

    def _blank(self, count: int) -> None:
        for _ in range(count):
            self.newline()

    def newline(self) -> None:
        self.lines.append("".join(self.buf).rstrip())
        self.buf = []
        self.at_start = True

    def write(self, text: str) -> None:
        if not text:
            return
        if self.at_start:
            self.buf.append(self.style.unit * self.indent)
            self.at_start = False
        self.buf.append(text)
