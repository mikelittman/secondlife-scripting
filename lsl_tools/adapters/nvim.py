"""Neovim adapter. Queries are the same files Gram and Helix load."""

from __future__ import annotations

import shutil
from pathlib import Path

from lsl_tools.registry import languages
from lsl_tools.symbols import project_root


class NvimAdapter:
    id = "nvim"

    def emit(self, out: Path | None = None) -> Path:
        root = project_root()
        destination = out or root / "editors" / "nvim"
        if destination.exists():
            shutil.rmtree(destination)
        ftdetect = destination / "ftdetect"
        ftdetect.mkdir(parents=True)
        lines = []
        for language in languages().values():
            for suffix in language.extensions:
                lines.append(f'au BufRead,BufNewFile *.{suffix} setfiletype {language.id}')
            query_dir = destination / "queries" / language.id
            query_dir.mkdir(parents=True)
            for query in language.queries.glob("*.scm"):
                shutil.copy(query, query_dir / query.name)
        (ftdetect / "lsl.vim").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (destination / "lua" / "lsl-tools.lua").parent.mkdir(parents=True)
        (destination / "lua" / "lsl-tools.lua").write_text(_lua(), encoding="utf-8")
        return destination


def _lua() -> str:
    filetypes = ", ".join(f'"{suffix}"' for language in languages().values() for suffix in language.extensions)
    return f"""-- Point Neovim at the LSL tree-sitter grammar and the shared language server.
-- SLua reuses the upstream Luau parser; its queries add the Second Life libraries.

local parser_config = require("nvim-treesitter.parsers").get_parser_configs()
parser_config.lsl = {{
  install_info = {{
    url = "https://github.com/mikelittman/secondlife-scripting",
    location = "languages/lsl",
    branch = "main",
    files = {{ "src/parser.c" }},
  }},
  filetype = "lsl",
}}

local configs = require("lspconfig.configs")
local util = require("lspconfig.util")
if not configs.lsl_tools then
  configs.lsl_tools = {{
    default_config = {{
      cmd = {{ "lsl-tools", "lsp" }},
      filetypes = {{ {filetypes} }},
      root_dir = util.root_pattern(".git"),
      single_file_support = true,
    }},
  }}
end
require("lspconfig").lsl_tools.setup({{}})
"""
