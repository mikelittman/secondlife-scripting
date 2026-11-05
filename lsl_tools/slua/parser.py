"""Recursive-descent parser for SLua (Luau syntax).

Type annotations are preserved as source text so the formatter can print them
without inventing a second type pretty-printer. Library checks live in the linter.
"""

from __future__ import annotations

from lsl_tools.model import Diagnostic, Node, ParseResult, Span, Token
from lsl_tools.slua.lexer import Lexer

COMPOUND = {"+=", "-=", "*=", "/=", "%=", "^=", "//=", "..="}
LEVELS = [
    (1, "left", {"or"}),
    (2, "left", {"and"}),
    (3, "left", {"<", ">", "<=", ">=", "==", "~="}),
    (4, "left", {"|"}),
    (5, "left", {"~"}),
    (6, "left", {"&"}),
    (7, "left", {"<<", ">>"}),
    (8, "right", {".."}),
    (9, "left", {"+", "-"}),
    (10, "left", {"*", "/", "//", "%"}),
]
BLOCK_END = {"end", "else", "elseif", "until", "eof"}


def parse(source: str) -> ParseResult:
    parser = Parser(Lexer(source).tokenize(), source)
    tree = parser.parse_chunk()
    return ParseResult("slua", tree, parser.errors, parser.tokens, source)


class Parser:
    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.i = 0
        self.pending: list[Token] = []
        self._held: list[Token] = []
        self.errors: list[Diagnostic] = []
        self.last = tokens[0].span if tokens else Span(1, 1, 1, 1, 0, 0)
        self._skip()

    def parse_chunk(self) -> Node:
        start = self._span()
        body = self._block({"eof"})
        end = self._span()
        node = self._node("chunk", start, end, body=body)
        node.trailing = [token.text for token in self.pending]
        self.pending = []
        return node

    def _block(self, terminators: set[str]) -> list[Node]:
        body = []
        while not self._is(*terminators):
            mark = self.i
            statement = self._statement()
            if statement is not None:
                body.append(statement)
            if self.i == mark:
                self._error("unexpected token")
                self._advance()
        return body

    def _statement(self) -> Node | None:
        leading = self._leading()
        self._eat_if(";")
        if self._is(*BLOCK_END):
            self.pending = self._held + self.pending
            return None
        start = self._peek()
        attributes = self._attributes()
        if self._is("local"):
            node = self._local()
        elif self._is("function"):
            node = self._function_statement()
        elif self._is("if"):
            node = self._if_statement()
        elif self._is("while"):
            node = self._while()
        elif self._is("repeat"):
            node = self._repeat()
        elif self._is("for"):
            node = self._for()
        elif self._is("do"):
            node = self._do()
        elif self._is("return"):
            node = self._return()
        elif self._is("break", "continue"):
            token = self._advance()
            node = self._node(f"{token.text}_statement", token.span, token.span)
        elif self._is("export") or (self._is("type") and self._ahead_kind() == "identifier"):
            node = self._type_alias()
        elif self._starts_expression():
            node = self._assignment_or_call()
        else:
            self._error(f"unexpected {start.text!r}")
            self._advance()
            node = self._error_node(start.span, "unexpected token")
        self._eat_if(";")
        if attributes:
            node.props["attributes"] = attributes
        return self._attach(node, leading)

    def _local(self) -> Node:
        start = self._advance()
        if self._is("function"):
            self._advance()
            name = self._expect_kind("identifier")
            generic = self._generic_params()
            params, return_type, body, end = self._function_body()
            return self._node(
                "local_function",
                start.span,
                end,
                name=name.text,
                generic=generic,
                params=params,
                return_type=return_type,
                body=body,
            )
        names = self._name_list()
        values: list[Node] = []
        if self._eat_if("="):
            values = self._expr_list()
        return self._node("local_declaration", start.span, self.last, names=names, values=values)

    def _function_statement(self) -> Node:
        start = self._advance()
        name, method = self._function_name()
        generic = self._generic_params()
        params, return_type, body, end = self._function_body()
        return self._node(
            "function_declaration",
            start.span,
            end,
            name=name,
            method=method,
            generic=generic,
            params=params,
            return_type=return_type,
            body=body,
        )

    def _function_name(self) -> tuple[list[str], str]:
        parts = [self._expect_kind("identifier").text]
        while self._eat_if("."):
            parts.append(self._expect_kind("identifier").text)
        method = ""
        if self._eat_if(":"):
            method = self._expect_kind("identifier").text
        return parts, method

    def _function_body(self) -> tuple[list[dict], str, list[Node], Span]:
        self._expect("(")
        params = self._params()
        self._expect(")")
        return_type = self._consume_type() if self._eat_if(":") else ""
        body = self._block({"end", "eof"})
        end = self._expect("end")
        return params, return_type, body, end.span

    def _if_statement(self) -> Node:
        start = self._advance()
        clauses = []
        while True:
            condition = self._parse_expression()
            self._expect("then")
            body = self._block({"elseif", "else", "end", "eof"})
            clauses.append({"condition": condition, "body": body})
            if not self._eat_if("elseif"):
                break
        else_body = None
        if self._eat_if("else"):
            else_body = self._block({"end", "eof"})
        end = self._expect("end")
        return self._node("if_statement", start.span, end.span, clauses=clauses, else_body=else_body)

    def _while(self) -> Node:
        start = self._advance()
        condition = self._parse_expression()
        self._expect("do")
        body = self._block({"end", "eof"})
        end = self._expect("end")
        return self._node("while_statement", start.span, end.span, condition=condition, body=body)

    def _repeat(self) -> Node:
        start = self._advance()
        body = self._block({"until", "eof"})
        self._expect("until")
        condition = self._parse_expression()
        return self._node("repeat_statement", start.span, condition.span, body=body, condition=condition)

    def _for(self) -> Node:
        start = self._advance()
        name = self._expect_kind("identifier")
        if self._eat_if("="):
            first = self._parse_expression()
            self._expect(",")
            limit = self._parse_expression()
            step = self._parse_expression() if self._eat_if(",") else None
            self._expect("do")
            body = self._block({"end", "eof"})
            end = self._expect("end")
            return self._node(
                "for_numeric",
                start.span,
                end.span,
                name=name.text,
                init=first,
                limit=limit,
                step=step,
                body=body,
            )
        names = [name.text]
        while self._eat_if(","):
            names.append(self._expect_kind("identifier").text)
        self._expect("in")
        iterators = self._expr_list()
        self._expect("do")
        body = self._block({"end", "eof"})
        end = self._expect("end")
        return self._node("for_generic", start.span, end.span, names=names, iterators=iterators, body=body)

    def _do(self) -> Node:
        start = self._advance()
        body = self._block({"end", "eof"})
        end = self._expect("end")
        return self._node("do_statement", start.span, end.span, body=body)

    def _return(self) -> Node:
        start = self._advance()
        values = [] if self._is(";", *BLOCK_END) else self._expr_list()
        end = values[-1].span if values else start.span
        return self._node("return_statement", start.span, end, values=values)

    def _type_alias(self) -> Node:
        exported = self._eat_if("export")
        start = self._peek()
        self._expect("type")
        name = self._expect_kind("identifier")
        self._expect("=")
        raw = self._consume_type()
        return self._node("type_alias", start.span, self.last, name=name.text, exported=exported, type_raw=raw)

    def _assignment_or_call(self) -> Node:
        first = self._suffix()
        if self._text() in COMPOUND:
            op = self._advance()
            value = self._parse_expression()
            return self._node("update_statement", first.span, value.span, target=first, op=op.text, value=value)
        if self._is(",") or self._is("="):
            targets = [first]
            while self._eat_if(","):
                targets.append(self._suffix())
            self._expect("=")
            values = self._expr_list()
            end = values[-1].span if values else targets[-1].span
            return self._node("assignment", targets[0].span, end, targets=targets, values=values)
        if first.kind in {"call_expression", "method_call"}:
            return first
        self._error("expected a call or assignment")
        return first

    def _expr_list(self) -> list[Node]:
        items = [self._parse_expression()]
        while self._eat_if(","):
            if self._is(";", *BLOCK_END, ")"):
                break
            items.append(self._parse_expression())
        return items

    def _parse_expression(self, min_prec: int = 1) -> Node:
        left = self._unary()
        while True:
            op = self._text()
            level = next((item for item in LEVELS if op in item[2] and item[0] >= min_prec), None)
            if level is None:
                break
            prec, assoc, _ = level
            self._advance()
            right = self._parse_expression(prec if assoc == "right" else prec + 1)
            left = self._node("binary_expression", left.span, right.span, op=op, left=left, right=right)
        return left

    def _unary(self) -> Node:
        if self._text() in {"-", "#", "~"} or self._is("not"):
            op = self._advance()
            # '^' binds tighter than unary, and unary is right-associative: -a^b is -(a^b).
            operand = self._unary()
            return self._node("unary_expression", op.span, operand.span, op=op.text, operand=operand)
        return self._power()

    def _power(self) -> Node:
        left = self._suffix()
        if self._text() == "^":
            self._advance()
            right = self._unary()
            return self._node("binary_expression", left.span, right.span, op="^", left=left, right=right)
        return left

    def _suffix(self) -> Node:
        node = self._primary()
        while True:
            if self._eat_if("."):
                field = self._expect_kind("identifier")
                node = self._node("member_expression", node.span, field.span, object=node, field=field.text)
            elif self._is("["):
                self._advance()
                index = self._parse_expression()
                close = self._expect("]")
                node = self._node("index_expression", node.span, close.span, object=node, index=index)
            elif self._eat_if(":"):
                method = self._expect_kind("identifier")
                args, end = self._args()
                node = self._node("method_call", node.span, end, object=node, method=method.text, args=args)
            elif self._is("(") or self._peek().kind == "string" or self._is("{"):
                args, end = self._args()
                node = self._node("call_expression", node.span, end, callee=node, args=args)
            elif self._eat_if("::"):
                raw = self._consume_type()
                node = self._node("type_assertion", node.span, self.last, operand=node, type_raw=raw)
            else:
                break
        return node

    def _primary(self) -> Node:
        token = self._peek()
        if token.kind == "number":
            self._advance()
            return self._node("number", token.span, token.span, raw=token.text)
        if token.kind == "string":
            self._advance()
            return self._node("string", token.span, token.span, raw=token.text)
        if self._is("nil", "true", "false"):
            self._advance()
            return self._node("literal", token.span, token.span, raw=token.text)
        if self._text() == "...":
            self._advance()
            return self._node("vararg", token.span, token.span)
        if self._is("identifier"):
            self._advance()
            return self._node("identifier", token.span, token.span, name=token.text)
        if self._is("("):
            self._advance()
            expr = self._parse_expression()
            close = self._expect(")")
            return self._node("parenthesized_expression", token.span, close.span, operand=expr)
        if self._is("{"):
            return self._table()
        if self._is("function"):
            return self._function_expression()
        if self._is("if"):
            return self._if_expression()
        self._error(f"expected an expression, found {token.text!r}")
        if token.kind != "eof":
            self._advance()
        return self._error_node(token.span, "expected an expression")

    def _args(self) -> tuple[list[Node], Span]:
        if self._is("("):
            self._advance()
            args = [] if self._is(")") else self._expr_list()
            close = self._expect(")")
            return args, close.span
        if self._peek().kind == "string":
            token = self._advance()
            return [self._node("string", token.span, token.span, raw=token.text)], token.span
        if self._is("{"):
            table = self._table()
            return [table], table.span
        self._error("expected arguments")
        return [], self._span()

    def _table(self) -> Node:
        open_tok = self._advance()
        fields = []
        while not self._is("}", "eof"):
            if self._is("["):
                self._advance()
                key = self._parse_expression()
                self._expect("]")
                self._expect("=")
                value = self._parse_expression()
                fields.append({"kind": "index", "key": key, "value": value})
            elif self._is("identifier") and self._ahead_text(1) == "=":
                name = self._advance()
                self._expect("=")
                value = self._parse_expression()
                fields.append({"kind": "name", "name": name.text, "value": value})
            else:
                fields.append({"kind": "value", "value": self._parse_expression()})
            if not self._eat_if(","):
                self._eat_if(";")
                break
        close = self._expect("}")
        return self._node("table", open_tok.span, close.span, fields=fields)

    def _function_expression(self) -> Node:
        start = self._advance()
        generic = self._generic_params()
        params, return_type, body, end = self._function_body()
        return self._node(
            "function_expression",
            start.span,
            end,
            generic=generic,
            params=params,
            return_type=return_type,
            body=body,
        )

    def _if_expression(self) -> Node:
        start = self._advance()
        clauses = []
        while True:
            condition = self._parse_expression()
            self._expect("then")
            value = self._parse_expression()
            clauses.append({"condition": condition, "value": value})
            if not self._eat_if("elseif"):
                break
        self._expect("else")
        else_value = self._parse_expression()
        return self._node("if_expression", start.span, else_value.span, clauses=clauses, else_value=else_value)

    def _name_list(self) -> list[dict]:
        names = [self._annotated_name()]
        while self._eat_if(","):
            names.append(self._annotated_name())
        return names

    def _annotated_name(self) -> dict:
        name = self._expect_kind("identifier")
        type_raw = self._consume_type() if self._eat_if(":") else ""
        return {"name": name.text, "type_raw": type_raw}

    def _params(self) -> list[dict]:
        params = []
        if self._is(")"):
            return params
        while True:
            if self._text() == "...":
                self._advance()
                type_raw = self._consume_type() if self._eat_if(":") else ""
                params.append({"name": "...", "type_raw": type_raw})
                break
            params.append(self._annotated_name())
            if not self._eat_if(","):
                break
        return params

    def _generic_params(self) -> str:
        if self._text() != "<":
            return ""
        checkpoint = self._checkpoint()
        start = self._peek().span.start_offset
        self._advance()
        if not self._is("identifier"):
            self._restore(checkpoint)
            return ""
        while self._is("identifier"):
            self._advance()
            self._eat_if("...")
            if not self._eat_if(","):
                break
        if not self._eat_if(">"):
            self._restore(checkpoint)
            return ""
        if not self._is("("):
            self._restore(checkpoint)
            return ""
        return self.source[start : self.last.end_offset].strip()

    def _attributes(self) -> list[str]:
        names = []
        while self._text() == "@":
            self._advance()
            names.append(self._expect_kind("identifier").text)
            if self._is("("):
                self._skip_balanced("(", ")")
        return names

    def _consume_type(self) -> str:
        start = self._peek().span.start_offset
        self._type_union()
        return self.source[start : self.last.end_offset].strip()

    def _type_union(self) -> None:
        self._type_intersection()
        while self._text() == "|":
            self._advance()
            self._type_intersection()

    def _type_intersection(self) -> None:
        self._type_prefix()
        while self._text() == "&":
            self._advance()
            self._type_prefix()

    def _type_prefix(self) -> None:
        self._type_primary()
        if self._text() == "?":
            self._advance()

    def _type_primary(self) -> None:
        if self._is("("):
            self._advance()
            if not self._is(")"):
                while True:
                    if self._is("identifier") and self._ahead_text(1) == ":":
                        self._advance()
                        self._advance()
                    self._type_union()
                    if self._text() == "...":
                        self._advance()
                    if not self._eat_if(","):
                        break
            self._expect(")")
            if self._text() == "->":
                self._advance()
                self._type_union()
            return
        if self._is("{"):
            self._skip_balanced("{", "}")
            return
        if self._is("typeof"):
            self._advance()
            self._expect("(")
            self._parse_expression()
            self._expect(")")
            return
        if self._text() == "...":
            self._advance()
            self._type_primary()
            return
        if self._peek().kind in {"identifier", "keyword", "string"}:
            self._advance()
            if self._text() == "<":
                self._advance()
                if not self._is(">"):
                    while True:
                        self._type_union()
                        if self._text() == "...":
                            self._advance()
                        if not self._eat_if(","):
                            break
                self._expect(">")
            return
        self._error("expected a type")

    def _skip_balanced(self, open_text: str, close_text: str) -> None:
        self._expect(open_text)
        depth = 1
        while not self._is("eof") and depth:
            if self._text() == open_text:
                depth += 1
            elif self._text() == close_text:
                depth -= 1
            if depth:
                self._advance()
        self._expect(close_text)

    def _starts_expression(self) -> bool:
        if self._peek().kind in {"identifier", "number", "string"}:
            return True
        return self._is("nil", "true", "false", "function", "if", "not", "(", "{") or self._text() in {"-", "#", "~", "..."}

    def _node(self, kind: str, start: Span, end: Span, **props) -> Node:
        node = Node(kind, Span.merge(start, end), props=props)
        if kind.endswith("expression") or kind in {
            "identifier",
            "number",
            "string",
            "literal",
            "vararg",
            "table",
            "member_expression",
            "index_expression",
            "method_call",
            "type_assertion",
        }:
            self.pending = [
                comment
                for comment in self.pending
                if not (
                    comment.span.start_offset >= node.span.start_offset
                    and comment.span.end_offset <= node.span.end_offset
                )
            ]
        return node

    def _error_node(self, span: Span, message: str) -> Node:
        return Node("error", span, props={"message": message})

    def _error(self, message: str) -> None:
        self.errors.append(Diagnostic("syntax", "error", message, self._span()))

    def _checkpoint(self) -> tuple:
        return self.i, len(self.errors), list(self.pending), self.last

    def _restore(self, checkpoint: tuple) -> None:
        self.i, count, self.pending, self.last = checkpoint
        del self.errors[count:]

    def _span(self) -> Span:
        return self._peek().span

    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _text(self) -> str:
        return self._peek().text

    def _is(self, *options: str) -> bool:
        token = self._peek()
        return token.kind in options or token.text in options

    def _ahead_kind(self) -> str:
        index = self.i + 1
        while index < len(self.tokens) and self.tokens[index].kind == "comment":
            index += 1
        return self.tokens[index].kind if index < len(self.tokens) else "eof"

    def _ahead_text(self, count: int) -> str:
        index = self.i
        seen = 0
        while index < len(self.tokens):
            if self.tokens[index].kind == "comment":
                index += 1
                continue
            if seen == count:
                return self.tokens[index].text
            seen += 1
            index += 1
        return ""

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind != "eof":
            self.last = token.span
            self.i += 1
            self._skip()
        return token

    def _skip(self) -> None:
        while self.i < len(self.tokens) and self.tokens[self.i].kind == "comment":
            self.pending.append(self.tokens[self.i])
            self.i += 1

    def _eat_if(self, text: str) -> bool:
        if self._text() == text:
            self._advance()
            return True
        return False

    def _expect(self, text: str) -> Token:
        if self._text() == text:
            return self._advance()
        self._error(f"expected {text!r}")
        return self._peek()

    def _expect_kind(self, kind: str) -> Token:
        if self._peek().kind == kind:
            return self._advance()
        self._error(f"expected {kind}")
        return self._peek()

    def _leading(self) -> list[str]:
        self._held = self.pending
        comments = [token.text for token in self.pending]
        self.pending = []
        return comments

    def _attach(self, node: Node, leading: list[str]) -> Node:
        trailing = []
        rest = []
        for comment in self.pending:
            inside = comment.span.start_offset >= node.span.start_offset and comment.span.end_offset <= node.span.end_offset
            if inside:
                continue
            if comment.span.start_line == node.span.end_line:
                trailing.append(comment.text)
            else:
                rest.append(comment)
        self.pending = rest
        node.leading = leading
        node.trailing = trailing
        return node
