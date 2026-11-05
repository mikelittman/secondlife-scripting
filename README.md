# lsl-dev-tools

Language tooling for [Linden Scripting Language](https://github.com/secondlife/tailslide) and [SLua](https://github.com/secondlife/slua). One parser, linter, and formatter feeds every editor. Gram is the first editor package. VS Code, Helix, and Neovim are generated from the same language packs.

Symbol names, signatures, and deprecations come from [lsl-definitions](https://github.com/secondlife/lsl-definitions). The LSL grammar follows Tailslide's parser. SLua syntax is Luau; its tree-sitter parser is [tree-sitter-luau](https://github.com/tree-sitter-grammars/tree-sitter-luau), and the highlight queries add the Second Life libraries (`ll.Say`, `LLEvents`, `vector`, and the rest).

## Layout

| Path | Role |
| --- | --- |
| `lsl_tools/lsl`, `lsl_tools/slua` | Parser, formatter, and linter |
| `lsl_tools/data` | Symbol tables generated from lsl-definitions |
| `lsl_tools/lsp.py` | Language server: diagnostics, formatting, hover, symbols, semantic tokens |
| `languages/lsl` | Tree-sitter grammar and queries |
| `languages/slua/queries` | Highlight, indent, and outline queries on top of Luau |
| `languages/*/format.toml`, `lint.toml` | Formatting and lint rules |
| `lsl_tools/adapters` | Turns those packs into editor files |
| `editors/` | Generated Gram, VS Code, Helix, and Neovim packages |

## Use the tools

```bash
python3 -m lsl_tools lint examples/hello.lsl examples/hello.slua
python3 -m lsl_tools format examples/hello.lsl
python3 -m lsl_tools highlight examples/hello.slua
python3 -m lsl_tools lsp
```

`format` reads stdin when you pass `-` and `--language lsl` or `--language slua`. It leaves a file alone when the parser reports a syntax error.

Lint rules and severities are in `languages/lsl/lint.toml` and `languages/slua/lint.toml`. Set a rule to `off` to silence it. LSL brace style is `brace_style` in `languages/lsl/format.toml` (`same_line` or `next_line`).

## Gram

This repository is the Gram extension. `extension.toml` is at the root.

Publish it to `https://github.com/mikelittman/secondlife-scripting` on the `main` branch, then in Gram install that repository URL. Gram compiles the LSL grammar from `languages/lsl` and the SLua grammar from tree-sitter-luau. The Rust crate in `src/lib.rs` starts the language server: `lsl-tools lsp` when that command is on `PATH`, otherwise `python3 -m lsl_tools lsp` using the checkout Gram just cloned. Python 3.11 or newer needs to be on `PATH`. Rust and a C toolchain are needed the first time Gram builds the extension.

If the GitHub repository URL is different, change both `repository` fields in `extension.toml` before publishing. The grammar revision `main` is what Gram fetches.

## Other editors

`python3 -m lsl_tools generate` also writes:

- `editors/vscode` — TextMate grammars generated from the symbol tables
- `editors/helix` — `languages.toml` plus the tree-sitter queries
- `editors/nvim` — ftdetect, queries, and an lspconfig snippet

To add an editor, implement `emit(self, out: Path) -> Path` in `lsl_tools/adapters`, register it in `ADAPTERS`, and read `lsl_tools.registry.languages()`. Query files live next to each language's `config.toml`.

## Refresh the symbol tables

```bash
python3 -m venv .venv
.venv/bin/pip install pyyaml
.venv/bin/python tools/sync_definitions.py
```

The runtime does not need PyYAML. It reads `lsl_tools/data/*.json`.

## What the parsers cover

The LSL parser follows Tailslide: globals, states, events, C-like statements, casts, and `<>` / `[]` literals. A comparison inside a vector or rotation literal needs parentheses, as in `<(a > b), 0, 0>`. The tree-sitter grammar is slightly looser so a half-written script still highlights.

The SLua parser covers Luau statements, expressions, type annotations (kept as source text), and interpolations as single string tokens. Calls inside a backtick string are not linted separately.

## Tests

```bash
python3 -m unittest discover -s tests -v
cd languages/lsl && npx tree-sitter test
```
