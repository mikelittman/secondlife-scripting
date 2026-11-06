"""A small language server shared by every editor adapter.

Gram, Helix, Neovim, and VS Code can all talk to `lsl-tools lsp`. Highlighting
stays in the tree-sitter queries. This server adds diagnostics, formatting,
hover, symbols, and semantic tokens.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

from lsl_tools.model import Diagnostic, Node, ParseResult, Span, Token
from lsl_tools.navigate import definition as find_definition
from lsl_tools.navigate import highlights as find_highlights
from lsl_tools.navigate import references as find_references
from lsl_tools.registry import Language, language_for_id
from lsl_tools.symbols import lsl_symbols, slua_symbols

TOKEN_TYPES = [
    "comment",
    "string",
    "number",
    "keyword",
    "type",
    "function",
    "method",
    "variable",
    "parameter",
    "property",
    "event",
]
TOKEN_INDEX = {name: index for index, name in enumerate(TOKEN_TYPES)}


@dataclass
class Server:
    documents: dict[str, dict] = field(default_factory=dict)
    notify: object | None = None

    def handle(self, message: dict) -> dict | None:
        method = message.get("method", "")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            return _result(request_id, _capabilities())
        if method == "initialized":
            return None
        if method == "shutdown":
            return _result(request_id, None)
        if method == "exit":
            raise SystemExit(0)
        if method in {"textDocument/didOpen", "textDocument/didChange"}:
            self._sync(params, method)
            self._publish(params)
            return None
        if method == "textDocument/didClose":
            uri = params.get("textDocument", {}).get("uri")
            self.documents.pop(uri, None)
            return None
        if method == "textDocument/formatting":
            edits, error = self._format(params)
            if error:
                return _error(request_id, -32603, error)
            return _result(request_id, edits)
        if method == "textDocument/hover":
            return _result(request_id, self._hover(params))
        if method == "textDocument/definition":
            return _result(request_id, self._definition(params))
        if method == "textDocument/references":
            return _result(request_id, self._references(params))
        if method == "textDocument/documentHighlight":
            return _result(request_id, self._highlights(params))
        if method == "textDocument/documentSymbol":
            return _result(request_id, self._symbols(params))
        if method == "textDocument/semanticTokens/full":
            return _result(request_id, {"data": self._semantic_tokens(params)})
        if request_id is not None:
            return _error(request_id, -32601, f"method not found: {method}")
        return None

    def _sync(self, params: dict, method: str) -> None:
        document = params["textDocument"]
        uri = document["uri"]
        if method == "textDocument/didOpen":
            text = document.get("text", "")
            language_id = document.get("languageId", "")
        else:
            text = params["contentChanges"][0]["text"]
            language_id = self.documents.get(uri, {}).get("languageId", "")
        language = language_for_id(language_id)
        parsed = None
        failure = ""
        if language is not None:
            try:
                parsed = language.parse(text)
            except Exception as exc:
                failure = f"parser failed: {exc}"
        self.documents[uri] = {
            "text": text,
            "languageId": language_id,
            "language": language,
            "parsed": parsed,
            "failure": failure,
        }

    def _publish(self, params: dict) -> None:
        uri = params["textDocument"]["uri"]
        record = self.documents.get(uri)
        if not record:
            return
        if record.get("failure"):
            span = Span(1, 1, 1, 1, 0, 0)
            diagnostics = [Diagnostic("parser", "error", record["failure"], span)]
        elif record["parsed"] is None:
            return
        else:
            diagnostics = list(record["parsed"].errors)
            diagnostics.extend(record["language"].lint(record["parsed"]))
        (self.notify or _notify)(
            "textDocument/publishDiagnostics",
            {"uri": uri, "diagnostics": [item.lsp() for item in diagnostics]},
        )

    def _format(self, params: dict) -> tuple[list[dict], str]:
        record = self._record(params)
        if record is None or record["language"] is None:
            return [], "document is not open"
        if record.get("failure"):
            return [], record["failure"]
        if record["parsed"] is None:
            return [], "document is not open"
        if record["parsed"].errors:
            first = record["parsed"].errors[0]
            return [], (
                f"not formatted, source has syntax errors: "
                f"{first.span.start_line}:{first.span.start_col}: {first.message}"
            )
        formatted = record["language"].format(record["parsed"])
        lines = record["text"].split("\n")
        end_line = max(len(lines) - 1, 0)
        end_char = len(lines[-1]) if lines else 0
        return [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": end_line, "character": end_char},
                },
                "newText": formatted,
            }
        ], ""

    def _definition(self, params: dict) -> list[dict]:
        record = self._record(params)
        if record is None or record.get("parsed") is None:
            return []
        position = params.get("position") or {}
        found = find_definition(record["parsed"], position.get("line", 0), position.get("character", 0))
        if found is None:
            return []
        origin, binding = found
        uri = params["textDocument"]["uri"]
        return [
            {
                "originSelectionRange": origin.lsp(),
                "targetUri": uri,
                "targetRange": binding.container_span.lsp(),
                "targetSelectionRange": binding.name_span.lsp(),
            }
        ]

    def _references(self, params: dict) -> list[dict]:
        record = self._record(params)
        if record is None or record.get("parsed") is None:
            return []
        position = params.get("position") or {}
        include = params.get("context", {}).get("includeDeclaration", True)
        uri = params["textDocument"]["uri"]
        return [
            {"uri": uri, "range": span.lsp()}
            for span in find_references(
                record["parsed"], position.get("line", 0), position.get("character", 0), include
            )
        ]

    def _highlights(self, params: dict) -> list[dict]:
        record = self._record(params)
        if record is None or record.get("parsed") is None:
            return []
        position = params.get("position") or {}
        return [
            {"range": span.lsp(), "kind": kind}
            for span, kind in find_highlights(record["parsed"], position.get("line", 0), position.get("character", 0))
        ]

    def _hover(self, params: dict) -> dict | None:
        record = self._record(params)
        if record is None or record["parsed"] is None:
            return None
        token = _token_at(record["parsed"].tokens, params["position"])
        if token is None:
            return None
        text = _hover_text(record["language"], record["parsed"].tokens, token)
        if not text:
            return None
        return {"contents": {"kind": "markdown", "value": text}, "range": token.span.lsp()}

    def _symbols(self, params: dict) -> list[dict]:
        record = self._record(params)
        if record is None or record["parsed"] is None:
            return []
        symbols = []
        _collect_symbols(record["parsed"].tree, symbols)
        return symbols

    def _semantic_tokens(self, params: dict) -> list[int]:
        record = self._record(params)
        if record is None or record["parsed"] is None:
            return []
        encoded = []
        previous_line = 0
        previous_col = 0
        for line, col, length, kind in _semantic_pieces(record["parsed"]):
            if length <= 0 or kind not in TOKEN_INDEX:
                continue
            delta_line = line - previous_line
            delta_col = col - previous_col if delta_line == 0 else col
            encoded.extend([delta_line, delta_col, length, TOKEN_INDEX[kind], 0])
            previous_line = line
            previous_col = col
        return encoded

    def _record(self, params: dict) -> dict | None:
        return self.documents.get(params["textDocument"]["uri"])


def serve(stdin=None, stdout=None) -> None:
    reader = stdin or sys.stdin.buffer
    writer = stdout or sys.stdout.buffer
    server = Server()
    while True:
        message = _read(reader)
        if message is None:
            return
        try:
            response = server.handle(message)
        except SystemExit:
            return
        if response is not None:
            _write(writer, response)


def _capabilities() -> dict:
    return {
        "capabilities": {
            "textDocumentSync": 1,
            "documentFormattingProvider": True,
            "hoverProvider": True,
            "definitionProvider": True,
            "referencesProvider": True,
            "documentHighlightProvider": True,
            "documentSymbolProvider": True,
            "semanticTokensProvider": {
                "legend": {"tokenTypes": TOKEN_TYPES, "tokenModifiers": []},
                "full": True,
            },
        },
        "serverInfo": {"name": "lsl-tools", "version": "0.1.6"},
    }


def _hover_text(language: Language, tokens: list[Token], token: Token) -> str:
    if language.id == "lsl":
        return _lsl_hover(token)
    return _slua_hover(tokens, token)


def _lsl_hover(token: Token) -> str:
    if token.kind != "identifier":
        return ""
    symbols = lsl_symbols()
    if token.text in symbols["functions"]:
        return _signature("lsl", token.text, symbols["functions"][token.text])
    if token.text in symbols["events"]:
        info = symbols["events"][token.text]
        args = ", ".join(f"{arg['type']} {arg['name']}" for arg in info["arguments"])
        return f"event `{token.text}({args})`\n\n{info['tooltip']}"
    if token.text in symbols["constants"]:
        info = symbols["constants"][token.text]
        return f"`{token.text}` : {info['type']} = `{info['value']}`\n\n{info['tooltip']}"
    if token.text in symbols["types"]:
        return f"`{token.text}`\n\n{symbols['types'][token.text]}"
    return ""


def _slua_hover(tokens: list[Token], token: Token) -> str:
    symbols = slua_symbols()
    if token.kind != "identifier":
        return ""
    module = _module_before(tokens, token)
    if module and module in symbols["modules"]:
        info = symbols["modules"][module]["functions"].get(token.text)
        if info:
            return _signature("slua", f"{module}.{token.text}", info)
    for item in symbols.get("builtins", []):
        if item["name"] == token.text:
            return _signature("slua", token.text, item)
    for item in symbols.get("globals", []):
        if item["name"] == token.text:
            return f"`{token.text}`\n\n{item.get('tooltip', '')}"
    return ""


def _signature(kind: str, name: str, info: dict) -> str:
    if kind == "lsl":
        args = ", ".join(f"{arg['type']} {arg['name']}" for arg in info.get("arguments", []))
        header = f"`{info.get('return', 'void')} {name}({args})`"
    else:
        args = ", ".join(f"{arg.get('name', '')}: {arg.get('type', '')}".strip(": ") for arg in info.get("params", []))
        header = f"`function {name}({args})`"
    parts = [header]
    if info.get("tooltip"):
        parts.append(info["tooltip"])
    deprecated = info.get("deprecated") or info.get("slua_deprecated")
    if deprecated:
        replacement = f" Use {deprecated['use']}." if deprecated.get("use") else ""
        parts.append(f"Deprecated.{replacement}")
    return "\n\n".join(parts)


def _module_before(tokens: list[Token], token: Token) -> str:
    index = tokens.index(token)
    if index >= 2 and tokens[index - 1].text == "." and tokens[index - 2].kind == "identifier":
        return tokens[index - 2].text
    return ""


def _token_at(tokens: list[Token], position: dict) -> Token | None:
    line = position["line"] + 1
    column = position["character"] + 1
    for token in tokens:
        span = token.span
        if span.start_line == line and span.start_col <= column < max(span.end_col, span.start_col + 1):
            return token
    return None


def _collect_symbols(node: Node, symbols: list[dict]) -> None:
    kind = node.kind
    name = ""
    symbol_kind = 12
    if kind in {"function_definition", "local_function"}:
        name = node.get("name") or ""
    elif kind == "function_declaration":
        name = ".".join(node.get("name") or [])
        if node.get("method"):
            name += ":" + node.get("method")
    elif kind == "state_definition":
        name = node.get("name") or ""
        symbol_kind = 5
    elif kind == "event_handler":
        name = node.get("name") or ""
        symbol_kind = 24
    elif kind in {"global_variable", "local_declaration"}:
        if kind == "global_variable":
            name = node.get("name") or ""
        else:
            name = ", ".join(item["name"] for item in node.get("names", []))
        symbol_kind = 13
    elif kind == "type_alias":
        name = node.get("name") or ""
        symbol_kind = 5
    if name:
        symbols.append({"name": name, "kind": symbol_kind, "range": node.span.lsp(), "selectionRange": node.span.lsp()})
    for value in node.props.values():
        if isinstance(value, Node):
            _collect_symbols(value, symbols)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Node):
                    _collect_symbols(item, symbols)


def _semantic_pieces(result: ParseResult):
    classes = _token_kinds(result.language)
    for token in result.tokens:
        if token.kind == "eof":
            continue
        kind = _semantic_kind(token, classes)
        if kind not in TOKEN_INDEX:
            continue
        line = token.span.start_line - 1
        col = token.span.start_col - 1
        for part in token.text.split("\n"):
            yield line, col, len(part), kind
            line += 1
            col = 0


def _token_kinds(language_id: str) -> dict[str, str]:
    if language_id == "lsl":
        symbols = lsl_symbols()
        kinds = {name: "function" for name in symbols["functions"]}
        kinds.update({name: "event" for name in symbols["events"]})
        return kinds
    symbols = slua_symbols()
    return {item["name"]: "function" for item in symbols.get("builtins", [])}


def _semantic_kind(token: Token, classes: dict[str, str]) -> str:
    if token.kind == "comment":
        return "comment"
    if token.kind == "string":
        return "string"
    if token.kind == "number":
        return "number"
    if token.kind == "keyword":
        return "keyword"
    if token.kind == "type":
        return "type"
    if token.kind == "identifier":
        return classes.get(token.text, "variable")
    if token.kind == "operator":
        return "keyword" if token.text in {"and", "or", "not"} else ""
    return ""


def _result(request_id, value) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _notify(method: str, params: dict) -> None:
    _write(sys.stdout.buffer, {"jsonrpc": "2.0", "method": method, "params": params})


def _read(reader) -> dict | None:
    headers = {}
    while True:
        line = reader.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = reader.read(length)
    return json.loads(body.decode("utf-8"))


def _write(writer, message: dict) -> None:
    body = json.dumps(message).encode("utf-8")
    writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    writer.flush()
