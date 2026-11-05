; Highlight rules for LSL. Capture names are the ones Gram and Zed themes understand.

[
  "state"
  "jump"
  "return"
  "if"
  "else"
  "for"
  "do"
  "while"
] @keyword

(state_definition
  name: (identifier) @keyword
  (#eq? @keyword "default"))

"print" @keyword

(type) @type

(string) @string
(number) @number
(comment) @comment

[
  "="
  "+="
  "-="
  "*="
  "/="
  "%="
  "+"
  "-"
  "*"
  "/"
  "%"
  "=="
  "!="
  "<"
  ">"
  "<="
  ">="
  "&&"
  "||"
  "!"
  "&"
  "|"
  "^"
  "~"
  "<<"
  ">>"
  "++"
  "--"
] @operator

[
  "("
  ")"
  "["
  "]"
  "{"
  "}"
  "<"
  ">"
] @punctuation.bracket

[
  ";"
  ","
  "."
  "@"
] @punctuation.delimiter

(identifier) @variable

(parameter name: (identifier) @variable.parameter)
(declaration name: (identifier) @variable)
(global_variable name: (identifier) @variable)

(function_definition name: (identifier) @function)
(call_expression name: (identifier) @function)
(event_handler name: (identifier) @function)
(state_definition name: (identifier) @type)
(label name: (identifier) @label)
(jump_statement name: (identifier) @label)

(member_expression field: (identifier) @property)

; Library functions are ll followed by an uppercase letter. The linter, not this
; pattern, decides whether the name really exists.
((call_expression
  name: (identifier) @function.builtin)
  (#match? @function.builtin "^ll[A-Z]"))

((identifier) @constant
  (#match? @constant "^[A-Z][A-Z0-9_]*$"))
