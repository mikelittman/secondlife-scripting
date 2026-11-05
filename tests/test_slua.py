import unittest

from lsl_tools.slua.format import Style, format_source
from lsl_tools.slua.lint import lint
from lsl_tools.slua.parser import parse

SAMPLE = """
local function greet(name: string): string
    return "Hello, " .. name
end

LLEvents:on("state_entry", function()
    ll.OwnerSay(greet("world"))
    local v = vector(1, 2, 3)
    if v.x > 0 then
        print(math.abs(-1))
    end
end)
"""


class SluaTests(unittest.TestCase):
    def test_structure(self):
        result = parse(SAMPLE)
        self.assertEqual(result.errors, [], [error.message for error in result.errors])
        body = result.tree.get("body")
        self.assertEqual(body[0].kind, "local_function")
        self.assertEqual(body[0].get("name"), "greet")
        self.assertEqual(body[0].get("return_type"), "string")
        call = body[1]
        self.assertEqual(call.kind, "method_call")
        self.assertEqual(call.get("method"), "on")
        handler = call.get("args")[1]
        self.assertEqual(handler.kind, "function_expression")
        statements = handler.get("body")
        self.assertEqual(statements[0].kind, "call_expression")
        self.assertEqual(statements[0].get("callee").get("field"), "OwnerSay")

    def test_statements(self):
        source = """
local x = 1
x += 2
for i = 1, 10 do
    if i % 2 == 0 then
        continue
    end
end
local t = { a = 1, [2] = 3, 4 }
type Pair = { x: number, y: number }
export type Id = string
"""
        result = parse(source)
        self.assertEqual(result.errors, [], [error.message for error in result.errors])
        kinds = [node.kind for node in result.tree.get("body")]
        self.assertEqual(
            kinds,
            ["local_declaration", "update_statement", "for_numeric", "local_declaration", "type_alias", "type_alias"],
        )
        self.assertTrue(result.tree.get("body")[-1].get("exported"))

    def test_format_is_stable(self):
        result = parse(SAMPLE)
        self.assertEqual(result.errors, [])
        once = format_source(result, Style())
        twice = format_source(parse(once), Style())
        self.assertEqual(once, twice)
        self.assertIn('ll.OwnerSay(greet("world"))', once)
        self.assertIn("local function greet(name: string): string", once)

    def test_lint(self):
        source = """
LLEvents:on("state_entry", function()
    ll.OwnerSay()
    ll.Cloud(vector(0, 0, 1))
    ll.NotReal(1)
    llcompat.Say(0, "hi")
    local flag = TRUE
end)
LLEvents:on("not_an_event", function() end)
"""
        result = parse(source)
        self.assertEqual(result.errors, [], [error.message for error in result.errors])
        codes = {item.code for item in lint(result)}
        self.assertTrue(
            {"arity", "deprecated-function", "unknown-function", "removed-constant", "unknown-event"} <= codes
        )


if __name__ == "__main__":
    unittest.main()
