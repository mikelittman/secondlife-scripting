; Luau blocks close with `end`. These node names match tree-sitter-luau.

[
  (function_declaration)
  (function_definition)
  (if_statement)
  (for_statement)
  (while_statement)
  (do_statement)
  (repeat_statement)
] @indent

"end" @outdent
"}" @outdent
