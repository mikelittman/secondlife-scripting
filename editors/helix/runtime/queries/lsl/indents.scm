(compound_statement
  "{" @start
  "}" @end) @indent

(state_definition
  "{" @start
  "}" @end) @indent

(vector_literal
  "<" @start
  ">" @end) @indent

(quaternion_literal
  "<" @start
  ">" @end) @indent

(list_literal
  "[" @start
  "]" @end) @indent

(parameter_list
  "(" @start
  ")" @end) @indent
