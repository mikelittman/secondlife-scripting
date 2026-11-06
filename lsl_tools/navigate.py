"""Go to definition, references, and occurrence highlights.

Tree-sitter highlights the buffer. Cmd-click uses the language server, which
resolves names in the parser tree. LSL locals live from their declaration to
the end of the enclosing function or event. A for-loop counter lives for that
loop only. Functions, globals, states, and labels are visible throughout the
script. SLua locals live from their declaration to the end of the block.
"""

from __future__ import annotations

from dataclasses import dataclass

from lsl_tools.model import Node, ParseResult, Span, Token

ASSIGN = {"=", "+=", "-=", "*=", "/=", "%=", "^=", "//=", "..="}
READ = 1
WRITE = 2


@dataclass(frozen=True)
class Binding:
    name: str
    kind: str
    name_span: Span
    container_span: Span
    scope_span: Span


def definition(result: ParseResult, line: int, character: int) -> tuple[Span, Binding] | None:
    token = token_at(result.tokens, line, character)
    if token is None:
        return None
    binding = _resolve(result, token)
    if binding is None:
        return None
    return token.span, binding


def references(result: ParseResult, line: int, character: int, include_declaration: bool = True) -> list[Span]:
    token = token_at(result.tokens, line, character)
    if token is None:
        return []
    binding = _resolve(result, token)
    if binding is None:
        return []
    spans = []
    for item in _navigable_tokens(result.tokens):
        if _same(_resolve(result, item), binding):
            if not include_declaration and _same_place(item.span, binding.name_span):
                continue
            spans.append(item.span)
    if include_declaration and not any(_same_place(span, binding.name_span) for span in spans):
        spans.insert(0, binding.name_span)
    return spans


def highlights(result: ParseResult, line: int, character: int) -> list[tuple[Span, int]]:
    token = token_at(result.tokens, line, character)
    if token is None:
        return []
    binding = _resolve(result, token)
    if binding is None:
        return []
    found = []
    for item in _navigable_tokens(result.tokens):
        if _same(_resolve(result, item), binding):
            kind = WRITE if _is_write(result.tokens, item, binding) else READ
            found.append((item.span, kind))
    if not any(_same_place(span, binding.name_span) for span, _kind in found):
        found.insert(0, (binding.name_span, WRITE if binding.kind in {"variable", "parameter"} else READ))
    return found


def token_at(tokens: list[Token], line: int, character: int) -> Token | None:
    row = line + 1
    column = character + 1
    inside = [
        token
        for token in _navigable_tokens(tokens)
        if token.span.start_line == row and token.span.start_col <= column < token.span.end_col
    ]
    if inside:
        return inside[0]
    edges = [
        token
        for token in _navigable_tokens(tokens)
        if token.span.start_line == row and token.span.end_col == column
    ]
    return edges[-1] if edges else None


def _resolve(result: ParseResult, token: Token) -> Binding | None:
    context = _context(result.tokens, token)
    if context == "field":
        return None
    bindings = _bindings(result)
    candidates = [
        binding
        for binding in bindings
        if binding.name == token.text
        and _contains(binding.scope_span, token.span)
        and _kind_matches(binding, context, result.language)
    ]
    return _pick(candidates, token)


def _bindings(result: ParseResult) -> list[Binding]:
    if result.language == "slua":
        return _slua_bindings(result)
    return _lsl_bindings(result)


def _lsl_bindings(result: ParseResult) -> list[Binding]:
    bindings: list[Binding] = []
    tokens = result.tokens
    file_span = _file_span(result)
    for item in result.tree.get("globals", []):
        if item.kind == "function_definition":
            _add_function(bindings, item, tokens, file_span)
            _add_lsl_params(bindings, item, tokens)
            _walk_lsl(item.get("body"), item.span, bindings, tokens)
        elif item.kind == "global_variable":
            name = _first_identifier(tokens, item.span)
            if name is not None:
                bindings.append(Binding(name.text, "variable", name.span, item.span, file_span))
    for state in result.tree.get("states", []):
        name = _state_token(tokens, state)
        if name is not None:
            bindings.append(Binding(state.get("name") or name.text, "state", name.span, state.span, file_span))
        for event in state.get("events", []):
            _add_lsl_params(bindings, event, tokens)
            _walk_lsl(event.get("body"), event.span, bindings, tokens)
    return bindings


def _walk_lsl(node: Node | None, owner: Span, bindings: list[Binding], tokens: list[Token]) -> None:
    if node is None:
        return
    if node.kind == "declaration":
        name = _first_identifier(tokens, node.span)
        if name is not None:
            bindings.append(Binding(name.text, "variable", name.span, node.span, _from(name.span, owner)))
        return
    if node.kind == "label":
        name = _first_identifier(tokens, node.span)
        if name is not None:
            bindings.append(Binding(name.text, "label", name.span, node.span, owner))
        return
    if node.kind == "for_statement":
        declaration = node.get("declaration")
        if declaration is not None:
            name = _first_identifier(tokens, declaration.span)
            if name is not None:
                bindings.append(Binding(name.text, "variable", name.span, declaration.span, _from(name.span, node.span)))
        _walk_lsl(node.get("body"), owner, bindings, tokens)
        return
    if node.kind == "compound":
        for statement in node.get("statements", []):
            _walk_lsl(statement, owner, bindings, tokens)
        return
    if node.kind == "if_statement":
        _walk_lsl(node.get("consequence"), owner, bindings, tokens)
        _walk_lsl(node.get("alternative"), owner, bindings, tokens)
        return
    if node.kind in {"while_statement", "do_statement"}:
        _walk_lsl(node.get("body"), owner, bindings, tokens)


def _add_function(bindings: list[Binding], node: Node, tokens: list[Token], file_span: Span) -> None:
    body = node.get("body")
    if body is None:
        return
    signature = _between(tokens, node.span.start_offset, body.span.start_offset)
    names = [token for token in signature if token.kind == "identifier"]
    if not names:
        return
    name = names[0]
    bindings.append(Binding(name.text, "function", name.span, node.span, file_span))


def _add_lsl_params(bindings: list[Binding], node: Node, tokens: list[Token]) -> None:
    body = node.get("body")
    if body is None:
        return
    signature = _between(tokens, node.span.start_offset, body.span.start_offset)
    seen_paren = False
    previous: Token | None = None
    for token in signature:
        if token.text == "(":
            seen_paren = True
            previous = token
            continue
        if seen_paren and token.kind == "identifier" and previous is not None and previous.kind == "type":
            bindings.append(Binding(token.text, "parameter", token.span, token.span, _from(token.span, node.span)))
        previous = token


def _slua_bindings(result: ParseResult) -> list[Binding]:
    bindings: list[Binding] = []
    _walk_slua(result.tree, result.tree.span, result.tokens, bindings, result.tree.span)
    return bindings


def _walk_slua(node: Node, block_end: Span, tokens: list[Token], bindings: list[Binding], chunk: Span) -> None:
    kind = node.kind
    if kind == "local_declaration":
        for name in _matching_identifiers(tokens, node.span.start_offset, _value_start(node), _names(node.get("names", []))):
            bindings.append(Binding(name.text, "variable", name.span, node.span, _from(name.span, block_end)))
    elif kind == "local_function":
        name = _named_identifier(tokens, node.span.start_offset, _paren_offset(tokens, node), node.get("name") or "")
        if name is not None:
            bindings.append(Binding(name.text, "variable", name.span, node.span, _from(name.span, block_end)))
        _add_slua_params(bindings, node, tokens)
    elif kind == "function_declaration":
        parts = node.get("name") or []
        if len(parts) == 1 and not node.get("method"):
            name = _named_identifier(tokens, node.span.start_offset, _paren_offset(tokens, node), parts[0])
            if name is not None:
                bindings.append(Binding(name.text, "variable", name.span, node.span, chunk))
        _add_slua_params(bindings, node, tokens)
    elif kind == "function_expression":
        _add_slua_params(bindings, node, tokens)
    elif kind == "for_numeric":
        name = _named_identifier(tokens, node.span.start_offset, node.span.end_offset, node.get("name") or "")
        if name is not None:
            bindings.append(Binding(name.text, "variable", name.span, node.span, _from(name.span, node.span)))
    elif kind == "for_generic":
        stop = _keyword_offset(tokens, node, "in")
        for name in _matching_identifiers(tokens, node.span.start_offset, stop, node.get("names", [])):
            bindings.append(Binding(name.text, "variable", name.span, node.span, _from(name.span, node.span)))
    if kind == "if_statement":
        for clause in node.get("clauses", []):
            body = clause.get("body", [])
            _walk_slua_list(body, _list_end(body, block_end), tokens, bindings, chunk)
        else_body = node.get("else_body") or []
        _walk_slua_list(else_body, _list_end(else_body, block_end), tokens, bindings, chunk)
        return
    inner_end = node.span if kind in {
        "chunk",
        "local_function",
        "function_declaration",
        "function_expression",
        "for_numeric",
        "for_generic",
        "while_statement",
        "repeat_statement",
        "do_statement",
    } else block_end
    for child in _child_nodes(node):
        _walk_slua(child, inner_end, tokens, bindings, chunk)


def _walk_slua_list(statements: list[Node], block_end: Span, tokens: list[Token], bindings: list[Binding], chunk: Span) -> None:
    for statement in statements:
        _walk_slua(statement, block_end, tokens, bindings, chunk)


def _child_nodes(node: Node):
    for value in node.props.values():
        if isinstance(value, Node):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Node):
                    yield item
                elif isinstance(item, dict):
                    for nested in item.values():
                        if isinstance(nested, Node):
                            yield nested
                        elif isinstance(nested, list):
                            for child in nested:
                                if isinstance(child, Node):
                                    yield child


def _add_slua_params(bindings: list[Binding], node: Node, tokens: list[Token]) -> None:
    open_offset = _paren_offset(tokens, node)
    close_offset = _keyword_offset(tokens, node, ")")
    if open_offset is None or close_offset is None:
        return
    for name in _matching_identifiers(tokens, open_offset, close_offset, _names(node.get("params", []))):
        bindings.append(Binding(name.text, "parameter", name.span, name.span, _from(name.span, node.span)))


def _names(items: list) -> list[str]:
    found = []
    for item in items:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict) and item.get("name") and item.get("name") != "...":
            found.append(item["name"])
    return found


def _kind_matches(binding: Binding, context: str, language: str) -> bool:
    if context == "call":
        # LSL calls name a function. SLua calls name a variable that holds one.
        if language == "lsl":
            return binding.kind == "function"
        return binding.kind in {"variable", "parameter"}
    if context == "label":
        return binding.kind == "label"
    if context == "state":
        return binding.kind == "state"
    return binding.kind in {"variable", "parameter"}


def _context(tokens: list[Token], token: Token) -> str:
    previous = _neighbor(tokens, token, -1)
    following = _neighbor(tokens, token, 1)
    if previous is not None and previous.text in {".", ":"}:
        return "field"
    if previous is not None and previous.text == "jump":
        return "label"
    if previous is not None and previous.text == "@":
        return "label"
    if token.text == "default" or (previous is not None and previous.text == "state"):
        return "state"
    if following is not None and following.text == "(":
        return "call"
    return "value"


def _pick(candidates: list[Binding], token: Token) -> Binding | None:
    if not candidates:
        return None
    smallest = min(_length(binding.scope_span) for binding in candidates)
    group = [binding for binding in candidates if _length(binding.scope_span) == smallest]
    earlier = [binding for binding in group if binding.name_span.start_offset <= token.span.start_offset]
    if earlier:
        earlier.sort(key=lambda binding: binding.name_span.start_offset, reverse=True)
        return earlier[0]
    group.sort(key=lambda binding: binding.name_span.start_offset)
    return group[0]


def _is_write(tokens: list[Token], token: Token, binding: Binding) -> bool:
    if binding.kind in {"variable", "parameter"} and _same_place(token.span, binding.name_span):
        return True
    previous = _neighbor(tokens, token, -1)
    following = _neighbor(tokens, token, 1)
    if following is not None and following.text in ASSIGN:
        return True
    if following is not None and following.text in {"++", "--"}:
        return True
    return previous is not None and previous.text in {"++", "--"}


def _navigable_tokens(tokens: list[Token]) -> list[Token]:
    return [token for token in tokens if token.kind == "identifier" or token.text == "default"]


def _neighbor(tokens: list[Token], token: Token, step: int) -> Token | None:
    index = _index(tokens, token)
    if index is None:
        return None
    index += step
    while 0 <= index < len(tokens) and tokens[index].kind in {"comment", "eof"}:
        index += step
    if 0 <= index < len(tokens):
        return tokens[index]
    return None


def _index(tokens: list[Token], token: Token) -> int | None:
    for index, item in enumerate(tokens):
        if item is token or _same_place(item.span, token.span) and item.text == token.text:
            return index
    return None


def _first_identifier(tokens: list[Token], span: Span) -> Token | None:
    for token in _between(tokens, span.start_offset, span.end_offset):
        if token.kind == "identifier":
            return token
    return None


def _state_token(tokens: list[Token], node: Node) -> Token | None:
    for token in _between(tokens, node.span.start_offset, node.span.end_offset):
        if token.text == node.get("name") and token.kind in {"identifier", "keyword"}:
            return token
    return None


def _matching_identifiers(tokens: list[Token], start: int, end: int | None, names: list[str]) -> list[Token]:
    if end is None:
        return []
    found = []
    pending = list(names)
    for token in _between(tokens, start, end):
        if token.kind == "identifier" and pending and token.text == pending[0]:
            found.append(token)
            pending.pop(0)
    return found


def _named_identifier(tokens: list[Token], start: int, end: int | None, name: str) -> Token | None:
    matches = _matching_identifiers(tokens, start, end, [name] if name else [])
    return matches[0] if matches else None


def _paren_offset(tokens: list[Token], node: Node) -> int | None:
    for token in _between(tokens, node.span.start_offset, node.span.end_offset):
        if token.text == "(":
            return token.span.end_offset
    return None


def _keyword_offset(tokens: list[Token], node: Node, text: str) -> int | None:
    for token in _between(tokens, node.span.start_offset, node.span.end_offset):
        if token.text == text:
            return token.span.start_offset
    return None


def _value_start(node: Node) -> int:
    values = node.get("values") or []
    if values:
        return values[0].span.start_offset
    return node.span.end_offset


def _list_end(statements: list[Node], fallback: Span) -> Span:
    if not statements:
        return fallback
    return statements[-1].span


def _between(tokens: list[Token], start: int, end: int) -> list[Token]:
    return [
        token
        for token in tokens
        if token.kind != "eof" and start <= token.span.start_offset and token.span.end_offset <= end
    ]


def _file_span(result: ParseResult) -> Span:
    eof = result.tokens[-1].span if result.tokens else Span(1, 1, 1, 1, 0, 0)
    return Span(1, 1, eof.end_line, eof.end_col, 0, len(result.source))


def _from(name: Span, end: Span) -> Span:
    return Span(name.start_line, name.start_col, end.end_line, end.end_col, name.start_offset, end.end_offset)


def _contains(scope: Span, span: Span) -> bool:
    return scope.start_offset <= span.start_offset and span.end_offset <= scope.end_offset


def _length(span: Span) -> int:
    return span.end_offset - span.start_offset


def _same(left: Binding | None, right: Binding | None) -> bool:
    if left is None or right is None:
        return False
    return left.kind == right.kind and left.name == right.name and _same_place(left.name_span, right.name_span)


def _same_place(left: Span, right: Span) -> bool:
    return left.start_offset == right.start_offset and left.end_offset == right.end_offset
