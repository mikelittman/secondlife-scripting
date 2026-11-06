"""VS Code / TextMate adapter.

Tree-sitter is what Gram uses. TextMate is the lexical highlighting path for
editors that do not load a tree-sitter grammar. The token rules are generated
from the same symbol tables.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lsl_tools.registry import languages
from lsl_tools.symbols import lsl_symbols, project_root, slua_symbols


class VsCodeAdapter:
    id = "vscode"

    def emit(self, out: Path | None = None) -> Path:
        destination = out or project_root() / "editors" / "vscode"
        if destination.exists():
            shutil.rmtree(destination)
        syntax = destination / "syntaxes"
        syntax.mkdir(parents=True)
        (syntax / "lsl.tmLanguage.json").write_text(
            json.dumps(_lsl_grammar(), indent=2) + "\n", encoding="utf-8"
        )
        (syntax / "slua.tmLanguage.json").write_text(
            json.dumps(_slua_grammar(), indent=2) + "\n", encoding="utf-8"
        )
        (destination / "package.json").write_text(json.dumps(_package(), indent=2) + "\n", encoding="utf-8")
        (destination / "language-configuration.json").write_text(
            json.dumps(_configuration(), indent=2) + "\n", encoding="utf-8"
        )
        return destination


def _package() -> dict:
    return {
        "name": "lsl-slua",
        "displayName": "LSL and SLua",
        "description": "Syntax highlighting for Linden Scripting Language and SLua.",
        "version": "0.1.4",
        "publisher": "local",
        "engines": {"vscode": "^1.85.0"},
        "categories": ["Programming Languages"],
        "contributes": {
            "languages": [
                {
                    "id": language.id,
                    "aliases": [language.name, language.id],
                    "extensions": [f".{suffix}" for suffix in language.extensions],
                    "configuration": "./language-configuration.json",
                }
                for language in languages().values()
            ],
            "grammars": [
                {
                    "language": language.id,
                    "scopeName": language.scope,
                    "path": f"./syntaxes/{language.id}.tmLanguage.json",
                }
                for language in languages().values()
            ],
        },
    }


def _configuration() -> dict:
    return {
        "comments": {"lineComment": "//", "blockComment": ["/*", "*/"]},
        "brackets": [["{", "}"], ["[", "]"], ["(", ")"], ["<", ">"]],
        "autoClosingPairs": [
            {"open": "{", "close": "}"},
            {"open": "[", "close": "]"},
            {"open": "(", "close": ")"},
            {"open": '"', "close": '"', "notIn": ["string"]},
        ],
    }


def _keyword(words: list[str], scope: str) -> dict:
    body = "|".join(sorted(set(words), key=len, reverse=True))
    return {"match": rf"\b(?:{body})\b", "name": scope}


def _lsl_grammar() -> dict:
    symbols = lsl_symbols()
    return {
        "name": "LSL",
        "scopeName": "source.lsl",
        "patterns": [{"include": f"#{name}"} for name in ("comment", "string", "number", "keyword", "type", "function", "event", "constant")],
        "repository": {
            "comment": {
                "patterns": [
                    {"name": "comment.line.double-slash.lsl", "match": r"//.*$"},
                    {"name": "comment.block.lsl", "begin": r"/\*", "end": r"\*/"},
                ]
            },
            "string": {"name": "string.quoted.double.lsl", "begin": r'L?"', "end": r'"', "patterns": [{"match": r"\\.", "name": "constant.character.escape.lsl"}]},
            "number": {"name": "constant.numeric.lsl", "match": r"\b(?:0[xX][0-9A-Fa-f]+|\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fF]?\b"},
            "keyword": _keyword(symbols["controls"], "keyword.control.lsl"),
            "type": _keyword(list(symbols["types"]), "storage.type.lsl"),
            "function": {"name": "support.function.lsl", "match": r"\bll[A-Z][A-Za-z0-9]*\b"},
            "event": _keyword(list(symbols["events"]), "entity.name.function.event.lsl"),
            "constant": {"name": "constant.language.lsl", "match": r"\b[A-Z][A-Z0-9_]+\b"},
        },
    }


def _slua_grammar() -> dict:
    symbols = slua_symbols()
    modules = sorted(symbols["modules"])
    return {
        "name": "SLua",
        "scopeName": "source.slua",
        "patterns": [{"include": f"#{name}"} for name in ("comment", "string", "number", "keyword", "module", "constant")],
        "repository": {
            "comment": {
                "patterns": [
                    {"name": "comment.block.slua", "begin": r"--\[(=*)\[", "end": r"\]\1\]"},
                    {"name": "comment.line.slua", "match": r"--.*$"},
                ]
            },
            "string": {
                "patterns": [
                    {"name": "string.quoted.other.slua", "begin": "`", "end": "`"},
                    {"name": "string.quoted.double.slua", "begin": r"\[(=*)\[", "end": r"\]\1\]"},
                    {"name": "string.quoted.double.slua", "begin": '"', "end": '"'},
                    {"name": "string.quoted.single.slua", "begin": "'", "end": "'"},
                ]
            },
            "number": {"name": "constant.numeric.slua", "match": r"\b(?:0[xXbB][\dA-Fa-f_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d[\d_]*)?)\b"},
            "keyword": _keyword(symbols["controls"] + ["nil", "true", "false", "typeof"], "keyword.control.slua"),
            "module": _keyword(modules + ["LLEvents", "LLTimers"], "support.class.slua"),
            "constant": {"name": "constant.language.slua", "match": r"\b[A-Z][A-Z0-9_]*\b"},
        },
    }
