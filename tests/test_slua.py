import unittest

from lsl_tools.slua.format import Style, format_source
from lsl_tools.slua.lint import lint
from lsl_tools.slua.parser import parse

SAMPLE = """
local function greet(name: string): string
    return "Hello, " .. name
end

LLEvents:on("touch_start", function()
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

    def test_completion_lists_ll_functions(self):
        from lsl_tools.complete import complete

        items = complete("slua", "local value = ll.Ow", 0, len("local value = ll.Ow"))
        labels = {item["label"] for item in items}
        self.assertIn("OwnerSay", labels)
        self.assertNotIn("Say", labels)
        self.assertNotIn("SetTimerEvent", labels)
        owner = next(item for item in items if item["label"] == "OwnerSay")
        self.assertIn("msg: string", owner["detail"])
        self.assertEqual(owner["tags"], [1])
        all_ll = complete("slua", "ll.", 0, len("ll."))
        all_labels = {item["label"] for item in all_ll}
        self.assertIn("Say", all_labels)
        self.assertNotIn("SetTimerEvent", all_labels)
        modules = complete("slua", "ll", 0, 2)
        self.assertIn("ll", {item["label"] for item in modules})
        events = complete("slua", "LLEvents:", 0, len("LLEvents:"))
        self.assertIn("on", {item["label"] for item in events})
        lsl = complete("lsl", "llOw", 0, 4)
        self.assertIn("llOwnerSay", {item["label"] for item in lsl})

    def test_type_and_typeof_are_calls(self):
        source = """
local kind = type(vector(1, 2, 3))
local precise = typeof(kind)
type Vec = vector
export type Id = string
local function describe(value)
    return type(value)
end
"""
        result = parse(source)
        self.assertEqual(result.errors, [], [error.message for error in result.errors])
        kinds = [node.kind for node in result.tree.get("body")]
        self.assertEqual(kinds, ["local_declaration", "local_declaration", "type_alias", "type_alias", "local_function"])

    def test_lint(self):
        source = """
LLEvents:on("touch_start", function()
    ll.OwnerSay()
    ll.Cloud(vector(0, 0, 1))
    ll.NotReal(1)
    ll.SetTimerEvent(1)
    llcompat.Say(0, "hi")
    assert(true)
    error("x")
    local flag = TRUE
end)
LLEvents:on("state_entry", function() end)
LLEvents:on("not_an_event", function() end)
"""
        result = parse(source)
        self.assertEqual(result.errors, [], [error.message for error in result.errors])
        diagnostics = lint(result)
        codes = {item.code for item in diagnostics}
        self.assertTrue(
            {"arity", "deprecated-function", "unknown-function", "removed-function", "removed-constant", "unknown-event"}
            <= codes
        )
        messages = {item.message for item in diagnostics}
        self.assertIn("state_entry is not an SLua event", messages)
        self.assertIn("unknown event not_an_event", messages)
        self.assertIn("ll.SetTimerEvent is not available in SLua", messages)
        self.assertTrue(any(item.code == "deprecated-function" and item.message.startswith("llcompat.Say is deprecated") and "Use " not in item.message for item in diagnostics))
        self.assertFalse(any("assert takes" in item.message or "error takes" in item.message for item in diagnostics))


if __name__ == "__main__":
    unittest.main()
