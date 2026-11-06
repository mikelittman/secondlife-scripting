; Named functions. `function() ... end` expressions have no name field.
(function_declaration
  name: (identifier) @name) @item

(function_declaration
  name: (dot_index_expression
    field: (identifier) @name)) @item

(function_declaration
  name: (method_index_expression
    method: (identifier) @name)) @item

(type_definition
  name: (type) @name) @item
