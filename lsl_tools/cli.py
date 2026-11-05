"""Command line for parsing, linting, formatting, highlighting, and the language server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lsl_tools.adapters import ADAPTERS
from lsl_tools.highlight import highlight
from lsl_tools.registry import language_for_path, languages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsl-tools", description="LSL and SLua language tools")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="parse a file and print the syntax tree")
    _add_file(parse_cmd)
    parse_cmd.add_argument("--sexp", action="store_true", help="print the tree instead of a summary")

    lint_cmd = sub.add_parser("lint", help="report parser and lint diagnostics")
    lint_cmd.add_argument("paths", nargs="+")

    format_cmd = sub.add_parser("format", help="format source")
    format_cmd.add_argument("paths", nargs="*")
    format_cmd.add_argument("--language", choices=sorted(languages()))
    format_cmd.add_argument("--write", action="store_true")
    format_cmd.add_argument("--check", action="store_true")

    highlight_cmd = sub.add_parser("highlight", help="print ANSI-colored source")
    _add_file(highlight_cmd)
    highlight_cmd.add_argument("--no-color", action="store_true")

    sub.add_parser("lsp", help="run the language server on stdin")
    generate = sub.add_parser("generate", help="write editor packages")
    generate.add_argument("--editor", choices=sorted(ADAPTERS), action="append")

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args)
    if args.command == "lint":
        return _lint(args.paths)
    if args.command == "format":
        return _format(args)
    if args.command == "highlight":
        return _highlight(args)
    if args.command == "lsp":
        from lsl_tools.lsp import serve

        serve()
        return 0
    if args.command == "generate":
        selected = args.editor or sorted(ADAPTERS)
        for name in selected:
            print(ADAPTERS[name].emit())
        return 0
    return 2


def _add_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", default="-")
    parser.add_argument("--language", choices=sorted(languages()))


def _language(path: str, explicit: str | None):
    if explicit:
        return languages()[explicit]
    if path == "-":
        sys.exit("pass --language when reading stdin")
    language = language_for_path(path)
    if language is None:
        sys.exit(f"cannot tell which language {path} is; pass --language")
    return language


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _parse(args) -> int:
    language = _language(args.path, args.language)
    result = language.parse(_read(args.path))
    if args.sexp:
        print(result.tree.sexp())
    else:
        print(f"{language.name}: {len(result.errors)} syntax error(s)")
    for error in result.errors:
        print(f"{error.span.start_line}:{error.span.start_col}: {error.message}", file=sys.stderr)
    return 1 if result.errors else 0


def _lint(paths: list[str]) -> int:
    failed = False
    for path in paths:
        language = language_for_path(path)
        if language is None:
            print(f"{path}: skipped", file=sys.stderr)
            continue
        result = language.parse(Path(path).read_text(encoding="utf-8"))
        diagnostics = list(result.errors)
        diagnostics.extend(language.lint(result))
        for item in diagnostics:
            print(f"{path}:{item.span.start_line}:{item.span.start_col}: {item.severity}: {item.message}")
            if item.severity == "error":
                failed = True
    return 1 if failed else 0


def _format(args) -> int:
    paths = args.paths or ["-"]
    changed = False
    for path in paths:
        explicit = args.language
        if path == "-" and not explicit and len(paths) == 1:
            explicit = explicit or None
        language = _language(path, explicit)
        source = _read(path)
        result = language.parse(source)
        if result.errors:
            print(f"{path}: not formatted, source has syntax errors", file=sys.stderr)
            for error in result.errors:
                print(f"{error.span.start_line}:{error.span.start_col}: {error.message}", file=sys.stderr)
            return 1
        formatted = language.format(result)
        if formatted != source:
            changed = True
        if args.check:
            continue
        if args.write and path != "-":
            Path(path).write_text(formatted, encoding="utf-8")
        else:
            sys.stdout.write(formatted)
    return 1 if args.check and changed else 0


def _highlight(args) -> int:
    language = _language(args.path, args.language)
    sys.stdout.write(highlight(_read(args.path), language, color=not args.no_color))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
