/**
 * Tree-sitter grammar for Linden Scripting Language.
 *
 * The shape follows Tailslide's lslmini.y (the Second Life parser). The editor
 * grammar is intentionally a little more permissive: a file may be missing its
 * default state, and a for-loop condition may be absent, so highlighting still
 * works while the user is typing. A for-loop may also declare its counter
 * (`for (integer i = 0; i < n; ++i)`), which the Second Life compiler accepts.
 */

const PREC = {
  assign: 1,
  logical: 2,
  bitOr: 3,
  bitXor: 4,
  bitAnd: 5,
  equality: 6,
  compare: 7,
  shift: 8,
  add: 9,
  mul: 10,
  prefix: 11,
  postfix: 12,
  call: 13,
};

const assignOp = choice("=", "+=", "-=", "*=", "/=", "%=");
const exprList = (rule) => seq(rule, repeat(seq(",", rule)));

module.exports = grammar({
  name: "lsl",

  extras: ($) => [/\s/, $.comment],
  word: ($) => $.identifier,

  rules: {
    script: ($) => seq(repeat($.global), repeat($.state_definition)),

    global: ($) => choice($.global_variable, $.function_definition),

    global_variable: ($) =>
      seq(
        field("type", $.type),
        field("name", $.identifier),
        optional(seq("=", field("value", $._expression))),
        ";",
      ),

    function_definition: ($) =>
      seq(
        optional(field("type", $.type)),
        field("name", $.identifier),
        field("parameters", $.parameter_list),
        field("body", $.compound_statement),
      ),

    parameter_list: ($) => seq("(", optional(exprList($.parameter)), ")"),
    parameter: ($) => seq(field("type", $.type), field("name", $.identifier)),

    state_definition: ($) =>
      seq(
        choice(field("name", alias("default", $.identifier)), seq("state", field("name", $.identifier))),
        "{",
        repeat($.event_handler),
        "}",
      ),

    event_handler: ($) =>
      seq(
        field("name", $.identifier),
        field("parameters", $.parameter_list),
        field("body", $.compound_statement),
      ),

    compound_statement: ($) => seq("{", repeat($.statement), "}"),

    statement: ($) =>
      choice(
        $.empty_statement,
        $.compound_statement,
        $.declaration,
        $.if_statement,
        $.for_statement,
        $.while_statement,
        $.do_statement,
        $.jump_statement,
        $.label,
        $.return_statement,
        $.state_statement,
        $.expression_statement,
      ),

    empty_statement: ($) => ";",
    declaration: ($) =>
      seq(
        field("type", $.type),
        field("name", $.identifier),
        optional(seq("=", field("value", $._expression))),
        ";",
      ),
    expression_statement: ($) => seq($._expression, ";"),
    jump_statement: ($) => seq("jump", field("name", $.identifier), ";"),
    label: ($) => seq("@", field("name", $.identifier), ";"),
    return_statement: ($) => seq("return", optional($._expression), ";"),
    state_statement: ($) => seq("state", field("name", choice($.identifier, alias("default", $.identifier))), ";"),

    if_statement: ($) =>
      prec.right(
        seq(
          "if",
          "(",
          field("condition", $._expression),
          ")",
          field("consequence", $.statement),
          optional(seq("else", field("alternative", $.statement))),
        ),
      ),

    while_statement: ($) =>
      seq("while", "(", field("condition", $._expression), ")", field("body", $.statement)),

    do_statement: ($) =>
      seq("do", field("body", $.statement), "while", "(", field("condition", $._expression), ")", ";"),

    for_statement: ($) =>
      seq(
        "for",
        "(",
        optional(
          choice(field("declaration", $.for_declaration), field("init", $._expr_list)),
        ),
        ";",
        optional(field("condition", $._expression)),
        ";",
        optional(field("step", $._expr_list)),
        ")",
        field("body", $.statement),
      ),

    for_declaration: ($) =>
      seq(
        field("type", $.type),
        field("name", $.identifier),
        optional(seq("=", field("value", $._expression))),
      ),

    _expr_list: ($) => exprList($._expression),

    _expression: ($) =>
      choice(
        $.assignment_expression,
        $.binary_expression,
        $.unary_expression,
        $.update_expression,
        $.cast_expression,
        $.call_expression,
        $.print_expression,
        $.member_expression,
        $.vector_literal,
        $.quaternion_literal,
        $.list_literal,
        $.parenthesized_expression,
        $.identifier,
        $.number,
        $.string,
      ),

    assignment_expression: ($) =>
      prec.right(
        PREC.assign,
        seq(field("left", $._expression), field("operator", assignOp), field("right", $._expression)),
      ),

    binary_expression: ($) => {
      const operators = [
        [prec.left, PREC.logical, choice("&&", "||")],
        [prec.left, PREC.bitOr, "|"],
        [prec.left, PREC.bitXor, "^"],
        [prec.left, PREC.bitAnd, "&"],
        [prec.left, PREC.equality, choice("==", "!=")],
        [prec.left, PREC.compare, choice("<", ">", "<=", ">=")],
        [prec.left, PREC.shift, choice("<<", ">>")],
        [prec.left, PREC.add, choice("+", "-")],
        [prec.left, PREC.mul, choice("*", "/", "%")],
      ];
      return choice(
        ...operators.map(([assoc, level, operator]) =>
          assoc(
            level,
            seq(field("left", $._expression), field("operator", operator), field("right", $._expression)),
          ),
        ),
      );
    },

    unary_expression: ($) =>
      prec.right(PREC.prefix, seq(field("operator", choice("-", "!", "~")), field("operand", $._expression))),

    update_expression: ($) =>
      choice(
        prec.right(PREC.prefix, seq(field("operator", choice("++", "--")), field("operand", $._lvalue))),
        prec.left(PREC.postfix, seq(field("operand", $._lvalue), field("operator", choice("++", "--")))),
      ),

    cast_expression: ($) =>
      prec.right(PREC.prefix, seq("(", field("type", $.type), ")", field("operand", $._expression))),

    call_expression: ($) =>
      prec(
        PREC.call,
        seq(field("name", $.identifier), "(", optional(field("arguments", $._expr_list)), ")"),
      ),

    print_expression: ($) => seq("print", "(", field("operand", $._expression), ")"),

    member_expression: ($) =>
      prec.left(PREC.postfix, seq(field("object", $.identifier), ".", field("field", $.identifier))),

    _lvalue: ($) => choice($.identifier, $.member_expression),

    vector_literal: ($) =>
      prec(
        PREC.postfix,
        seq("<", field("x", $._expression), ",", field("y", $._expression), ",", field("z", $._expression), ">"),
      ),

    quaternion_literal: ($) =>
      prec(
        PREC.postfix + 1,
        seq(
          "<",
          field("x", $._expression),
          ",",
          field("y", $._expression),
          ",",
          field("z", $._expression),
          ",",
          field("s", $._expression),
          ">",
        ),
      ),

    list_literal: ($) => seq("[", optional($._expr_list), "]"),
    parenthesized_expression: ($) => seq("(", $._expression, ")"),

    type: ($) => choice("integer", "float", "string", "key", "vector", "quaternion", "rotation", "list"),

    identifier: ($) => /[A-Za-z_][A-Za-z0-9_]*/,
    number: ($) =>
      token(
        choice(
          /0[xX][0-9a-fA-F]+/,
          /\d+[eE][+-]?\d+[fF]?/,
          /\d*\.\d+([eE][+-]?\d+)?[fF]?/,
          /\d+\.\d*([eE][+-]?\d+)?[fF]?/,
          /\d+/,
        ),
      ),
    string: ($) =>
      token(
        seq(
          optional("L"),
          '"',
          repeat(choice(/[^"\\\n]/, /\n/, /\\./, /\\\r?\n/)),
          '"',
        ),
      ),
    comment: ($) =>
      token(
        choice(
          seq("//", /[^\n]*/),
          seq("/*", /[^*]*\*+([^/*][^*]*\*+)*/, "/"),
        ),
      ),
  },
});
