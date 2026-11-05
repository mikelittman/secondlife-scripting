"""Recursive-descent parser for LSL.

The grammar follows Tailslide's lslmini.y: globals, then one or more states,
C-like statements, and vector/rotation/list literals. Editor use also accepts
a file that does not yet have a default state.
"""

from __future__ import annotations

from lsl_tools.model import Diagnostic, Node, ParseResult, Span, Token
from lsl_tools.lsl.lexer import TYPES, Lexer

ASSIGN = {"=", "+=", "-=", "*=", "/=", "%="}
# Lowest precedence first. && and || share a level, matching Tailslide.
LEVELS = [
    (1, "right", ASSIGN),
    (2, "left", {"&&", "||"}),
    (3, "left", {"|"}),
    (4, "left", {"^"}),
    (5, "left", {"&"}),
    (6, "left", {"==", "!="}),
    (7, "left", {"<", "<=", ">", ">="}),
    (8, "left", {"<<", ">>"}),
    (9, "left", {"+", "-"}),
    (10, "left", {"*", "/", "%"}),
]
PREFIX_UNARY = {"-", "!", "~", "++", "--"}


def parse(source: str) -> ParseResult:
    tokens = Lexer(source).tokenize()
    parser = Parser(tokens, source)
    tree = parser.parse_script()
    return ParseResult("lsl", tree, parser.errors, tokens, source)


class Parser:
    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.i = 0
        self.pending: list[Token] = []
        self.errors: list[Diagnostic] = []
        self._skip()

    def parse_script(self) -> Node:
        start = self._span()
        globals_: list[Node] = []
        states: list[Node] = []
        while not self._is("eof"):
            if self._is("default") or (self._is("state") and self._ahead_is("identifier", "default")):
                break
            item = self._parse_global()
            if item is None:
                break
            globals_.append(item)
        while self._is("default") or self._is("state"):
            states.append(self._parse_state())
        if not self._is("eof"):
            self._error("expected a global or a state")
            while not self._is("eof"):
                self._advance()
        end = self._peek().span
        node = self._node("script", start, end, globals=globals_, states=states)
        node.trailing = [token.text for token in self.pending]
        self.pending = []
        return node

    def _parse_global(self) -> Node | None:
        leading = self._leading()
        if self._is("type"):
            type_tok = self._advance()
            if not self._is("identifier"):
                self._error("expected a name")
                self._sync()
                return self._attach(self._error_node(type_tok.span, "expected a name"), leading)
            name = self._advance()
            if self._is("("):
                params = self._parse_params()
                body = self._parse_compound()
                node = self._node(
                    "function_definition",
                    type_tok.span,
                    body.span,
                    type_name=type_tok.text,
                    name=name.text,
                    params=params,
                    body=body,
                )
                return self._attach(node, leading)
            init = None
            if self._eat_if("="):
                init = self._parse_expression()
            semi = self._expect(";")
            node = self._node(
                "global_variable",
                type_tok.span,
                semi.span,
                type_name=type_tok.text,
                name=name.text,
                init=init,
            )
            return self._attach(node, leading)
        if self._is("identifier") and self._ahead_is("("):
            name = self._advance()
            params = self._parse_params()
            body = self._parse_compound()
            node = self._node(
                "function_definition",
                name.span,
                body.span,
                type_name="",
                name=name.text,
                params=params,
                body=body,
            )
            return self._attach(node, leading)
        if self._is("eof", "default", "state"):
            return None
        self._error("expected a global variable, function, or state")
        start = self._span()
        self._sync()
        return self._attach(self._error_node(start, "expected a global"), leading)

    def _parse_state(self) -> Node:
        leading = self._leading()
        if self._is("default"):
            name = self._advance()
        else:
            self._expect("state")
            if self._is("identifier", "default"):
                name = self._advance()
            else:
                self._error("expected a state name")
                name = self._peek()
        self._expect("{")
        events = []
        while not self._is("}", "eof"):
            events.append(self._parse_event())
        close = self._expect("}")
        node = self._node("state_definition", name.span, close.span, name=name.text, events=events)
        return self._attach(node, leading)

    def _parse_event(self) -> Node:
        leading = self._leading()
        if not self._is("identifier"):
            self._error("expected an event handler")
            start = self._span()
            self._sync()
            return self._attach(self._error_node(start, "expected an event"), leading)
        name = self._advance()
        params = self._parse_params() if self._is("(") else []
        if not self._is("{"):
            self._error("expected an event body")
        body = self._parse_compound()
        node = self._node("event_handler", name.span, body.span, name=name.text, params=params, body=body)
        return self._attach(node, leading)

    def _parse_params(self) -> list[dict]:
        self._expect("(")
        params = []
        if not self._is(")"):
            while True:
                if not self._is("type"):
                    self._error("expected a parameter type")
                    break
                type_tok = self._advance()
                if not self._is("identifier"):
                    self._error("expected a parameter name")
                    break
                name = self._advance()
                params.append({"type": type_tok.text, "name": name.text})
                if not self._eat_if(","):
                    break
        self._expect(")")
        return params

    def _parse_compound(self) -> Node:
        leading = self._leading()
        open_tok = self._expect("{")
        statements = []
        while not self._is("}", "eof"):
            statement = self._parse_statement()
            if statement is None:
                break
            statements.append(statement)
        close = self._expect("}")
        node = self._node("compound", open_tok.span, close.span, statements=statements)
        return self._attach(node, leading)

    def _parse_statement(self) -> Node | None:
        leading = self._leading()
        if self._is("}", "eof"):
            self.pending = self._held + self.pending
            return None
        start = self._peek()
        if self._is(";"):
            tok = self._advance()
            return self._attach(self._node("empty_statement", tok.span, tok.span), leading)
        if self._is("{"):
            self.pending = self._held + self.pending
            return self._parse_compound()
        if self._is("if"):
            return self._attach(self._parse_if(), leading)
        if self._is("for"):
            return self._attach(self._parse_for(), leading)
        if self._is("do"):
            return self._attach(self._parse_do(), leading)
        if self._is("while"):
            return self._attach(self._parse_while(), leading)
        if self._is("jump"):
            self._advance()
            name = self._expect_kind("identifier")
            semi = self._expect(";")
            return self._attach(self._node("jump_statement", start.span, semi.span, name=name.text), leading)
        if self._is("@"):
            self._advance()
            name = self._expect_kind("identifier")
            semi = self._expect(";")
            return self._attach(self._node("label", start.span, semi.span, name=name.text), leading)
        if self._is("return"):
            self._advance()
            value = None if self._is(";") else self._parse_expression()
            semi = self._expect(";")
            return self._attach(self._node("return_statement", start.span, semi.span, value=value), leading)
        if self._is("state"):
            self._advance()
            if self._is("identifier", "default"):
                name = self._advance()
            else:
                self._error("expected a state name")
                name = self._peek()
            semi = self._expect(";")
            return self._attach(self._node("state_statement", start.span, semi.span, name=name.text), leading)
        if self._is("type"):
            type_tok = self._advance()
            name = self._expect_kind("identifier")
            init = self._parse_expression() if self._eat_if("=") else None
            semi = self._expect(";")
            node = self._node(
                "declaration",
                type_tok.span,
                semi.span,
                type_name=type_tok.text,
                name=name.text,
                init=init,
            )
            return self._attach(node, leading)
        if self._starts_expression():
            expr = self._parse_expression()
            semi = self._expect(";")
            return self._attach(self._node("expression_statement", expr.span, semi.span, expression=expr), leading)
        self._error(f"unexpected {start.text!r}")
        self._sync()
        end = self._previous_span(start.span)
        return self._attach(self._error_node(Span.merge(start.span, end), "unexpected token"), leading)

    def _parse_if(self) -> Node:
        start = self._advance()
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        consequence = self._parse_statement() or self._error_node(condition.span, "expected a statement")
        alternative = None
        end = consequence.span
        if self._is("else"):
            self._advance()
            alternative = self._parse_statement() or self._error_node(end, "expected a statement")
            end = alternative.span
        return self._node(
            "if_statement",
            start.span,
            end,
            condition=condition,
            consequence=consequence,
            alternative=alternative,
        )

    def _parse_while(self) -> Node:
        start = self._advance()
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        body = self._parse_statement() or self._error_node(condition.span, "expected a statement")
        return self._node("while_statement", start.span, body.span, condition=condition, body=body)

    def _parse_do(self) -> Node:
        start = self._advance()
        body = self._parse_statement() or self._error_node(start.span, "expected a statement")
        self._expect("while")
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        semi = self._expect(";")
        return self._node("do_statement", start.span, semi.span, body=body, condition=condition)

    def _parse_for(self) -> Node:
        start = self._advance()
        self._expect("(")
        init = [] if self._is(";") else self._parse_expr_list()
        self._expect(";")
        if self._is(";"):
            self._error("for loop requires a condition")
            condition = self._error_node(self._span(), "missing condition")
        else:
            condition = self._parse_expression()
        self._expect(";")
        step = [] if self._is(")") else self._parse_expr_list()
        self._expect(")")
        body = self._parse_statement() or self._error_node(condition.span, "expected a statement")
        return self._node("for_statement", start.span, body.span, init=init, condition=condition, step=step, body=body)

    def _parse_expr_list(self) -> list[Node]:
        items = [self._parse_expression()]
        while self._eat_if(","):
            items.append(self._parse_expression())
        return items

    def _parse_expression(self, min_prec: int = 1, terminators: frozenset[str] = frozenset()) -> Node:
        left = self._parse_unary()
        while True:
            op = self._text() if self._peek().kind == "operator" else ""
            if op in terminators:
                break
            level = next((item for item in LEVELS if op in item[2] and item[0] >= min_prec), None)
            if level is None:
                break
            prec, assoc, _ = level
            if op in ASSIGN and not self._is_lvalue(left):
                self._error("assignment target must be a variable or a field")
            self._advance()
            next_min = prec if assoc == "right" else prec + 1
            right = self._parse_expression(next_min, terminators)
            left = self._node("binary_expression", left.span, right.span, op=op, left=left, right=right)
        return left

    def _parse_unary(self) -> Node:
        if self._text() in PREFIX_UNARY and self._peek().kind == "operator":
            op = self._advance()
            operand = self._parse_unary()
            if op.text in {"++", "--"} and not self._is_lvalue(operand):
                self._error(f"{op.text} requires a variable")
            kind = "update_expression" if op.text in {"++", "--"} else "unary_expression"
            return self._node(kind, op.span, operand.span, op=op.text, operand=operand, prefix=True)
        if self._is("(") and self._ahead_is("type") and self._ahead_text(2) == ")":
            open_tok = self._advance()
            type_tok = self._advance()
            self._expect(")")
            operand = self._parse_unary()
            return self._node("cast_expression", open_tok.span, operand.span, type_name=type_tok.text, operand=operand)
        return self._parse_postfix()

    def _parse_postfix(self) -> Node:
        node = self._parse_primary()
        if self._text() in {"++", "--"} and self._peek().kind == "operator":
            if not self._is_lvalue(node):
                self._error(f"{self._text()} requires a variable")
            op = self._advance()
            return self._node("update_expression", node.span, op.span, op=op.text, operand=node, prefix=False)
        return node

    def _parse_primary(self) -> Node:
        tok = self._peek()
        if tok.kind == "number":
            self._advance()
            return self._node("number", tok.span, tok.span, raw=tok.text)
        if tok.kind == "string":
            self._advance()
            return self._node("string", tok.span, tok.span, raw=tok.text)
        if self._is("print"):
            self._advance()
            self._expect("(")
            operand = self._parse_expression()
            close = self._expect(")")
            return self._node("print_expression", tok.span, close.span, operand=operand)
        if self._is("<"):
            return self._parse_bracket_literal()
        if self._is("["):
            open_tok = self._advance()
            items = [] if self._is("]") else self._parse_expr_list()
            close = self._expect("]")
            return self._node("list_literal", open_tok.span, close.span, items=items)
        if self._is("("):
            open_tok = self._advance()
            expr = self._parse_expression()
            close = self._expect(")")
            return self._node("parenthesized_expression", open_tok.span, close.span, operand=expr)
        if self._is("identifier"):
            name = self._advance()
            if self._is("("):
                self._advance()
                args = [] if self._is(")") else self._parse_expr_list()
                close = self._expect(")")
                return self._node("call_expression", name.span, close.span, name=name.text, args=args)
            if self._is("."):
                self._advance()
                field = self._expect_kind("identifier")
                return self._node("member_expression", name.span, field.span, object=name.text, field=field.text)
            return self._node("identifier", name.span, name.span, name=name.text)
        self._error(f"expected an expression, found {tok.text!r}")
        if tok.kind != "eof":
            self._advance()
        return self._error_node(tok.span, "expected an expression")

    def _parse_bracket_literal(self) -> Node:
        # '>' closes the literal, so a comparison inside a component needs parentheses.
        open_tok = self._advance()
        stop = frozenset({">"})
        first = self._parse_expression(terminators=stop)
        self._expect(",")
        second = self._parse_expression(terminators=stop)
        self._expect(",")
        third = self._parse_expression(terminators=stop)
        if self._eat_if(","):
            fourth = self._parse_expression(terminators=stop)
            close = self._expect(">")
            return self._node(
                "quaternion_literal",
                open_tok.span,
                close.span,
                x=first,
                y=second,
                z=third,
                s=fourth,
            )
        close = self._expect(">")
        return self._node("vector_literal", open_tok.span, close.span, x=first, y=second, z=third)

    def _starts_expression(self) -> bool:
        if self._peek().kind in {"identifier", "number", "string"}:
            return True
        return self._text() in {"(", "<", "[", "!", "~", "-", "++", "--"} or self._is("print")

    def _is_lvalue(self, node: Node) -> bool:
        return node.kind in {"identifier", "member_expression"}

    def _node(self, kind: str, start: Span, end: Span, **props) -> Node:
        node = Node(kind, Span.merge(start, end), props=props)
        if kind.endswith("expression") or kind.endswith("literal") or kind in {"identifier", "number", "string"}:
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
        span = self._span()
        self.errors.append(Diagnostic("syntax", "error", message, span))

    def _span(self) -> Span:
        return self._peek().span

    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _text(self) -> str:
        return self._peek().text

    def _is(self, *options: str) -> bool:
        token = self._peek()
        return token.kind in options or token.text in options or ("type" in options and token.kind == "type")

    def _ahead_is(self, *options: str) -> bool:
        index = self.i + 1
        while index < len(self.tokens) and self.tokens[index].kind == "comment":
            index += 1
        if index >= len(self.tokens):
            return False
        token = self.tokens[index]
        return token.kind in options or token.text in options

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

    def _sync(self) -> None:
        guard = self.i
        while not self._is(";", "}", "eof", "default"):
            self._advance()
            if self.i == guard:
                self._advance()
                break
            guard = self.i
        if self._is(";"):
            self._advance()

    def _leading(self) -> list[str]:
        self._held = self.pending
        comments = [token.text for token in self.pending]
        self.pending = []
        return comments

    def _attach(self, node: Node, leading: list[str]) -> Node:
        trailing: list[str] = []
        rest: list[Token] = []
        for comment in self.pending:
            inside = (
                comment.span.start_offset >= node.span.start_offset
                and comment.span.end_offset <= node.span.end_offset
            )
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


# Imported so pack metadata and highlighters can share the type list.
__all__ = ["TYPES", "parse", "Parser"]
