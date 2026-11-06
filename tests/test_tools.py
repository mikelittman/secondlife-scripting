import tempfile
import tomllib
import unittest
from pathlib import Path

from lsl_tools.adapters import ADAPTERS
from lsl_tools.highlight import highlight
from lsl_tools.lsp import Server
from lsl_tools.registry import languages


class ToolTests(unittest.TestCase):
    def test_examples_parse(self):
        root = Path(__file__).resolve().parents[1] / "examples"
        for path in sorted(root.iterdir()):
            language = languages()["lsl" if path.suffix == ".lsl" else "slua"]
            result = language.parse(path.read_text(encoding="utf-8"))
            self.assertEqual(result.errors, [], path.name)
            self.assertFalse(any(item.severity == "error" for item in language.lint(result)), path.name)

    def test_generate_writes_every_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, adapter in ADAPTERS.items():
                written = adapter.emit(root / name)
                self.assertTrue(written.is_dir(), name)
            gram = (root / "gram" / "extension.toml").read_text(encoding="utf-8")
            self.assertIn("[grammars.lsl]", gram)
            self.assertIn("[grammars.luau]", gram)
            self.assertTrue((root / "gram" / "languages" / "lsl" / "highlights.scm").is_file())
            self.assertTrue((root / "gram" / "languages" / "slua" / "highlights.scm").is_file())
            for language in ("lsl", "slua"):
                text = (root / "gram" / "languages" / language / "config.toml").read_text(encoding="utf-8")
                parsed = tomllib.loads(text)
                self.assertIn("brackets", parsed)
            package = (root / "vscode" / "package.json").read_text(encoding="utf-8")
            self.assertIn("source.lsl", package)
            self.assertIn("source.slua", package)
            self.assertTrue((root / "helix" / "languages.toml").is_file())
            self.assertTrue((root / "nvim" / "lua" / "lsl-tools.lua").is_file())

    def test_highlight_marks_a_library_call(self):
        colored = highlight('default { state_entry() { llOwnerSay("hi"); } }\n', languages()["lsl"])
        self.assertIn("llOwnerSay", colored)
        self.assertIn("\033[", colored)

    def test_language_server_format_and_hover(self):
        server = Server(notify=lambda *_args: None)
        opened = server.handle(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///hello.lsl",
                        "languageId": "lsl",
                        "text": "default{state_entry(){llOwnerSay(\"hi\");}}",
                    }
                },
            }
        )
        self.assertIsNone(opened)
        formatted = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/formatting",
                "params": {"textDocument": {"uri": "file:///hello.lsl"}},
            }
        )
        self.assertIn("    state_entry() {", formatted["result"][0]["newText"])
        hover = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": "file:///hello.lsl"},
                    "position": {"line": 0, "character": 28},
                },
            }
        )
        self.assertIn("llOwnerSay", hover["result"]["contents"]["value"])
        broken = server.handle(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": "file:///hello.lsl"},
                    "contentChanges": [{"text": "default { state_entry() { $$$; } }"}],
                },
            }
        )
        self.assertIsNone(broken)
        refused = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "textDocument/formatting",
                "params": {"textDocument": {"uri": "file:///hello.lsl"}},
            }
        )
        self.assertIn("syntax errors", refused["error"]["message"])


if __name__ == "__main__":
    unittest.main()
