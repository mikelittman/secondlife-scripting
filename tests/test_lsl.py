import unittest

from lsl_tools.lsl.format import Style, format_source
from lsl_tools.lsl.lint import lint
from lsl_tools.lsl.parser import parse

SAMPLE = """
integer g = 1;

string greet(string name) {
    return "Hello, " + name;
}

default {
    state_entry() {
        llOwnerSay(greet("world"));
        vector v = <1.0, 2.0, 3.0>;
        if (v.x > 0) {
            state other;
        }
    }
    touch_start(integer total_number) {
        @again;
        jump again;
    }
}

state other {
    state_entry() {
        llSay(0, (string)g);
        llCloud(<0,0,1>);
    }
}
"""


class LslParserTests(unittest.TestCase):
    def test_structure(self):
        result = parse(SAMPLE)
        self.assertEqual(result.errors, [])
        tree = result.tree
        self.assertEqual([item.get("name") for item in tree.get("globals")], ["g", "greet"])
        self.assertEqual([item.get("name") for item in tree.get("states")], ["default", "other"])
        events = tree.get("states")[0].get("events")
        self.assertEqual([event.get("name") for event in events], ["state_entry", "touch_start"])
        say = events[0].get("body").get("statements")[0].get("expression")
        self.assertEqual(say.kind, "call_expression")
        self.assertEqual(say.get("name"), "llOwnerSay")

    def test_vector_is_not_a_comparison(self):
        result = parse("default { state_entry() { vector v = <1, 2, 3>; rotation r = <0, 0, 0, 1>; } }\n")
        self.assertEqual(result.errors, [])
        statements = result.tree.get("states")[0].get("events")[0].get("body").get("statements")
        self.assertEqual(statements[0].get("init").kind, "vector_literal")
        self.assertEqual(statements[1].get("init").kind, "quaternion_literal")

    def test_casts_lists_and_updates(self):
        source = "default { state_entry() { integer n = (integer)1.5; list box = [1, <2, 3, 4>]; n++; --n; } }\n"
        result = parse(source)
        self.assertEqual(result.errors, [])
        body = result.tree.get("states")[0].get("events")[0].get("body").get("statements")
        self.assertEqual(body[0].get("init").kind, "cast_expression")
        self.assertEqual(body[1].get("init").kind, "list_literal")
        self.assertEqual(body[2].kind, "expression_statement")
        self.assertFalse(body[2].get("expression").get("prefix"))
        self.assertTrue(body[3].get("expression").get("prefix"))

    def test_comments_and_strings(self):
        source = 'default {\n// lead\nstate_entry() {\nllOwnerSay("say \\"hi\\"\\n"); // trail\n}\n}\n'
        result = parse(source)
        self.assertEqual(result.errors, [])
        event = result.tree.get("states")[0].get("events")[0]
        self.assertTrue(any("lead" in comment for comment in event.leading))
        statement = event.get("body").get("statements")[0]
        self.assertTrue(any("trail" in comment for comment in statement.trailing))
        self.assertIn('\\"hi\\"', statement.get("expression").get("args")[0].get("raw"))

    def test_format_is_stable(self):
        result = parse(SAMPLE)
        self.assertEqual(result.errors, [])
        once = format_source(result, Style())
        again = format_source(parse(once), Style())
        self.assertEqual(once, again)
        self.assertIn("llOwnerSay(greet(\"world\"));", once)
        self.assertIn("vector v = <1.0, 2.0, 3.0>;", once)
        self.assertIn("state other;", once)

    def test_format_reindents_like_a_javascript_formatter(self):
        source = """
integer g=1;
string greet(string name){
return "Hello, "+name;
}
default{
state_entry(){
llOwnerSay(greet("world"));
vector v=<1,2,3>;
if(v.x>0){
state other;
}else if(v.x<0){
llSay(0,"no");
}else{
llSay(0,"zero");
}
for(integer i=0;i<3;++i){
llOwnerSay((string)i);
}
for(i=0,g=1;i<2;i++,g++){
llOwnerSay((string)i);
}
}
touch_start(integer n){@again;jump again;}
}
state other{state_entry(){llSay(0,(string)g);}}
"""
        result = parse(source)
        self.assertEqual(result.errors, [])
        formatted = format_source(result, Style())
        self.assertEqual(formatted, format_source(parse(formatted), Style()))
        self.assertIn("    return \"Hello, \" + name;", formatted)
        self.assertIn("        vector v = <1, 2, 3>;", formatted)
        self.assertIn("        } else if (v.x < 0) {", formatted)
        self.assertIn("        for (integer i = 0; i < 3; ++i) {", formatted)
        self.assertIn("        for (i = 0, g = 1; i < 2; i++, g++) {", formatted)
        self.assertIn("            llOwnerSay((string)i);", formatted)

    def test_format_keeps_global_variables_compact(self):
        source = "integer a=1;\n\n\nfloat b = 2.0;\nkey id=NULL_KEY;\n\nstring greet(string name) {\nreturn name;\n}\n\ndefault {\nstate_entry() {\nllOwnerSay(greet((string)a));\n}\n}\n"
        formatted = format_source(parse(source), Style())
        self.assertIn("integer a = 1;\nfloat b = 2.0;\nkey id = NULL_KEY;\n\nstring greet", formatted)
        self.assertEqual(formatted, format_source(parse(formatted), Style()))

    def test_unexpected_token_does_not_crash(self):
        result = parse("default { state_entry() { $$$; } }\n")
        self.assertTrue(result.errors)
        self.assertEqual(format_source(result, Style()), "default { state_entry() { $$$; } }\n")

    def test_format_keeps_a_comment_inside_an_expression(self):
        source = "default { state_entry() { llSay(0, /* channel */ \"x\"); } }\n"
        formatted = format_source(parse(source), Style())
        self.assertIn("/* channel */", formatted)
        self.assertEqual(formatted, format_source(parse(formatted), Style()))

    def test_lint_finds_library_problems(self):
        source = """
default {
    state_entry() {
        llOwnerSay();
        llCloud(<0, 0, 1>);
        llNotARealFunction(1);
        if (g = 1) { jump missing; }
    }
    touch_start() { }
    no_such_event() { }
}
state bare { }
"""
        result = parse(source)
        self.assertEqual(result.errors, [])
        codes = {item.code for item in lint(result)}
        self.assertTrue(
            {"arity", "deprecated-function", "unknown-function", "assignment-in-condition", "event-arity", "unknown-event", "empty-state"}
            <= codes
        )


if __name__ == "__main__":
    unittest.main()
