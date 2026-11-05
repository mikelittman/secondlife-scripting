"""Helix adapter. Helix reads the same tree-sitter queries Gram does."""

from __future__ import annotations

import shutil
from pathlib import Path

from lsl_tools.registry import languages
from lsl_tools.symbols import project_root


class HelixAdapter:
    id = "helix"

    def emit(self, out: Path | None = None) -> Path:
        root = project_root()
        destination = out or root / "editors" / "helix"
        if destination.exists():
            shutil.rmtree(destination)
        runtime = destination / "runtime" / "queries"
        blocks = []
        for language in languages().values():
            query_dir = runtime / language.id
            query_dir.mkdir(parents=True)
            for query in language.queries.glob("*.scm"):
                shutil.copy(query, query_dir / query.name)
            blocks.append(self._language(language))
        blocks.append('[language-server.lsl-tools]\ncommand = "lsl-tools"\nargs = ["lsp"]\n')
        (destination / "languages.toml").write_text("\n".join(blocks) + "\n", encoding="utf-8")
        return destination

    def _language(self, language) -> str:
        comment = f'comment-token = "{language.line_comment}"'
        block = ""
        if language.block_comment:
            start, end = language.block_comment
            block = f'block-comment-tokens = {{ start = "{start}", end = "{end}" }}\n'
        grammar = ""
        if language.id == "lsl":
            grammar = (
                "\n[[grammar]]\n"
                'name = "lsl"\n'
                'source = { git = "https://github.com/mikelittman/secondlife-scripting", rev = "main", subpath = "languages/lsl" }\n'
            )
        else:
            grammar = (
                "\n[[grammar]]\n"
                f'name = "{language.grammar}"\n'
                f'source = {{ git = "{language.grammar_repository}", rev = "{language.grammar_rev}" }}\n'
            )
        suffixes = ", ".join(f'"{suffix}"' for suffix in language.extensions)
        return (
            "[[language]]\n"
            f'name = "{language.id}"\n'
            f'scope = "{language.scope}"\n'
            f"file-types = [{suffixes}]\n"
            f'injection-regex = "{language.id}"\n'
            f"{comment}\n"
            f"{block}"
            f'indent = {{ tab-width = {language.tab_size}, unit = "{" " * language.tab_size}" }}\n'
            'language-servers = ["lsl-tools"]\n'
            f'grammar = "{language.grammar}"\n'
            f"{grammar}"
        )
