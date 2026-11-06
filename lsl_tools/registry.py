"""Language registry. An editor adapter iterates this instead of hard-coding LSL."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from lsl_tools.lsl.format import format_source as format_lsl
from lsl_tools.lsl.lexer import Lexer as LslLexer
from lsl_tools.lsl.lint import lint as lint_lsl
from lsl_tools.lsl.parser import parse as parse_lsl
from lsl_tools.slua.format import format_source as format_slua
from lsl_tools.slua.lexer import Lexer as SluaLexer
from lsl_tools.slua.lint import lint as lint_slua
from lsl_tools.slua.parser import parse as parse_slua
from lsl_tools.symbols import project_root


@dataclass(frozen=True)
class Language:
    id: str
    name: str
    scope: str
    grammar: str
    extensions: tuple[str, ...]
    line_comment: str
    block_comment: tuple[str, str] | None
    tab_size: int
    description: str
    grammar_repository: str
    grammar_rev: str
    grammar_path: str
    parse: object
    lint: object
    format: object
    tokenize: object

    @property
    def directory(self) -> Path:
        return project_root() / "languages" / self.id

    @property
    def queries(self) -> Path:
        return self.directory


def _load(language_id: str, parse, lint, format_source, lexer) -> Language:
    path = project_root() / "languages" / language_id / "pack.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    block = data.get("block_comment")
    return Language(
        id=data["id"],
        name=data["name"],
        scope=data["scope"],
        grammar=data["grammar"],
        extensions=tuple(data.get("extensions", [])),
        line_comment=data.get("line_comment", ""),
        block_comment=tuple(block) if block else None,
        tab_size=int(data.get("tab_size", 4)),
        description=data.get("description", data["name"]),
        grammar_repository=data.get("grammar_repository", ""),
        grammar_rev=data.get("grammar_rev", ""),
        grammar_path=data.get("grammar_path", ""),
        parse=parse,
        lint=lint,
        format=format_source,
        tokenize=lambda source: lexer(source).tokenize(),
    )


def languages() -> dict[str, Language]:
    return {
        "lsl": _load("lsl", parse_lsl, lint_lsl, format_lsl, LslLexer),
        "slua": _load("slua", parse_slua, lint_slua, format_slua, SluaLexer),
    }


def language_for_path(path: str) -> Language | None:
    suffix = Path(path).suffix.lower().lstrip(".")
    for language in languages().values():
        if suffix in language.extensions:
            return language
    return None


def language_for_id(language_id: str) -> Language | None:
    aliases = {
        "lsl": "lsl",
        "linden": "lsl",
        "lindenscript": "lsl",
        "slua": "slua",
        "luau": "slua",
        "serverlua": "slua",
    }
    return languages().get(aliases.get(language_id.lower(), ""))
