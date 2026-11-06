"""Gram extension. Gram is a Zed fork, so this is a Zed language extension."""

from __future__ import annotations

import shutil
from pathlib import Path

from lsl_tools.registry import languages
from lsl_tools.symbols import project_root


def _toml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class GramAdapter:
    id = "gram"

    def emit(self, out: Path | None = None) -> Path:
        if out is None:
            return project_root()
        destination = out
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        self._manifest(destination)
        for language in languages().values():
            folder = destination / "languages" / language.id
            folder.mkdir(parents=True)
            (folder / "config.toml").write_text(self._config(language), encoding="utf-8")
            for query in sorted(language.queries.glob("*.scm")):
                shutil.copy(query, folder / query.name)
        (destination / "lsp-settings.json").write_text(self._settings(), encoding="utf-8")
        return destination

    def _manifest(self, destination: Path) -> None:
        lines = [
            'id = "lsl-slua"',
            'name = "LSL and SLua"',
            'version = "0.1.4"',
            "schema_version = 1",
            'description = "Highlighting and language server for Linden Scripting Language and SLua."',
            'repository = "https://github.com/mikelittman/secondlife-scripting"',
            "",
            "[grammars.lsl]",
            'repository = "https://github.com/mikelittman/secondlife-scripting"',
            'rev = "main"',
            'path = "languages/lsl"',
            "",
            "[language_servers.lsl-tools]",
            'name = "LSL Tools"',
            'languages = ["LSL", "SLua"]',
            "",
            "[language_servers.lsl-tools.language_ids]",
            'LSL = "lsl"',
            'SLua = "slua"',
            "",
        ]
        slua = languages()["slua"]
        lines += [
            f"[grammars.{slua.grammar}]",
            f'repository = "{slua.grammar_repository}"',
            f'rev = "{slua.grammar_rev}"',
            "",
        ]
        (destination / "extension.toml").write_text("\n".join(lines), encoding="utf-8")

    def _config(self, language) -> str:
        suffixes = ", ".join(f'"{suffix}"' for suffix in language.extensions)
        comments = f'["{language.line_comment} "]'
        brackets = self._brackets(language.id)
        indent = ""
        if language.id == "lsl":
            indent = (
                'increase_indent_pattern = "\\\\{\\\\s*(//.*|/\\\\*.*)?$|\\\\b(if|else|for|while|do)\\\\b[^;{}]*$"\n'
                'decrease_indent_pattern = "^\\\\s*(\\\\}|else\\\\b)"\n'
            )
        elif language.id == "slua":
            indent = 'decrease_indent_pattern = "^\\\\s*(end|else|elseif|until)\\\\b"\n'
        return (
            f'name = "{language.name}"\n'
            f'grammar = "{language.grammar}"\n'
            f"path_suffixes = [{suffixes}]\n"
            f"line_comments = {comments}\n"
            f"tab_size = {language.tab_size}\n"
            "hard_tabs = false\n"
            f"{indent}"
            'autoclose_before = ";:.,=}])>\\n\\t "\n'
            f"{brackets}"
        )

    def _brackets(self, language_id: str) -> str:
        pairs = [
            ('{', '}', "true"),
            ('[', ']', "true"),
            ('(', ')', "false"),
            ('"', '"', "false"),
        ]
        if language_id == "lsl":
            pairs.append(("<", ">", "false"))
        if language_id == "slua":
            pairs.append(("'", "'", "false"))
        rows = []
        for start, end, newline in pairs:
            rows.append(
                "  { start = "
                + _toml(start)
                + ", end = "
                + _toml(end)
                + ", close = true, newline = "
                + newline
                + ', not_in = ["comment", "string"] },'
            )
        return "brackets = [\n" + "\n".join(rows) + "\n]\n"

    def _settings(self) -> str:
        return """{
  "languages": {
    "LSL": {
      "formatter": {
        "external": {
          "command": "lsl-tools",
          "arguments": ["format", "--language", "lsl", "-"]
        }
      },
      "format_on_save": "on"
    },
    "SLua": {
      "formatter": {
        "external": {
          "command": "lsl-tools",
          "arguments": ["format", "--language", "slua", "-"]
        }
      },
      "format_on_save": "on"
    }
  },
  "lsp": {
    "lsl-tools": {
      "binary": {
        "path": "lsl-tools",
        "arguments": ["lsp"]
      }
    }
  }
}
"""
