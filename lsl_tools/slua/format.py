"""SLua formatter. Indent and spacing come from languages/slua/format.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from lsl_tools.model import Node, ParseResult
from lsl_tools.symbols import project_root


@dataclass
class Style:
    indent_width: int = 4
    use_tabs: bool = False

    @property
    def unit(self) -> str:
        return "\t" if self.use_tabs else " " * self.indent_width


def load_style(path: Path | None = None) -> Style:
    file = path or project_root() / "languages" / "slua" / "format.toml"
    data = tomllib.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
    return Style(indent_width=int(data.get("indent_width", 4)), use_tabs=bool(data.get("use_tabs", False)))


def format_source(result: ParseResult, style: Style | None = None) -> str:
    if result.errors:
        return result.source
    printer = Printer(result, style or load_style())
    return printer.print_chunk(result.tree)


class Printer:
    def __init__(self, result: ParseResult, style: Style):
        self.source = result.source
        self.tokens = result.tokens
        self.style = style
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.indent = 0
        self.at_start = True

    def print_chunk(self, node: Node) -> str:
        for statement in node.get("body", []):
            self._statement(statement)
            self.newline()
        for comment in node.trailing:
            self._comment(comment, trailing=False)
        text = "\n".join(self.lines)
        if self.buf:
            text = (text + "\n" if text else "") + "".join(self.buf).rstrip()
        if text and not text.endswith("\n"):
            text += "\n"
        return text

    def _statement(self, node: Node) -> None:
        self._leading(node)
        for attribute in node.get("attributes") or []:
            self.write("@" + attribute)
            self.newline()
        kind = node.kind
        if kind == "local_declaration":
            self.write("local ")
            self._names(node.get("names", []))
            if node.get("values"):
                self.write(" = ")
                self._exprs(node.get("values"))
        elif kind == "local_function":
            self.write("local function " + node.get("name"))
            self._signature(node)
        elif kind == "function_declaration":
            self.write("function " + ".".join(node.get("name") or []))
            if node.get("method"):
                self.write(":" + node.get("method"))
            self._signature(node)
        elif kind == "if_statement":
            self._if_statement(node)
        elif kind == "while_statement":
            self.write("while ")
            self._expr(node.get("condition"))
            self.write(" do")
            self.newline()
            self._body(node.get("body", []))
            self.write("end")
        elif kind == "repeat_statement":
            self.write("repeat")
            self.newline()
            self._body(node.get("body", []))
            self.write("until ")
            self._expr(node.get("condition"))
        elif kind == "for_numeric":
            self.write(f"for {node.get('name')} = ")
            self._expr(node.get("init"))
            self.write(", ")
            self._expr(node.get("limit"))
            if node.get("step") is not None:
                self.write(", ")
                self._expr(node.get("step"))
            self.write(" do")
            self.newline()
            self._body(node.get("body", []))
            self.write("end")
        elif kind == "for_generic":
            self.write("for " + ", ".join(node.get("names", [])) + " in ")
            self._exprs(node.get("iterators", []))
            self.write(" do")
            self.newline()
            self._body(node.get("body", []))
            self.write("end")
        elif kind == "do_statement":
            self.write("do")
            self.newline()
            self._body(node.get("body", []))
            self.write("end")
        elif kind == "return_statement":
            self.write("return")
            if node.get("values"):
                self.write(" ")
                self._exprs(node.get("values"))
        elif kind in {"break_statement", "continue_statement"}:
            self.write(kind.split("_", 1)[0])
        elif kind == "type_alias":
            if node.get("exported"):
                self.write("export ")
            self.write(f"type {node.get('name')} = {node.get('type_raw')}")
        elif kind == "assignment":
            self._exprs(node.get("targets", []))
            self.write(" = ")
            self._exprs(node.get("values", []))
        elif kind == "update_statement":
            self._expr(node.get("target"))
            self.write(" " + node.get("op") + " ")
            self._expr(node.get("value"))
        elif kind in {"call_expression", "method_call"}:
            self._expr(node)
        elif kind == "error":
            self.write(self.source[node.span.start_offset : node.span.end_offset])
        self._trailing(node)

    def _signature(self, node: Node) -> None:
        if node.get("generic"):
            self.write(node.get("generic"))
        self.write("(" + self._params(node.get("params", [])) + ")")
        if node.get("return_type"):
            self.write(": " + node.get("return_type"))
        self.newline()
        self._body(node.get("body", []))
        self.write("end")

    def _if_statement(self, node: Node) -> None:
        for index, clause in enumerate(node.get("clauses", [])):
            self.write("if " if index == 0 else "elseif ")
            self._expr(clause["condition"])
            self.write(" then")
            self.newline()
            self._body(clause["body"])
        else_body = node.get("else_body")
        if else_body is not None:
            self.write("else")
            self.newline()
            self._body(else_body)
        self.write("end")

    def _body(self, statements: list[Node]) -> None:
        self.indent += 1
        if not statements:
            self.newline()
        for statement in statements:
            self._statement(statement)
            self.newline()
        self.indent -= 1

    def _names(self, names: list[dict]) -> None:
        parts = []
        for item in names:
            text = item["name"]
            if item.get("type_raw"):
                text += ": " + item["type_raw"]
            parts.append(text)
        self.write(", ".join(parts))

    def _params(self, params: list[dict]) -> str:
        parts = []
        for param in params:
            text = param["name"]
            if param.get("type_raw"):
                text += ": " + param["type_raw"]
            parts.append(text)
        return ", ".join(parts)

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
        if kind in {"number", "string", "literal"}:
            self.write(node.get("raw"))
        elif kind == "vararg":
            self.write("...")
        elif kind == "identifier":
            self.write(node.get("name"))
        elif kind == "member_expression":
            self._expr(node.get("object"))
            self.write("." + node.get("field"))
        elif kind == "index_expression":
            self._expr(node.get("object"))
            self.write("[")
            self._expr(node.get("index"))
            self.write("]")
        elif kind == "call_expression":
            self._expr(node.get("callee"))
            self.write("(")
            self._exprs(node.get("args", []))
            self.write(")")
        elif kind == "method_call":
            self._expr(node.get("object"))
            self.write(":" + node.get("method") + "(")
            self._exprs(node.get("args", []))
            self.write(")")
        elif kind == "parenthesized_expression":
            self.write("(")
            self._expr(node.get("operand"))
            self.write(")")
        elif kind == "unary_expression":
            op = node.get("op")
            self.write(op + (" " if op == "not" else ""))
            self._expr(node.get("operand"))
        elif kind == "binary_expression":
            self._expr(node.get("left"))
            self.write(" " + node.get("op") + " ")
            self._expr(node.get("right"))
        elif kind == "type_assertion":
            self._expr(node.get("operand"))
            self.write(" :: " + node.get("type_raw"))
        elif kind == "table":
            self._table(node)
        elif kind == "function_expression":
            self.write("function")
            self._signature(node)
        elif kind == "if_expression":
            self._if_expression(node)
        elif kind == "error":
            self.write(self.source[node.span.start_offset : node.span.end_offset])

    def _table(self, node: Node) -> None:
        fields = node.get("fields", [])
        inline = node.span.start_line == node.span.end_line
        if inline:
            self.write("{")
            self._fields(fields, multiline=False)
            self.write("}" if not fields else " }")
            return
        self.write("{")
        self.newline()
        self.indent += 1
        self._fields(fields, multiline=True)
        self.indent -= 1
        self.write("}")

    def _fields(self, fields: list[dict], multiline: bool) -> None:
        for index, field in enumerate(fields):
            if multiline:
                if index:
                    self.write(",")
                    self.newline()
            elif index:
                self.write(", ")
            if field["kind"] == "name":
                self.write(field["name"] + " = ")
                self._expr(field["value"])
            elif field["kind"] == "index":
                self.write("[")
                self._expr(field["key"])
                self.write("] = ")
                self._expr(field["value"])
            else:
                self._expr(field["value"])
        if multiline and fields:
            self.write(",")
            self.newline()

    def _if_expression(self, node: Node) -> None:
        inline = node.span.start_line == node.span.end_line
        for index, clause in enumerate(node.get("clauses", [])):
            self.write("if " if index == 0 else " elseif ")
            self._expr(clause["condition"])
            self.write(" then ")
            self._expr(clause["value"])
            if not inline:
                self.newline()
        self.write(" else " if inline else "else ")
        self._expr(node.get("else_value"))

    def _comment_inside(self, node: Node) -> bool:
        start, end = node.span.start_offset, node.span.end_offset
        return any(
            token.kind == "comment" and start <= token.span.start_offset and token.span.end_offset <= end
            for token in self.tokens
        )

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
