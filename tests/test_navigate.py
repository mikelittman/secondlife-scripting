import unittest

from lsl_tools.lsl.parser import parse as parse_lsl
from lsl_tools.lsp import Server
from lsl_tools.navigate import definition, highlights, references
from lsl_tools.slua.parser import parse as parse_slua

LSL = """
integer g = 1;

string greet(string name) {
    return name;
}

default {
    state_entry() {
        integer g = 2;
        string called = greet(g);
        vector v = <0, 0, 0>;
        if (v.x) {
            jump done;
        }
        @done;
        for (integer i = 0; i < g; ++i) {
            llOwnerSay((string)i);
        }
        llOwnerSay((string)g);
    }
    touch_start(integer total_number) {
        state other;
    }
}

state other {
    state_entry() {
        llOwnerSay(greet(g));
    }
}
"""

SLUA = """
local function greet(name)
    return name
end

function announce(text)
    greet(text)
end

local g = 1
local function shadow(g)
    return g
end
"""


def _word(source: str, snippet: str, word: str, which: int = 0) -> tuple[int, int, int]:
    base = -1
    for _ in range(which + 1):
        base = source.find(snippet, base + 1)
        if base < 0:
            raise AssertionError(f"missing snippet {snippet!r}")
    start = source.find(word, base)
    while start >= 0 and start <= base + len(snippet):
        before = source[start - 1] if start else ""
        after = source[start + len(word) : start + len(word) + 1]
        if before not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" and after not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_":
            break
        start = source.find(word, start + 1)
    if start < 0 or start > base + len(snippet):
        raise AssertionError(f"{word!r} not in {snippet!r}")
    line = source.count("\n", 0, start)
    column = start - source.rfind("\n", 0, start) - 1
    return line, column, start


class NavigateTests(unittest.TestCase):
    def test_lsl_click_through_function_variable_and_state(self):
        result = parse_lsl(LSL)
        self.assertEqual(result.errors, [])

        def target(snippet, word, which=0):
            line, column, _start = _word(LSL, snippet, word, which)
            found = definition(result, line, column)
            self.assertIsNotNone(found, snippet)
            return found[1].name_span.start_offset

        self.assertEqual(target("greet(g)", "greet"), LSL.find("greet(string name)"))
        self.assertEqual(target("greet(g)", "g"), LSL.find("g = 2"))
        self.assertEqual(target("greet(g)", "greet", 1), LSL.find("greet(string name)"))
        self.assertEqual(target("greet(g)", "g", 1), LSL.find("g = 1"))
        self.assertEqual(target("return name", "name"), LSL.find("name)"))
        self.assertEqual(target("v.x", "v"), LSL.find("v ="))
        self.assertIsNone(definition(result, *_word(LSL, "v.x", "x")[:2]))
        self.assertEqual(target("jump done", "done"), LSL.find("@done") + 1)
        self.assertEqual(target("(string)i)", "i"), LSL.find("i ="))
        self.assertEqual(target("state other;", "other"), LSL.find("state other {") + len("state "))
        self.assertIsNone(definition(result, *_word(LSL, "llOwnerSay", "llOwnerSay")[:2]))
        self.assertEqual(len(references(result, *_word(LSL, "greet(string name)", "greet")[:2])), 3)
        self.assertTrue(any(kind == 2 for _span, kind in highlights(result, *_word(LSL, "g = 2", "g")[:2])))

    def test_slua_click_through_local_function_and_parameter(self):
        result = parse_slua(SLUA)
        self.assertEqual(result.errors, [])
        line, column, _start = _word(SLUA, "greet(text)", "greet")
        _origin, greet = definition(result, line, column)
        self.assertEqual(greet.name_span.start_offset, SLUA.find("greet(name)"))
        line, column, _start = _word(SLUA, "return g", "g")
        _origin, param = definition(result, line, column)
        self.assertEqual(param.name_span.start_offset, SLUA.find("shadow(g)") + len("shadow("))
        line, column, _start = _word(SLUA, "greet(text)", "text")
        _origin, text = definition(result, line, column)
        self.assertEqual(text.name_span.start_offset, SLUA.find("announce(text)") + len("announce("))

    def test_language_server_definition(self):
        server = Server(notify=lambda *_args: None)
        server.handle(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///home/resident/script.lsl",
                        "languageId": "lsl",
                        "text": LSL,
                    }
                },
            }
        )
        line, column, _start = _word(LSL, "greet(g)", "greet")
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": "file:///home/resident/script.lsl"},
                    "position": {"line": line, "character": column},
                },
            }
        )
        link = response["result"][0]
        self.assertEqual(link["targetUri"], "file:///home/resident/script.lsl")
        self.assertEqual(link["targetSelectionRange"]["start"]["line"], LSL[: LSL.find("greet(string name)")].count("\n"))
        caps = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertTrue(caps["result"]["capabilities"]["definitionProvider"])


if __name__ == "__main__":
    unittest.main()
